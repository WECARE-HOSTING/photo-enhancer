#!/usr/bin/env python3
"""Turn `picks.txt` into a drop that `1 - input/` already knows how to eat.

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

Output lands in `1 - input/<shoot>/` under the name it keeps for the rest of its
life — `SALA_01_0002.jpg`. The ambiente and the room were settled by `cull.py` and
are read from `ambientes.md`; the only thing decided here is the number, because
only here is it known which photographs were actually picked. Numbering earlier
would leave gaps where the unpicked ones were.

    ambientes.md      SALA / room 01     <- cull.py decided this
    picks.txt         2_Sala Cobertura_11.JPG, 2_Sala Cobertura_23.JPG
    ->                SALA_01_0001.jpg, SALA_01_0002.jpg

Nothing downstream renames it: `organize.py` only gathers photos into a job, and
`enhance.py` only appends `_edit`. Read `0 - selection/CONTEXT.md`.
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
import ambientes  # noqa: E402

SELECTION_DIR = Path(__file__).resolve().parent
ROOT = SELECTION_DIR.parent
INPUT_DIR = ROOT / "1 - input"

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

def read_picks(job: Path) -> "list[list[str]]":
    """Parse `picks.txt` into a list of scenes, each a list of frame names."""
    path = job / "picks.txt"
    if not path.exists():
        sys.exit(f"error: no {rel(path)}.\n"
                 "       Open contact.html, tick your choices, press "
                 "'Copy picks.txt',\n"
                 f"       and paste it into {rel(path)}.")
    scenes = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        frames = [f.strip() for f in line.split("+") if f.strip()]
        if frames:
            scenes.append(frames)
    if not scenes:
        sys.exit(f"error: {rel(path)} lists no photos")
    return scenes


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


# ----------------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("shoot", help="the shoot folder, e.g. '0 - selection/Cobertura'")
    ap.add_argument("--workers", type=int, default=WORKERS,
                    help=f"picks developed at once (default {WORKERS})")
    ap.add_argument("--name", help="folder name to create in 1 - input/ "
                                   "(default: the shoot's own name)")
    ap.add_argument("--prune", action="store_true",
                    help="delete _proxies/ afterwards. Never touches source/ — "
                         "that is the only thing a re-pick needs.")
    ap.add_argument("--force", action="store_true",
                    help="overwrite an existing folder in 1 - input/")
    args = ap.parse_args()

    job = Path(args.shoot)
    if not job.is_absolute():
        job = (ROOT / args.shoot) if (ROOT / args.shoot).exists() \
            else (SELECTION_DIR / args.shoot)
    if not job.is_dir():
        sys.exit(f"error: no such shoot folder: {args.shoot}")
    source = job / "source"
    if not source.is_dir():
        sys.exit(f"error: {rel(job)} has no source/ — run fetch.py first")

    scenes = read_picks(job)
    index = index_source(source)

    resolved, missing = [], []
    for frames in scenes:
        try:
            resolved.append(resolve(frames, index))
        except DevelopError as e:
            missing.append(str(e))

    out_dir = INPUT_DIR / (args.name or job.name)
    if out_dir.exists() and any(out_dir.iterdir()):
        if not args.force:
            sys.exit(f"error: {rel(out_dir)} already has files in it.\n"
                     "       Use --force to replace it, or --name for a different "
                     "folder.")
        shutil.rmtree(out_dir)

    brackets = sum(1 for r in resolved if len(r) > 1)
    raws = sum(1 for r in resolved if r[0].suffix.lower() in RAW_EXTS)

    print(f"\n{job.name} · {len(resolved)} pick(s) from picks.txt"
          f"{f', {len(missing)} unresolved' if missing else ''}")
    for m in missing:
        print(f"  !! {m}")
    if missing:
        print("\n   Those names are not in source/. Fix the lines in picks.txt and\n"
              "   run this again — nothing has been written yet.")
        sys.exit(1)

    catalog = ambientes.read_catalog(job)
    if not catalog:
        sys.exit(f"error: no {rel(job / ambientes.CATALOG_NAME)}.\n"
                 "       That file is where the room names live, and the delivered "
                 "filenames are\n       built from it. Run cull.py on this shoot "
                 "first:\n"
                 f'         ./_config/.venv/bin/python "0 - selection/cull.py" '
                 f'"{rel(job)}"')
    names, unnamed = assign_names(resolved, catalog)
    for u in unnamed:
        print(f"  !! {u}")
    if unnamed:
        print(f"\n   {len(unnamed)} pick(s) have no room in "
              f"{rel(job / ambientes.CATALOG_NAME)}, so they cannot be\n"
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

    if args.prune:
        proxies = job / "_proxies"
        if proxies.is_dir():
            n = sum(1 for _ in proxies.rglob("*"))
            shutil.rmtree(proxies)
            print(f"pruned      {n} proxy file(s); source/ left alone")

    print(f"\nThe drop is ready, and these {tally['ok']} name(s) are final — "
          "`organize.py` gathers them\ninto a job without renaming anything, and "
          "`enhance.py` only appends `_edit`.\nThe photographer's original filenames "
          "are recorded in job.md. Then:\n")
    print('  ./_config/.venv/bin/python "1 - input/organize.py"')
    print('  ./_config/.venv/bin/python "2 - in progress/batch.py"')


if __name__ == "__main__":
    main()
