#!/usr/bin/env python3
"""Turn `picks.txt` into a job, and develop the whole delivery while at it.

    ./_config/.venv/bin/python "0 - selection/develop.py" "0 - selection/Cobertura"
    ./_config/.venv/bin/python "0 - selection/develop.py" "0 - selection/Cobertura" --prune

**Your picks are final here.** This script does not re-apply the quota, drop a
flagged frame, or reconsider anything — `cull.py` had its say on the contact
sheet and lost the argument the moment you edited the list. All that happens now
is mechanical: raw files get developed, brackets get merged, and everything gets
numbered in the order you listed it.

Three shapes come in and one goes out:

- **JPEG** → resized, nothing else touched.
- **RAW** → developed through libraw at the camera's own white balance.
- **A bracket** (`a.NEF+b.NEF+c.NEF` on one line) → aligned and fused into a
  single frame with real detail in the windows.

That last one is fidelity, not polish. The project's one rule is *enhance the
real photo, never recreate it*. Send `gpt-image-2` the middle frame of a bracket
and the window is a white rectangle, so the model **invents** the view — a
different building, a different sky. Fuse the bracket first and it is given the
view that was actually there.

The picks land in `1 - edit/Job_NNNN/` under the name they keep for the rest of
their lives — `SALA_01_0002.jpg`. The ambiente and the room were settled by
`cull.py` and are read from `ambientes.md`; the only thing decided here is the
number, because only here is it known which photographs were actually picked.
Numbering earlier would leave gaps where the unpicked ones were.

    ambientes.md      SALA / room 01     <- cull.py decided this
    picks.txt         2_Sala Cobertura_11.JPG, 2_Sala Cobertura_23.JPG
    ->                SALA_01_0001.jpg, SALA_01_0002.jpg

**This is where a job is born.** The number is minted here and nowhere else,
because this is the one moment in the pipeline when the shoot's name and a fresh
job number are in the same process — and the archive, three stages later, needs
that link to know which delivery a finished job came out of. It goes into
`job.md` as `**Shoot:**`.

**The photographs nobody picked are developed too**, at the same 2400px, into
`<shoot>/developed/`. They travel into the archive when the job is approved, so
a finished job holds the whole delivery. That is what makes the camera originals
deletable afterwards — see `archive.py --purge-source`.

Nothing downstream renames anything: `enhance.py` only appends `_edit` and
`marca.py` only `_final`. Read `0 - selection/CONTEXT.md`.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps
from pillow_heif import register_heif_opener

# Same reason as ingest.py: Pillow cannot open a phone's .heic without this,
# and it must be registered before the first Image.open().
register_heif_opener()

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_config"))
import ambientes  # noqa: E402
import gate  # noqa: E402
import ledger  # noqa: E402
import paths  # noqa: E402
import stage  # noqa: E402

SELECTION_DIR = paths.SELECTION_DIR
ROOT = paths.ROOT

# Where the developed picks land, as a whole job. This is the moment the shoot
# name and a fresh job number are in the same process, which is why the number
# is minted here and not downstream: the archive needs that link to know which
# delivery a finished job came out of.
EDIT_DIR = paths.EDIT_DIR

# The unpicked photographs, developed to the same size as the picks and left in
# the shoot until the job is archived. 2400px for everything, not the 1600px
# proxies, because the camera originals are meant to be deletable afterwards —
# and a 1600px archive copy would cap every future re-pick below the 2048px the
# pipeline delivers.
REST_DIR = "developed"

STAGE = SELECTION_DIR.name

RAW_EXTS = {
    ".nef", ".nrw", ".cr2", ".cr3", ".crw", ".arw", ".srf", ".sr2", ".raf",
    ".orf", ".rw2", ".pef", ".dng", ".srw", ".3fr", ".fff", ".iiq", ".erf",
    ".mos", ".mrw", ".x3f",
}
PHOTO_EXTS = RAW_EXTS | {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff",
                         ".heic", ".heif"}

# The whole pipeline tops out at 2048px: `enhance.py` downscales its upload to
# that and the model renders there too. A little headroom above it costs nothing
# and leaves room for a crop, but there is no point carrying a 6000px file
# through a stage that will throw the pixels away.
DEVELOP_LONG_EDGE = 2400
DEVELOP_JPEG_QUALITY = 94

WORKERS = 4


class DevelopError(Exception):
    """One pick failed. Raised so the rest of the list still gets done."""


def rel(p: Path) -> str:
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)


# Third place in this project where matching a filename matters, and the reason it
# does here: `picks.txt` came back through a browser and a clipboard, either of
# which may have composed the accents that macOS stores decomposed, so `Suíte`
# typed by a person and `Suíte` on disk are different strings for the same file.
# One owner for the answer — see `ambientes.fold_name`.
fold = ambientes.fold_name


# ------------------------------------------------------------------- the picks

def read_picks(shoot: Path) -> "tuple[list[list[str]], dict[str, str]]":
    """Parse `picks.txt` into scenes, plus whatever you wrote about each.

    Returns (scenes, comments-by-first-frame). A trailing `#` is a comment, not
    part of a filename — without this a single note on the sheet made `resolve()`
    fail to find the file and killed the entire hand-off, for one sentence.
    """
    path = shoot / "picks.txt"
    if not path.exists():
        sys.exit(f"error: no {rel(path)}.\n"
                 f"       Open {gate.PAGES['selection']}, tick your choices, "
                 "press 'Copiar picks',\n"
                 f"       and paste it into {rel(path)}.")
    scenes: "list[list[str]]" = []
    notes: "dict[str, str]" = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        body, _, note = line.partition("#")
        frames = [f.strip() for f in body.split("+") if f.strip()]
        if frames:
            scenes.append(frames)
            if note.strip():
                notes[frames[0]] = note.strip()
    if not scenes:
        sys.exit(f"error: {rel(path)} lists no photos")
    return scenes, notes


def index_source(source: Path) -> "dict[str, Path]":
    by_name: "dict[str, Path]" = {}
    for p in source.rglob("*"):
        if p.is_file() and p.suffix.lower() in PHOTO_EXTS:
            by_name.setdefault(fold(p.name), p)
            by_name.setdefault(fold(p.stem), p)
    return by_name


def resolve(frames: "list[str]", index: "dict[str, Path]") -> "list[Path]":
    out = []
    for name in frames:
        hit = index.get(fold(name)) or index.get(fold(Path(name).name)) \
            or index.get(fold(Path(name).stem))
        if hit is None:
            raise DevelopError(f"no such file in source/: {name}")
        out.append(hit)
    return out


# ------------------------------------------------------------------ developing

def load_raw(path: Path) -> np.ndarray:
    """Develop one raw file to RGB, camera white balance, no auto-brightening.

    `half_size` halves each dimension, which on a 24MP body still lands near
    3000px — above the pipeline's ceiling — and is roughly four times faster than
    a full demosaic. Auto-brightness stays off because `PROMPT.md` is what decides
    how the photograph is lit, and a libraw guess here would fight it.
    """
    import rawpy
    try:
        with rawpy.imread(str(path)) as raw:
            return raw.postprocess(half_size=True, use_camera_wb=True,
                                   no_auto_bright=True, output_bps=8)
    except Exception as e:                       # noqa: BLE001
        raise DevelopError(f"libraw could not develop it: {type(e).__name__}: {e}")


def load_frame(path: Path) -> np.ndarray:
    """One frame as an RGB array, honouring EXIF orientation."""
    if path.suffix.lower() in RAW_EXTS:
        return load_raw(path)
    try:
        with Image.open(path) as im:
            return np.asarray(ImageOps.exif_transpose(im).convert("RGB"))
    except Exception as e:                       # noqa: BLE001
        raise DevelopError(f"could not read it: {type(e).__name__}: {e}")


def fuse_bracket(paths: "list[Path]") -> np.ndarray:
    """Align and fuse an exposure bracket into one frame.

    Mertens exposure fusion rather than an HDR tone-map: it picks the
    best-exposed, best-contrasted, most-saturated pixels from across the stack
    and blends them, which yields a normal-looking photograph instead of the
    flat, grey, obviously-processed HDR look. Nothing to tone-map afterwards, and
    nothing that reads as "an HDR".

    Alignment runs first because even a tripod drifts between frames, and a
    misaligned fusion ghosts along every edge. On a truly static stack it is a
    no-op that costs a second.
    """
    import cv2

    frames = [load_frame(p) for p in paths]
    shapes = {f.shape for f in frames}
    if len(shapes) != 1:
        # A stack whose frames disagree on size is not a bracket — most likely
        # `picks.txt` joined two unrelated photographs with a `+`.
        raise DevelopError(
            "these frames are different sizes, so they are not one bracket: "
            + ", ".join(f"{p.name} {f.shape[1]}x{f.shape[0]}"
                        for p, f in zip(paths, frames)))

    bgr = [f[:, :, ::-1].copy() for f in frames]
    try:
        cv2.createAlignMTB().process(bgr, bgr)
    except Exception:                            # noqa: BLE001 — alignment is optional
        pass
    fused = cv2.createMergeMertens().process(bgr)
    out = np.clip(fused * 255.0, 0, 255).astype(np.uint8)
    return out[:, :, ::-1]                       # back to RGB


def write_output(rgb: np.ndarray, dest: Path) -> "tuple[int, int]":
    im = Image.fromarray(rgb)
    im.thumbnail((DEVELOP_LONG_EDGE, DEVELOP_LONG_EDGE), Image.LANCZOS)
    dest.parent.mkdir(parents=True, exist_ok=True)
    im.save(dest, "JPEG", quality=DEVELOP_JPEG_QUALITY, optimize=True,
            subsampling=0)
    return im.size


def assign_names(resolved: "list[list[Path]]",
                 catalog: "dict[str, ambientes.Row]"
                 ) -> "tuple[list[str], list[str]]":
    """Name every pick `AMBIENTE_NN_NNNN.jpg`. Returns (names, problems).

    The ambiente and the room come from `ambientes.md` and are not second-guessed
    here — `cull.py` decided them, with a model's help and possibly with yours, and
    this script's whole contract is that it does not reconsider. All that is added
    is the counter, restarted per room and following the order of `picks.txt`,
    which is the order of the contact sheet.

    A pick that is not in the catalogue is a problem, not a fallback name. Guessing
    would produce a file whose name claims a room nobody verified, and that name
    then travels to a client — so it is reported and the run writes nothing, the
    same way an unresolvable filename already behaves.
    """
    counters: "dict[tuple[str, int], int]" = {}
    names: "list[str]" = []
    problems: "list[str]" = []
    for paths in resolved:
        row = next((catalog[k] for k in (fold(p.name) for p in paths)
                    if k in catalog), None)
        if row is None:
            problems.append(f"not in {ambientes.CATALOG_NAME}: "
                            f"{'+'.join(p.name for p in paths)}")
            names.append("")
            continue
        key = (row.ambiente, row.sala)
        counters[key] = counters.get(key, 0) + 1
        names.append(ambientes.format_name(row.ambiente, row.sala,
                                           counters[key]) + ".jpg")
    return names, problems


def develop_one(n: int, name: str, paths: "list[Path]",
                out_dir: Path) -> "tuple[int, str, list[str]]":
    """Develop one pick. Returns (n, status, log lines). Runs in a worker."""
    lines: "list[str]" = []
    t0 = time.time()
    try:
        dest = out_dir / name
        if len(paths) > 1:
            rgb = fuse_bracket(paths)
            how = f"fused {len(paths)} frames"
        else:
            rgb = load_frame(paths[0])
            how = "developed raw" if paths[0].suffix.lower() in RAW_EXTS else "resized"
        w, h = write_output(rgb, dest)
        lines.append(f"{dest.name:<44s} {how}, {w}x{h}, {time.time() - t0:.1f}s")
        return n, "ok", lines
    except DevelopError as e:
        lines.append(f"{'+'.join(p.name for p in paths):<44s} FAILED — {e}")
        return n, "failed", lines
    except Exception as e:                       # noqa: BLE001 — one bad pick must not stop the rest
        lines.append(f"{'+'.join(p.name for p in paths):<44s} FAILED — "
                     f"{type(e).__name__}: {e}")
        return n, "failed", lines


# ------------------------------------------------------- the rest of the shoot

def develop_rest(shoot: Path, picked: "set[Path]", workers: int) -> "list[Path]":
    """Develop everything that was NOT picked, at the same size as the picks.

    Idempotent — a file already in `developed/` is left alone, so re-running
    after a corrected pick costs seconds rather than redoing 244 photographs.

    This is the step that makes deleting the camera originals safe later. The
    1600px proxies `ingest.py` already made would have been free, but they are
    below the 2048px this pipeline delivers, and a discarded photograph you
    might promote later deserves the same resolution as one you kept.
    """
    out = shoot / REST_DIR
    todo = []
    for p in sorted(shoot.joinpath("source").rglob("*")):
        if not (p.is_file() and p.suffix.lower() in PHOTO_EXTS) or p in picked:
            continue
        dest = out / f"{p.stem}.jpg"
        if not dest.exists():
            todo.append((p, dest))

    if not todo:
        return sorted(out.glob("*.jpg")) if out.is_dir() else []

    out.mkdir(exist_ok=True)
    print(f"\nrestante    {len(todo)} não escolhida(s) -> {rel(out)}/  "
          f"(local, sem API)")
    done = 0
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(_develop_plain, src, dest): src
                   for src, dest in todo}
        for fut in as_completed(futures):
            ok, msg = fut.result()
            done += ok
            if msg:
                print(f"  !! {msg}")
            if done and done % 50 == 0:
                print(f"  {done}/{len(todo)}")
    print(f"  {done}/{len(todo)} reveladas")
    return sorted(out.glob("*.jpg"))


def _develop_plain(src: Path, dest: Path) -> "tuple[int, str]":
    try:
        write_output(load_frame(src), dest)
        return 1, ""
    except Exception as e:                       # noqa: BLE001 — one bad file is not fatal
        return 0, f"{src.name}: {type(e).__name__}: {e}"


# ------------------------------------------------------------------- the job

def source_label(scenes: "list[list[str]]", total: int, shoot: Path) -> str:
    """The `**Dropped as:**` value, kept in the shape `index.md` has always used."""
    return f"`{shoot.name}` — {len(scenes)} of {total} delivered"


def write_job_md(job_dir: Path, shoot: Path, scenes: "list[list[str]]",
                 resolved: "list[list[Path]]", names: "list[str]",
                 total: int) -> None:
    """The job's own front page, and the two lines other scripts parse out of it.

    `**Shoot:**` is what lets the archive find the delivery this job came from,
    three stages later. `**Dropped as:**` is what `index.md` shows. Both are
    frozen wire formats — change the wording and the reader silently falls back
    to a dash.
    """
    rows = [f"| `{name}` | `{'+'.join(p.name for p in paths_)}` |"
            for name, paths_ in zip(names, resolved)]
    (job_dir / "job.md").write_text(
        f"# {job_dir.name}\n\n"
        f"**Shoot:** `{rel(shoot)}`\n\n"
        f"**Dropped as:** {source_label(scenes, total, shoot)}\n\n"
        f"{len(names)} photo(s), developed by `0 - selection/develop.py` at "
        f"{DEVELOP_LONG_EDGE}px.\n\n"
        "| Photo | Came from |\n|---|---|\n" + "\n".join(rows) + "\n",
        encoding="utf-8")


def write_originais_md(job_dir: Path, shoot: Path, resolved: "list[list[Path]]",
                       names: "list[str]", rest: "list[Path]") -> None:
    """The manifest of the whole delivery, written while it is still knowable.

    Only here does one process know both which source file became which name and
    which ones were left out. Writing it now means `archive.py` copies a finished
    manifest instead of re-deriving it from a record it would have to read back.
    """
    became = {}
    for name, paths_ in zip(names, resolved):
        for p in paths_:
            became[p] = Path(name).stem

    rows = []
    for p in sorted(shoot.joinpath("source").rglob("*")):
        if not (p.is_file() and p.suffix.lower() in PHOTO_EXTS):
            continue
        mb = p.stat().st_size / 1e6
        got = became.get(p)
        rows.append(f"| `{p.relative_to(shoot / 'source')}` | {mb:.1f} MB | "
                    f"{'sim' if got else 'não'} | "
                    f"{f'`{got}`' if got else '—'} |")

    (job_dir / "originais.md").write_text(
        f"# {job_dir.name} — a entrega inteira\n\n"
        f"_As {len(rows)} fotos que `{shoot.name}` entregou, escolhidas ou não. "
        f"As imagens em si ficam\nao lado deste arquivo em `escolhidas/` e "
        f"`nao-escolhidas/`, todas a {DEVELOP_LONG_EDGE}px._\n\n"
        f"_{len(became)} escolhida(s) · {len(rest)} não escolhida(s) · o bruto "
        "da câmera pode ser apagado com\n"
        '`archive.py --purge-source` depois que este trabalho estiver '
        "arquivado._\n\n"
        "| Arquivo | Tamanho | Escolhida | Virou |\n|---|---|---|---|\n"
        + "\n".join(rows) + "\n",
        encoding="utf-8")


def write_shoot_gate(shoot: Path, job_dir: Path, scenes: "list[list[str]]",
                     notes: "dict[str, str]", total: int) -> None:
    """Record the selection decision, then copy it into the job.

    The shoot never travels — it receives and keeps — so the job gets a copy.
    That copy is what makes an archived job self-explaining once the shoot is
    gone: the picks, the room names, and whatever you wrote about them.
    """
    marks = [gate.Mark(key=frames[0], back=False, comment=notes.get(frames[0], ""))
             for frames in scenes if notes.get(frames[0])]
    n = gate.rounds_so_far(shoot, STAGE) + 1
    gate.fold(shoot, STAGE, n, marks, approved=len(scenes))
    ledger.append(paths.SELECTION_DIR, shoot.name, "gate", len(scenes),
                  f"{len(scenes)} de {total} escolhida(s), {len(marks)} "
                  f"comentada(s) · `{gate.RECORD}` rodada {n}")
    shutil.copy2(shoot / gate.RECORD, job_dir / gate.RECORD)


# ----------------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("shoot", help="the shoot folder, e.g. '0 - selection/Cobertura'")
    ap.add_argument("--workers", type=int, default=WORKERS,
                    help=f"picks developed at once (default {WORKERS})")
    ap.add_argument("--job", help="reuse this job number instead of minting one "
                                  "(only for a job still in 1 - edit/)")
    ap.add_argument("--prune", action="store_true",
                    help="delete _proxies/ afterwards. Never touches source/ or "
                         "developed/ — those are what a re-pick and the archive need.")
    ap.add_argument("--force", action="store_true",
                    help="replace the job folder in 1 - edit/. Refuses once it "
                         "holds paid results.")
    args = ap.parse_args()

    shoot = Path(args.shoot)
    if not shoot.is_absolute():
        shoot = (ROOT / args.shoot) if (ROOT / args.shoot).exists() \
            else (SELECTION_DIR / args.shoot)
    if not shoot.is_dir():
        sys.exit(f"error: no such shoot folder: {args.shoot}")
    source = shoot / "source"
    if not source.is_dir():
        sys.exit(f"error: {rel(shoot)} has no source/ — run fetch.py first")

    scenes, notes = read_picks(shoot)
    index = index_source(source)

    resolved, missing = [], []
    for frames in scenes:
        try:
            resolved.append(resolve(frames, index))
        except DevelopError as e:
            missing.append(str(e))

    # Mint the number here, and nowhere else. A name already used anywhere in
    # the pipeline is a hard stop: two photo sets under one number is worse than
    # a stopped run, and `add_to_index` would silently overwrite one row with
    # the other.
    existing = stage.all_job_dirs()
    if args.job:
        if args.job not in existing:
            sys.exit(f"error: {args.job} não existe em estágio nenhum.")
        out_dir = existing[args.job]
        if out_dir.parent != EDIT_DIR:
            sys.exit(f"error: {args.job} já saiu de {rel(EDIT_DIR)} — está em "
                     f"{rel(out_dir.parent)}/.\n       Um trabalho que já andou "
                     "não volta por aqui; use archive.py --return.")
    else:
        out_dir = EDIT_DIR / stage.new_job_name()

    if out_dir.exists() and any(out_dir.iterdir()):
        paid = sorted(out_dir.glob("*_edit*.jpg"))
        if paid:
            sys.exit(
                f"error: {rel(out_dir)} já tem {len(paid)} resultado(s) pagos "
                "da fal.ai dentro.\n       --force apagaria os arquivos, os "
                "logs que dizem qual prompt os fez, e\n       o registro do "
                "portão. Apague a pasta à mão se é isso mesmo que você quer.")
        if not args.force:
            sys.exit(f"error: {rel(out_dir)} já tem arquivos.\n"
                     "       Use --force para substituir.")
        shutil.rmtree(out_dir)

    brackets = sum(1 for r in resolved if len(r) > 1)
    raws = sum(1 for r in resolved if r[0].suffix.lower() in RAW_EXTS)

    print(f"\n{shoot.name} · {len(resolved)} pick(s) from picks.txt"
          f"{f', {len(missing)} unresolved' if missing else ''}")
    for m in missing:
        print(f"  !! {m}")
    if missing:
        print("\n   Those names are not in source/. Fix the lines in picks.txt and\n"
              "   run this again — nothing has been written yet.")
        sys.exit(1)

    catalog = ambientes.read_catalog(shoot)
    if not catalog:
        sys.exit(f"error: no {rel(shoot / ambientes.CATALOG_NAME)}.\n"
                 "       That file is where the room names live, and the delivered "
                 "filenames are\n       built from it. Run cull.py on this shoot "
                 "first:\n"
                 f'         ./_config/.venv/bin/python "0 - selection/cull.py" '
                 f'"{rel(shoot)}"')
    names, unnamed = assign_names(resolved, catalog)
    for u in unnamed:
        print(f"  !! {u}")
    if unnamed:
        print(f"\n   {len(unnamed)} pick(s) have no room in "
              f"{rel(shoot / ambientes.CATALOG_NAME)}, so they cannot be\n"
              "   named. Re-run cull.py to rebuild the catalogue — nothing has been "
              "written yet.")
        sys.exit(1)

    print(f"shapes      {len(resolved) - brackets - raws} jpeg · {raws} raw · "
          f"{brackets} bracket(s)")
    rooms = sorted({n.rsplit("_", 1)[0] for n in names})
    print(f"rooms       {len(rooms)}: {', '.join(rooms[:14])}"
          + (f" … +{len(rooms) - 14} more" if len(rooms) > 14 else ""))
    print(f"into        {rel(out_dir)}")
    print(f"size        {DEVELOP_LONG_EDGE}px long edge "
          f"(the pipeline renders at 2048)\n")

    t0 = time.time()
    tally = {"ok": 0, "failed": 0}
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = [pool.submit(develop_one, i, names[i - 1], paths, out_dir)
                   for i, paths in enumerate(resolved, 1)]
        for fut in sorted(as_completed(futures), key=lambda f: f.result()[0]):
            n, status, lines = fut.result()
            tally[status] += 1
            for line in lines:
                print(f"  {line}")

    elapsed = time.time() - t0
    print(f"\n=== {tally['ok']} developed · {tally['failed']} failed · "
          f"{elapsed:.0f}s ===")

    if tally["failed"]:
        print(f"\n{tally['failed']} pick(s) failed. Fix or remove those lines in "
              "picks.txt and re-run with --force.")
        return

    # Everything the delivery contained, not just what was kept. This is what
    # the archive will hold, and what makes deleting the camera originals a
    # decision rather than a loss.
    picked = {p for paths_ in resolved for p in paths_}
    rest = develop_rest(shoot, picked, args.workers)

    total = sum(1 for p in source.rglob("*")
                if p.is_file() and p.suffix.lower() in PHOTO_EXTS)
    write_job_md(out_dir, shoot, scenes, resolved, names, total)
    write_originais_md(out_dir, shoot, resolved, names, rest)
    write_shoot_gate(shoot, out_dir, scenes, notes, total)

    ledger.append(paths.SELECTION_DIR, shoot.name, "left", len(names),
                  f"-> `{rel(out_dir)}` · {total} entregues, {len(rest)} fora")
    ledger.append(EDIT_DIR, out_dir.name, "entered", len(names),
                  f"de `{rel(shoot)}` · {total} entregues, {len(rest)} não escolhidas")

    if args.prune:
        proxies = shoot / "_proxies"
        if proxies.is_dir():
            n = sum(1 for _ in proxies.rglob("*"))
            shutil.rmtree(proxies)
            print(f"pruned      {n} proxy file(s); source/ e developed/ intactos")

    paths.notify(out_dir.name, f"{tally['ok']} reveladas · pronto para editar")
    print(f"\n{out_dir.name} está pronto em {rel(out_dir)} — estes "
          f"{tally['ok']} nome(s) são finais e\nnada mais renomeia: `enhance.py` "
          "só acrescenta `_edit`, `marca.py` só `_final`.\n")
    print("  " + paths.cmd(EDIT_DIR / "batch.py"))


if __name__ == "__main__":
    main()
