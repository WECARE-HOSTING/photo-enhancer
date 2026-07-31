#!/usr/bin/env python3
"""Get a photographer's delivery onto disk, whole and verified.

    ./_config/.venv/bin/python "0 - selection/fetch.py" ~/Downloads/CasaNirvana-001.zip
    ./_config/.venv/bin/python "0 - selection/fetch.py" ~/Downloads/Casa\\ Nirvana/
    ./_config/.venv/bin/python "0 - selection/fetch.py" "gdrive:Shoots/Casa Nirvana"
    ./_config/.venv/bin/python "0 - selection/fetch.py" "https://drive.google.com/..."

Builds `0 - selection/<name>/source/` out of whatever was sent — a folder, one
zip, a pile of zips, a split archive, an rclone remote, a share link — and then
writes `fetch.md`: what arrived, what was thrown away as a duplicate, and
**which files are missing.**

That last part is the reason this script exists rather than a `unzip` command.
When you download a large folder from Google Drive's web interface, Drive zips
it server-side and *cuts it into pieces* — `Name-001.zip`, `Name-002.zip`, ...
Each piece opens on its own, so extracting one and moving on looks like it
worked. It didn't; you have a third of the shoot. Worse, Drive sometimes drops
files from the zip silently.

Camera filenames are sequential, so that is checkable rather than trustable:
`fetch.md` reports the numeric range it found and every hole in it. A hole can
be legitimate — the photographer deleted a bad frame — but a long run of holes,
especially at the end of the range, is a truncated download. You learn that here,
before spending CPU on proxies or money on the API.

Nothing is judged, renamed, or resized here. Read `0 - selection/CONTEXT.md`,
then run `cull.py`.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

SELECTION_DIR = Path(__file__).resolve().parent
ROOT = SELECTION_DIR.parent

# The drop zone. Put a photographer's folders, zips, or loose files here and run
# fetch.py with no source argument. Everything inside is treated as one delivery
# and is *moved* into the shoot, so an empty drop/ means nothing is waiting.
DROP_DIR = SELECTION_DIR / "drop"

# Raw formats worth culling. Anything the camera writes as a negative — rawpy
# (libraw) reads all of these, and `cull.py` pulls the embedded preview out
# rather than decoding them.
RAW_EXTS = {
    ".nef", ".nrw",                     # Nikon
    ".cr2", ".cr3", ".crw",             # Canon
    ".arw", ".srf", ".sr2",             # Sony
    ".raf",                             # Fujifilm
    ".orf",                             # Olympus / OM
    ".rw2",                             # Panasonic
    ".pef", ".dng",                     # Pentax / Adobe
    ".srw",                             # Samsung
    ".3fr", ".fff",                     # Hasselblad
    ".iiq",                             # Phase One
    ".erf", ".mos", ".mrw", ".x3f",
}
JPEG_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".heic", ".heif"}
PHOTO_EXTS = RAW_EXTS | JPEG_EXTS

ARCHIVE_EXTS = {".zip", ".7z", ".rar"}

# Junk that macOS, Windows, and Lightroom sprinkle through a delivery. Counting
# these as photos would corrupt every number in the report.
JUNK_NAMES = {".ds_store", "thumbs.db", "desktop.ini", "__macosx"}
JUNK_EXTS = {".xmp", ".lrcat", ".lrdata", ".dop", ".pp3", ".cos"}

# Drive's server-side split: "Casa Nirvana-001.zip", "-002.zip", ... Each opens
# standalone and holds a *subset* of the files, so they merge by extracting all
# of them into one folder.
DRIVE_PART_RE = re.compile(r"^(?P<stem>.+)-(?P<n>\d{3})$")

# A real split archive: the pieces are fragments of one stream and only the
# first is openable. 7z reassembles them; zipfile cannot.
SPLIT_SUFFIX_RE = re.compile(r"\.(?:zip|7z|rar)\.(\d{3})$", re.I)
SPLIT_LEGACY_RE = re.compile(r"\.(?:z|r)(\d{2})$", re.I)

# Trailing digits are the frame counter; everything before is the camera's
# prefix. "DSC_0142" -> ("DSC_", 142, 4)
SEQ_RE = re.compile(r"^(?P<prefix>.*?)(?P<num>\d{3,})$")

# What a browser, Finder, or Drive adds when a file lands twice: "DSC_0142 (1)",
# "DSC_0142 copy", "DSC_0142 copy 2". A name wearing one of these is the copy,
# never the camera's original — which matters because the two are byte-identical
# and only one survives dedup.
COPY_MARK_RE = re.compile(r"(?:\s\(\d+\)|\s-\s?\d+|\scop(?:y|ie|ia)(?:\s\d+)?)$", re.I)

# A run of missing frames this long reads as a truncated download rather than a
# photographer deleting rejects. Deleting a bad bracket loses 3-7 in a row;
# losing 15 in a row is a broken zip.
GAP_RUN_ALARM = 12


def rel(p: Path) -> str:
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def sevenzip() -> "str | None":
    """Homebrew ships the binary as `7zz` (sevenzip) or `7z` (p7zip)."""
    for name in ("7zz", "7z", "7za"):
        if found := shutil.which(name):
            return found
    return None


def is_junk(p: Path) -> bool:
    return (p.name.lower() in JUNK_NAMES
            or p.suffix.lower() in JUNK_EXTS
            or p.name.startswith("._")          # AppleDouble resource forks
            or any(part.lower() in JUNK_NAMES for part in p.parts))


def classify(p: Path) -> str:
    ext = p.suffix.lower()
    if ext in RAW_EXTS:
        return "raw"
    if ext in JPEG_EXTS:
        return "image"
    if ext in ARCHIVE_EXTS:
        return "archive"
    return "other"


# ---------------------------------------------------------------- acquisition

def looks_like_url(s: str) -> bool:
    return s.startswith(("http://", "https://"))


def looks_like_rclone_remote(s: str) -> bool:
    """`remote:path` — a colon that isn't a Windows drive or a URL scheme."""
    if looks_like_url(s) or os.path.exists(s):
        return False
    return bool(re.match(r"^[A-Za-z0-9_-]+:", s))


def run_tool(cmd: "list[str]", what: str, fatal: bool = True) -> int:
    """Run an external downloader, streaming its progress straight through.

    Not captured on purpose: these move tens of gigabytes and their progress
    output is the only sign the run is alive.
    """
    print(f"running     {Path(cmd[0]).name} ... ({what})")
    try:
        proc = subprocess.run(cmd)
    except FileNotFoundError:
        sys.exit(f"error: `{cmd[0]}` is not installed.\n"
                 f"       brew install {Path(cmd[0]).name}")
    if proc.returncode != 0 and fatal:
        sys.exit(f"error: {Path(cmd[0]).name} exited {proc.returncode} — "
                 "nothing was verified.\n"
                 "       If the link needs a sign-in, download it by hand and\n"
                 "       point this script at the .zip instead.")
    return proc.returncode


# Drive starts refusing after a few dozen consecutive file requests
# ("Cannot retrieve the public link ... or have had many accesses"). Observed on
# a real 307-file folder: gdown got 45 files and then stopped. Since gdown skips
# files already on disk, simply going round again picks up where it left off, and
# a growing pause between rounds is what gets past the throttle.
GDOWN_BACKOFF = [0, 20, 45, 90, 150, 240, 240, 240]


def count_files(folder: Path) -> int:
    return sum(1 for p in folder.rglob("*") if p.is_file())


def gdown_folder(url: str, staging: Path, gdown: str) -> str:
    """Pull a Drive folder, going round again for whatever the throttle blocked.

    Returns a note describing how many rounds it took. Never raises on a partial
    result — a short delivery is reported by the count check rather than hidden
    behind a crash, and the files already on disk are worth keeping either way.
    """
    got = count_files(staging)
    rounds = 0
    for attempt, pause in enumerate(GDOWN_BACKOFF, 1):
        if pause:
            print(f"throttled   waiting {pause}s before round {attempt} "
                  f"({got} file(s) so far)")
            time.sleep(pause)
        rounds = attempt
        code = run_tool([gdown, "--no-cookies", "--continue", "-O",
                         str(staging) + os.sep, "--folder", url],
                        f"gdown round {attempt}", fatal=False)
        now = count_files(staging)
        if code == 0:
            return f"gdown, {rounds} round(s), completed cleanly"
        if now == got:
            print(f"stalled     round {attempt} added nothing — giving up on the link")
            return (f"gdown, {rounds} round(s), **stalled at {now} file(s)** "
                    "— Drive kept refusing")
        got = now
    return f"gdown, {rounds} round(s), stopped with {got} file(s) — rounds exhausted"


def drop_contents() -> "list[Path]":
    """Whatever is waiting in `0 - selection/drop/`.

    An explicit drop folder rather than "loose in the stage folder", because
    then nothing has to be guessed: everything inside it is a delivery, and a
    shoot folder can never be mistaken for one.

    It also solves something a single `source` argument cannot. A delivery often
    arrives as two sibling folders — `1_Imóvel/`, `3_Condomínio/` — and needs
    *both*, with their own names kept, because those names are what identify the
    area and drive the gallery order.
    """
    if not DROP_DIR.is_dir():
        return []
    return [p for p in sorted(DROP_DIR.iterdir(), key=lambda p: p.name.lower())
            if not p.name.startswith(".")]


def adopt_drop(drops: "list[Path]", staging: Path) -> "tuple[list[Path], str]":
    """Move the drop into the shoot, keeping each item's own folder name.

    Moved, not copied: leaving the originals in `drop/` would make it look like
    there is still work waiting, and the next run would adopt them a second time
    into a second shoot.
    """
    staging.mkdir(parents=True, exist_ok=True)
    names = []
    for d in drops:
        dest = staging / d.name
        if dest.exists():
            sys.exit(f"error: {rel(dest)} already exists — resolve it by hand")
        shutil.move(str(d), str(dest))
        names.append(d.name)
        print(f"  adopted   {d.name}")
    return sorted(staging.iterdir()), ("from `0 - selection/drop/`: "
                                       + ", ".join(f"`{n}`" for n in names))


def acquire(source: str, staging: Path) -> "tuple[list[Path], str]":
    """Put the delivery into `staging`. Returns (top-level items, how).

    Local sources are **hard-linked** where the filesystem allows it, so
    pointing this at a 15 GB folder in ~/Downloads costs no extra disk. Links
    are safe because nothing downstream ever writes to `source/`.
    """
    staging.mkdir(parents=True, exist_ok=True)

    if looks_like_rclone_remote(source):
        run_tool(["rclone", "copy", "--progress", "--transfers", "8",
                  source, str(staging)], "rclone, file by file")
        return sorted(staging.iterdir()), f"rclone from `{source}`"

    if looks_like_url(source):
        return acquire_url(source, staging)

    src = Path(source).expanduser()
    if not src.exists():
        sys.exit(f"error: no such file or folder: {src}")

    if src.is_dir():
        n = link_tree(src, staging)
        return sorted(staging.iterdir()), f"local folder `{src}` ({n} file(s) linked)"

    # One archive named on the command line usually means its siblings were
    # meant too — Drive's "-001, -002, -003" split is the whole reason. Pulling
    # in the set is the difference between a third of the shoot and all of it.
    siblings = archive_siblings(src)
    for f in siblings:
        link_one(f, staging / f.name)
    if len(siblings) > 1:
        print(f"siblings    {len(siblings)} archive(s) in the set — taking all of them")
        for f in siblings:
            print(f"  {f.name}  {human(f.stat().st_size)}")
    return sorted(staging.iterdir()), f"local archive `{src.name}` (set of {len(siblings)})"


def venv_tool(name: str) -> "str | None":
    """Find a console script, checking this interpreter's own bin/ first.

    Running `./_config/.venv/bin/python` does **not** put the venv's `bin/` on
    PATH, so a plain `which` misses tools installed with pip into that venv —
    which is where gdown lives.
    """
    local = Path(sys.executable).parent / name
    if local.exists():
        return str(local)
    return shutil.which(name)


def acquire_url(url: str, staging: Path) -> "tuple[list[Path], str]":
    """Download a share link.

    Google Drive share links go through `gdown`, which fetches files one at a
    time through Drive's own endpoints. That sidesteps the server-side zip split
    entirely — nothing is ever zipped, so nothing is ever cut into pieces.

    It is not a guarantee, though: one request per file means a few hundred files
    is a few hundred requests, and Drive can start refusing partway through. The
    run would end looking successful with a partial folder on disk. That is why
    the count is checked afterwards and why `--expect` exists.
    """
    if "drive.google.com" in url or "docs.google.com" in url:
        gdown = venv_tool("gdown")
        if not gdown:
            sys.exit("error: gdown is not installed. Either:\n"
                     "         ./_config/.venv/bin/python -m pip install gdown\n"
                     "       or download the folder by hand and point this script\n"
                     "       at the .zip files it produces.")
        if "/folders/" in url:
            print("note        Drive throttles a long run of single-file requests, so this\n"
                  "            goes round more than once, skipping what already landed.\n"
                  "            It can still come back short — pass --expect N with the\n"
                  "            count the photographer gave you.")
            note = gdown_folder(url, staging, gdown)
            return sorted(staging.iterdir()), f"{note}, from `{url}`"

        run_tool([gdown, "--no-cookies", "--continue",
                  "-O", str(staging) + os.sep, url], "gdown, single file")
        return sorted(staging.iterdir()), f"gdown from `{url}`"

    dest = staging / (url.rstrip("/").split("/")[-1].split("?")[0] or "download")
    run_tool(["curl", "-fL", "--progress-bar", "-o", str(dest), url], "curl")
    return sorted(staging.iterdir()), f"curl from `{url}`"


def archive_siblings(archive: Path) -> "list[Path]":
    """Every archive belonging to the same delivery as `archive`.

    Covers Drive's `-001/-002` split and true multi-part archives. Falls back to
    just the one file when the name has no part number in it.
    """
    stem = archive.stem
    folder = archive.parent

    if m := DRIVE_PART_RE.match(stem):
        base = m.group("stem")
        found = sorted(p for p in folder.iterdir()
                       if p.is_file() and (mm := DRIVE_PART_RE.match(p.stem))
                       and mm.group("stem") == base
                       and p.suffix.lower() == archive.suffix.lower())
        if found:
            return found

    if SPLIT_SUFFIX_RE.search(archive.name):
        base = SPLIT_SUFFIX_RE.sub("", archive.name)
        return sorted(p for p in folder.iterdir()
                      if p.is_file() and p.name.startswith(base)
                      and SPLIT_SUFFIX_RE.search(p.name))

    if SPLIT_LEGACY_RE.search(archive.name):
        base = archive.name.rsplit(".", 1)[0]
        return sorted(p for p in folder.iterdir()
                      if p.is_file() and p.name.rsplit(".", 1)[0] == base)

    return [archive]


def link_one(src: Path, dest: Path) -> None:
    """Hard-link, or copy when that is not possible (different volume)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        return
    try:
        os.link(src, dest)
    except OSError:
        shutil.copy2(src, dest)


def link_tree(src: Path, dest: Path) -> int:
    n = 0
    for p in sorted(src.rglob("*")):
        if p.is_file() and not is_junk(p):
            link_one(p, dest / p.relative_to(src))
            n += 1
    return n


# ---------------------------------------------------------------- extraction

def extract_all(folder: Path, depth: int = 0) -> "tuple[list[str], int]":
    """Extract every archive in `folder`, in place, recursively.

    All of them land in the *same* destination, which is what merges Drive's
    `-001/-002/-003` pieces back into one delivery. Archives are removed once
    unpacked so a re-run doesn't unpack them again.

    Returns (notes, junk_skipped) — the junk count has to come back from here
    because junk is filtered *during* extraction and would otherwise never be
    counted anywhere, making the report claim a clean delivery it never saw.
    """
    if depth > 2:
        return [], 0

    notes: "list[str]" = []
    junk = 0
    # A split archive's parts are named `X.7z.001`, so their *suffix* is `.001`
    # and an extension test alone walks straight past them.
    archives = sorted(p for p in folder.rglob("*")
                      if p.is_file() and (p.suffix.lower() in ARCHIVE_EXTS
                                          or SPLIT_SUFFIX_RE.search(p.name)))
    # A true split archive is opened through its first part only; the rest are
    # fragments and would each fail on their own.
    archives = [a for a in archives if not SPLIT_LEGACY_RE.search(a.name)
                and not (SPLIT_SUFFIX_RE.search(a.name)
                         and not a.name.endswith((".001", ".01")))]
    if not archives:
        return notes, junk

    for arc in archives:
        dest = arc.parent
        note, skipped = extract_one(arc, dest)
        junk += skipped
        notes.append(note)
        print(f"  {note}")
        arc.unlink(missing_ok=True)
        for frag in archive_siblings(arc):
            if frag.exists() and SPLIT_SUFFIX_RE.search(frag.name):
                frag.unlink(missing_ok=True)

    deeper_notes, deeper_junk = extract_all(folder, depth + 1)
    return notes + deeper_notes, junk + deeper_junk


def extract_one(arc: Path, dest: Path) -> "tuple[str, int]":
    """Unpack one archive. zipfile first, 7z for what zipfile can't do.

    Returns (note, junk_entries_skipped).
    """
    if arc.suffix.lower() == ".zip" and not SPLIT_SUFFIX_RE.search(arc.name):
        try:
            with zipfile.ZipFile(arc) as zf:
                entries = [m for m in zf.namelist() if not m.endswith("/")]
                members = [m for m in entries if not is_junk(Path(m))]
                zf.extractall(dest, members=members)
            return (f"{arc.name} -> {len(members)} file(s) (zipfile)",
                    len(entries) - len(members))
        except (zipfile.BadZipFile, NotImplementedError, RuntimeError) as e:
            # Split, encrypted, or a compression method zipfile lacks — all of
            # which 7z handles. Worth trying before giving up on the delivery.
            print(f"  {arc.name}: zipfile said {type(e).__name__}, trying 7z")

    tool = sevenzip()
    if not tool:
        sys.exit(f"error: {arc.name} needs 7z to unpack "
                 f"({arc.suffix} / split archive), and it is not installed.\n"
                 "       brew install sevenzip")
    proc = subprocess.run([tool, "x", "-y", f"-o{dest}", str(arc)],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        sys.exit(f"error: 7z could not unpack {arc.name}:\n"
                 f"       {proc.stderr.strip()[:400]}")
    # 7z has no member filter, so its junk is caught by sweep_junk() afterwards
    # and counted there instead.
    return f"{arc.name} -> unpacked (7z)", 0


# ---------------------------------------------------------------- verification

def sweep_junk(folder: Path) -> int:
    """Delete the OS/editor cruft archives carry, then the folders it left."""
    n = 0
    for p in sorted(folder.rglob("*"), key=lambda p: -len(p.parts)):
        if p.is_file() and is_junk(p):
            p.unlink(missing_ok=True)
            n += 1
    for p in sorted(folder.rglob("*"), key=lambda p: -len(p.parts)):
        if p.is_dir() and not any(p.iterdir()):
            p.rmdir()
    return n


def canonical_rank(f: Path) -> "tuple[int, int, str]":
    """Sort key that puts the camera's own filename ahead of a copy of it.

    Which twin survives dedup is not cosmetic. `DSC_0142.NEF` carries a frame
    number the whole pipeline reads — bracket grouping, the sequence check,
    the trail back to the photographer's file. `DSC_0142 (1).NEF` carries none
    of that. Plain alphabetical order picks the copy, because a space sorts
    before a period.
    """
    return (1 if COPY_MARK_RE.search(f.stem) else 0, len(f.name), f.name)


def dedupe(files: "list[Path]") -> "tuple[list[Path], list[tuple[Path, Path]]]":
    """Remove byte-identical duplicates. Returns (kept, [(removed, kept_as)]).

    Overlapping Drive partitions and a re-run of an interrupted fetch both
    produce these. Only files that share an exact size are hashed — that is
    almost none of them, so this costs nearly nothing on a 500-file delivery.
    """
    by_size: "dict[int, list[Path]]" = defaultdict(list)
    for f in files:
        by_size[f.stat().st_size].append(f)

    kept, removed = [], []
    for size, group in by_size.items():
        if len(group) == 1:
            kept.append(group[0])
            continue
        seen: "dict[str, Path]" = {}
        for f in sorted(group, key=canonical_rank):
            digest = sha256(f)
            if digest in seen:
                removed.append((f, seen[digest]))
                f.unlink(missing_ok=True)
            else:
                seen[digest] = f
                kept.append(f)
    return sorted(kept), removed


def sha256(f: Path) -> str:
    h = hashlib.sha256()
    with f.open("rb") as fh:
        while chunk := fh.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def read_expect_list(path: Path) -> "list[str]":
    """Load a list of expected file paths. Blank lines and #comments ignored."""
    if not path.exists():
        sys.exit(f"error: no expect-list at {path}")
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")]


def same_name(name: str) -> str:
    """A filename in one canonical form, so accented names compare equal.

    macOS stores `Área` decomposed (NFD: `A` + U+0301) while Drive's API, most
    zips, and anything typed in a browser hand it over composed (NFC: U+00C1).
    The two are the same filename and the same file, and compare unequal.

    Measured on a real Portuguese delivery: 78 of 307 filenames carried an
    accent, so an inventory check without this reports a quarter of a complete
    delivery as missing — and the fix looks like a bug in the download.
    """
    return unicodedata.normalize("NFC", name).casefold()


def compare_to_list(expected: "list[str]", files: "list[Path]",
                    source_dir: Path) -> dict:
    """Check arrivals against a known inventory, by name.

    Strictly better than a count. A count says "262 missing" and leaves you to
    work out which; this names them, so a second fetch can target the gap and
    you can tell the photographer exactly what to re-send.

    Matching is on the **basename**, deliberately. Every route rearranges the
    tree differently — gdown wraps the delivery in one more folder, Drive's zip
    keeps the original layout, a photographer may flatten it — and a full-path
    comparison would report all 307 files missing over a naming difference that
    doesn't matter. Basenames within one shoot are effectively unique.
    """
    want = {same_name(Path(p).name): p for p in expected}
    have = {same_name(p.name) for p in files}

    missing, deduped = [], []
    for name, orig in sorted(want.items()):
        if name in have:
            continue
        # An inventory taken before dedup lists the copies too. "DSC_0142 (1).NEF"
        # being absent is not a loss when "DSC_0142.NEF" is here and the two were
        # byte-identical — dedup removed it on purpose. Counting it as missing
        # would halt a delivery that is actually complete.
        stem, suffix = Path(name).stem, Path(name).suffix
        twin = same_name(COPY_MARK_RE.sub("", stem) + suffix)
        if twin != name and twin in have:
            deduped.append(orig)
            continue
        missing.append(orig)

    extra = sorted(name for name in have if name not in want)
    return {"expected": len(want), "arrived": len(have & set(want)),
            "missing": missing, "extra": extra, "deduped": deduped,
            "complete": not missing}


def sequence_report(files: "list[Path]") -> "list[dict]":
    """Find each camera's frame-number run and the holes *inside* it.

    Cameras number frames consecutively, so a delivery should be a dense range
    and holes are worth reporting: a few scattered ones are the photographer
    deleting rejects; a long run is a zip that came back short.

    **What this cannot see: a missing tail.** If the download stopped early, the
    frames past the cut are simply absent, so the range itself ends early and
    every frame inside it is present. The check reports a clean sweep on a
    delivery that lost a third of the shoot — which is precisely the failure it
    was written to catch. Nothing in the files can reveal it, because the
    evidence is what's absent.

    So this never returns "ok". It returns the range it saw and leaves the tail
    question open; `--expect N` is what actually closes it.
    """
    groups: "dict[str, dict[int, Path]]" = defaultdict(dict)
    for f in files:
        if m := SEQ_RE.match(f.stem):
            groups[m.group("prefix") or f.suffix.lower()][int(m.group("num"))] = f

    out = []
    for prefix, frames in sorted(groups.items()):
        if len(frames) < 5:            # too short to say anything about
            continue
        lo, hi = min(frames), max(frames)
        missing = [n for n in range(lo, hi + 1) if n not in frames]

        runs: "list[list[int]]" = []
        for n in missing:
            if runs and n == runs[-1][-1] + 1:
                runs[-1].append(n)
            else:
                runs.append([n])

        longest = max((len(r) for r in runs), default=0)
        out.append({
            "prefix": prefix, "lo": lo, "hi": hi,
            "present": len(frames), "in_range": hi - lo + 1,
            "missing": missing, "runs": runs, "longest": longest,
            "alarm": longest >= GAP_RUN_ALARM,
        })
    return out


def part_report(archives: "list[tuple[str, int]]") -> "dict | None":
    """Sanity-check a Drive `-001/-002/-003` set for a missing piece.

    Two things are checkable without knowing the expected total:

    - **A hole in the numbering.** `-001` and `-003` with no `-002` is a piece
      that never downloaded, and unlike a missing tail this one is visible.
    - **The last piece being full size.** Drive cuts by bytes, so the final
      piece is the remainder and is normally *smaller* than the rest. When the
      highest-numbered piece is the same size as its siblings, there is very
      likely another piece after it that was never fetched.
    """
    numbered = []
    for name, size in archives:
        if m := DRIVE_PART_RE.match(Path(name).stem):
            numbered.append((int(m.group("n")), name, size))
    if len(numbered) < 2:
        return None
    numbered.sort()

    nums = [n for n, _, _ in numbered]
    holes = [n for n in range(min(nums), max(nums) + 1) if n not in nums]

    sizes = [s for _, _, s in numbered]
    last, others = sizes[-1], sizes[:-1]
    # Within 5% of the average of the others reads as "not the remainder".
    last_is_full = bool(others) and last >= 0.95 * (sum(others) / len(others))

    return {"count": len(numbered), "highest": max(nums), "holes": holes,
            "last_is_full": last_is_full, "names": [n for _, n, _ in numbered],
            "alarm": bool(holes) or last_is_full}


# ---------------------------------------------------------------- report

def write_report(job: Path, source: str, how: str, notes: "list[str]",
                 files: "list[Path]", removed: "list[tuple[Path, Path]]",
                 junk: int, seqs: "list[dict]", parts: "dict | None",
                 expect: "int | None", inventory: "dict | None" = None) -> None:
    by_ext: "dict[str, list[Path]]" = defaultdict(list)
    for f in files:
        by_ext[f.suffix.lower()].append(f)

    photos = [f for f in files if classify(f) in ("raw", "image")]
    others = [f for f in files if classify(f) == "other"]
    total = sum(f.stat().st_size for f in files)

    L = [
        f"# {job.name} — Fetch report", "",
        "| | |", "|---|---|",
        f"| Fetched | {datetime.now(timezone.utc).isoformat(timespec='seconds')} |",
        f"| Asked for | `{source}` |",
        f"| Arrived via | {how} |",
        f"| Photos | **{len(photos)}** ({sum(1 for f in photos if classify(f) == 'raw')} raw, "
        f"{sum(1 for f in photos if classify(f) == 'image')} jpeg/tiff) |",
        f"| On disk | {human(total)} |",
        "",
    ]

    if notes:
        L += ["## Archives unpacked", ""]
        L += [f"- {n}" for n in notes]
        L += ["", "Every archive was extracted into the **same** folder, which is what "
              "merges Drive's `-001`/`-002` pieces back into one delivery.", ""]

    L += ["## By extension", "", "| Ext | Count | Size |", "|---|---|---|"]
    for ext, group in sorted(by_ext.items(), key=lambda kv: -len(kv[1])):
        kind = classify(Path("x" + ext))
        tag = "" if kind in ("raw", "image") else "  ← not a photo"
        L.append(f"| `{ext or '(none)'}` | {len(group)} | "
                 f"{human(sum(f.stat().st_size for f in group))} |{tag}")
    L.append("")

    L += ["## Did everything arrive?", ""]

    # A named inventory beats a count, so it goes first when we have one.
    if inventory:
        if inventory["complete"]:
            L += [f"**Confirmed, by name.** All {inventory['expected']} file(s) on the "
                  "inventory arrived.", ""]
        else:
            L += [f"**❌ {len(inventory['missing'])} of {inventory['expected']} file(s) "
                  "MISSING.** These were on the inventory and did not arrive:", ""]
            for m in inventory["missing"][:60]:
                L.append(f"- `{m}`")
            if len(inventory["missing"]) > 60:
                L.append(f"- … {len(inventory['missing']) - 60} more")
            L += ["", "Fetch again with `--force`; anything already here is skipped.", ""]
        if inventory.get("deduped"):
            L += [f"{len(inventory['deduped'])} name(s) on the inventory are absent "
                  "because dedup removed them — each was a byte-identical copy of a file "
                  "that *is* here, so nothing was lost:", ""]
            L += [f"- `{d}`" for d in inventory["deduped"][:20]]
            L.append("")
        if inventory["extra"]:
            L += [f"Also {len(inventory['extra'])} file(s) arrived that are *not* on the "
                  "inventory — the list may be out of date, or the photographer added to "
                  "the folder:", ""]
            L += [f"- `{x}`" for x in inventory["extra"][:20]]
            L.append("")

    # Without an inventory, a count is the strongest thing left. Everything
    # below it is circumstantial.
    elif expect is None:
        L += [f"**Unverified.** {len(photos)} photos arrived. Nothing here knows how "
              "many were sent, so that number is unconfirmed. Ask the photographer "
              "for the count and re-run with `--expect N` to turn this into a real "
              "check:", "",
              "```bash",
              f'./_config/.venv/bin/python "0 - selection/fetch.py" \\',
              f'    "{source}" --force --expect 450',
              "```", ""]
    elif len(photos) == expect:
        L += [f"**Confirmed.** {len(photos)} photos arrived and {expect} were "
              "expected. The delivery is complete.", ""]
    else:
        short = expect - len(photos)
        L += [f"**❌ {abs(short)} photo(s) {'MISSING' if short > 0 else 'more than expected'}.** "
              f"{len(photos)} arrived, {expect} expected. "
              + ("Re-fetch before going further — a partial delivery costs more to "
                 "discover after the culling."
                 if short > 0 else
                 "Possibly a duplicate the dedup could not see, or a miscount."), ""]

    L += ["### Frame numbering", ""]
    # Frame numbering is a *proxy* for "did everything arrive". With a confirmed
    # inventory we have the real answer, and the proxy's holes are then just
    # frames the photographer chose not to send — a normal, healthy thing that
    # must not be dressed up as a problem.
    if inventory and inventory["complete"]:
        L.append("_The inventory already confirmed the delivery, so the holes below are "
                 "simply frames the photographer didn't send. Listed for interest only._")
        L.append("")
    if not seqs:
        L.append("- These filenames carry no frame numbers, so this check has nothing "
                 "to work with.")
    for s in seqs:
        L.append(f"- `{s['prefix']}` runs `{s['lo']:04d}`–`{s['hi']:04d}` · "
                 f"{s['present']} present · {len(s['missing'])} hole(s) inside that range")
        if s["missing"]:
            shown = ", ".join(
                f"{r[0]:04d}" if len(r) == 1 else f"**{r[0]:04d}–{r[-1]:04d}** ({len(r)})"
                for r in s["runs"][:12])
            L.append(f"  - {shown}"
                     + (f", … {len(s['runs']) - 12} more runs" if len(s["runs"]) > 12 else ""))
        if s["alarm"]:
            L.append(f"  - ⚠️ A run of {s['longest']} consecutive frames is gone. Could "
                     "be a deleted bad bracket, could be a short zip. Worth asking.")
    if seqs:
        L += ["", "> This only finds holes **between** the first and last frame. If the "
              "download stopped early, the frames past the cut are simply absent and the "
              "range ends there looking perfectly intact — so a clean result above is "
              "**not** evidence the tail arrived. Only `--expect` settles that.", ""]

    if parts:
        L += ["### Drive partition set", ""]
        L.append(f"- {parts['count']} piece(s), highest numbered `-{parts['highest']:03d}`")
        if parts["holes"]:
            L.append(f"  - ⚠️ **Missing piece(s): "
                     f"{', '.join(f'-{h:03d}' for h in parts['holes'])}.** "
                     "Download them and re-run with `--force`.")
        if parts["last_is_full"]:
            L.append(f"  - ⚠️ **`-{parts['highest']:03d}` is the same size as the others.** "
                     "Drive cuts by byte size, so the last piece is the remainder and is "
                     "normally smaller. A full-size last piece usually means there is "
                     f"a `-{parts['highest'] + 1:03d}` you don't have yet.")
        if not parts["alarm"]:
            L.append("  - The last piece is smaller than its siblings, which is what "
                     "the real final piece looks like.")
        L.append("")

    L += ["### Housekeeping", ""]
    L.append(f"- Duplicates removed: **{len(removed)}**"
             + (" — byte-identical under different names, which is what overlapping "
                "Drive partitions and browser re-downloads produce" if removed else ""))
    for dup, orig in removed[:10]:
        L.append(f"  - `{dup.name}` = `{orig.name}`")
    if len(removed) > 10:
        L.append(f"  - … {len(removed) - 10} more")
    L.append(f"- OS/editor junk dropped: {junk}"
             + ("  — `.DS_Store`, AppleDouble `._` forks, Lightroom `.xmp` sidecars"
                if junk else ""))

    if others:
        L += ["", "## Not photos — left in place, not counted", ""]
        for f in others[:20]:
            hint = ""
            if f.suffix.lower() == ".pdf" or "plan" in f.name.lower() or "plant" in f.name.lower():
                hint = "  ← could be the floor plan. `manifest.md` wants it."
            L.append(f"- `{f.relative_to(job)}`{hint}")
        if len(others) > 20:
            L.append(f"- … {len(others) - 20} more")

    L += ["", "---", ""]
    short = ((inventory is not None and not inventory["complete"])
             or (inventory is None and expect is not None and len(photos) < expect))
    if short:
        L += ["**Do not go on to `cull.py` yet.** Culling an incomplete delivery "
              "means the frame you needed may simply not be here, and you would never "
              "know — the shortlist would look perfectly reasonable. Get the missing "
              "files, re-run with `--force`, then continue.", ""]
    else:
        L += ["Nothing here has been judged, renamed, or resized. Next:", "",
              "```bash",
              f'./_config/.venv/bin/python "0 - selection/cull.py" "{rel(job)}"',
              "```", ""]

    (job / "fetch.md").write_text("\n".join(L), encoding="utf-8")


# ---------------------------------------------------------------- main

def default_name(source: str) -> str:
    """A folder name a person would recognize the shoot by."""
    if looks_like_rclone_remote(source):
        raw = source.split(":", 1)[1].rstrip("/").split("/")[-1] or source.split(":")[0]
    elif looks_like_url(source):
        raw = "Download"
    else:
        p = Path(source).expanduser()
        if p.is_dir():
            raw = p.name
        else:
            # Strip the part suffix off the *full name* first — `Quinta.7z.001`
            # has stem `Quinta.7z`, so stemming before stripping keeps the `.7z`.
            name = SPLIT_LEGACY_RE.sub("", SPLIT_SUFFIX_RE.sub("", p.name))
            raw = Path(name).stem
        if m := DRIVE_PART_RE.match(raw):     # "Casa Nirvana-001" -> "Casa Nirvana"
            raw = m.group("stem")
    return re.sub(r"[/\\:]", "-", raw).strip() or "Delivery"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", nargs="?",
                    help="a folder, a .zip, an rclone remote:path, or a URL. Omit it to "
                         "take whatever is waiting in 0 - selection/drop/ (then --name "
                         "is required).")
    ap.add_argument("--name", help="folder name for this shoot "
                                   "(default: derived from the source)")
    ap.add_argument("--force", action="store_true",
                    help="add to an existing shoot folder instead of stopping")
    ap.add_argument("--expect", type=int, metavar="N",
                    help="how many photos the photographer said they sent. The only "
                         "check that can prove nothing was lost off the end of the "
                         "download — everything else is circumstantial.")
    ap.add_argument("--expect-list", type=Path, metavar="FILE",
                    help="a file listing the expected filenames, one per line. Better "
                         "than --expect: names which files are missing, not just how "
                         "many. For a Drive folder, generate one with "
                         "`gdown --folder --json <link>`.")
    args = ap.parse_args()

    drops = [] if args.source else drop_contents()
    if not args.source and not drops:
        sys.exit("nothing to do.\n"
                 f"       Put the photographer's folders or zips in {rel(DROP_DIR)}/ "
                 "and run this again,\n"
                 "       or pass a path / link as the first argument.")
    if not args.source and not args.name:
        sys.exit("error: --name is required when taking a drop, since there is no\n"
                 "       filename to derive the shoot name from. For example:\n"
                 '         ...fetch.py --name "Cobertura"')

    name = args.name or default_name(args.source)
    job = SELECTION_DIR / name
    source_dir = job / "source"

    if source_dir.exists() and any(source_dir.iterdir()) and not args.force:
        sys.exit(f"error: {rel(source_dir)} already has files in it.\n"
                 "       Use --name for a different shoot, or --force to add to this one.")

    print(f"shoot       {name}")
    print(f"into        {rel(source_dir)}")

    if drops:
        items, how = adopt_drop(drops, source_dir)
    else:
        items, how = acquire(args.source, source_dir)
    if not items:
        sys.exit(f"error: nothing arrived in {rel(source_dir)}")

    # Names and sizes have to be read before extraction removes the archives —
    # the relative size of the last piece is evidence about a missing one.
    archives = [(p.name, p.stat().st_size) for p in sorted(source_dir.rglob("*"))
                if p.is_file() and (p.suffix.lower() in ARCHIVE_EXTS
                                    or SPLIT_SUFFIX_RE.search(p.name))]
    parts = part_report(archives)

    notes, junk = extract_all(source_dir)
    junk += sweep_junk(source_dir)

    files = sorted(p for p in source_dir.rglob("*") if p.is_file())
    if not files:
        sys.exit(f"error: {rel(source_dir)} is empty after unpacking")

    files, removed = dedupe(files)
    photos = [f for f in files if classify(f) in ("raw", "image")]
    seqs = sequence_report(photos)

    # An `expected.txt` sitting in the shoot folder is used without being asked
    # for. It belongs to the shoot, it survives re-runs, and it means the
    # strongest check available is the default rather than something you have to
    # remember a flag for.
    expect_list = args.expect_list or (
        job / "expected.txt" if (job / "expected.txt").exists() else None)
    inventory = None
    if expect_list:
        print(f"inventory   {rel(expect_list)}")
        inventory = compare_to_list(read_expect_list(expect_list),
                                    photos, source_dir)

    write_report(job, args.source, how, notes, files, removed, junk, seqs,
                 parts, args.expect, inventory)

    raw_n = sum(1 for f in photos if classify(f) == "raw")
    print(f"unpacked    {len(notes)} archive(s)" if notes else "unpacked    no archives")
    print(f"photos      {len(photos)}  ({raw_n} raw, {len(photos) - raw_n} jpeg/tiff)  "
          f"{human(sum(f.stat().st_size for f in photos))}")
    if removed:
        print(f"duplicates  {len(removed)} removed")
    if junk:
        print(f"junk        {junk} swept")

    verified = (inventory["complete"] if inventory
                else args.expect is not None and len(photos) == args.expect)

    # Frame holes only ever mattered as evidence about completeness. Once the
    # inventory has settled that, they are just frames the photographer chose
    # not to send — and shouting about those teaches you to ignore the shouting.
    for s in seqs:
        print(f"frames      {'!!' if s['alarm'] and not verified else '  '}  "
              f"{s['prefix']}{s['lo']:04d}–{s['hi']:04d} · {s['present']} present"
              f" · {len(s['missing'])} hole(s) inside the range"
              + ("  (not sent, delivery already confirmed)" if verified and s["alarm"] else ""))
    if not seqs:
        print("frames      --  filenames carry no frame numbers")
    # A size-based guess about a missing piece is worth nothing once the count
    # is proven, and printing it anyway trains you to ignore warnings.
    if parts and parts["alarm"] and not verified:
        print(f"parts       !!  {parts['count']} piece(s)"
              + (f", missing {', '.join(f'-{h:03d}' for h in parts['holes'])}"
                 if parts["holes"] else
                 f", -{parts['highest']:03d} is full size — expect a -{parts['highest'] + 1:03d}"))

    print(f"report      {rel(job / 'fetch.md')}")

    # The count is the whole question, so it gets the last word rather than
    # being one bullet among many.
    if inventory:
        if inventory["complete"]:
            print(f"\nOK all {inventory['expected']} file(s) on the inventory arrived, "
                  "checked by name.")
        else:
            miss = inventory["missing"]
            print(f"\n!! {len(miss)} of {inventory['expected']} file(s) MISSING by name:")
            for m in miss[:12]:
                print(f"     {m}")
            if len(miss) > 12:
                print(f"     ... {len(miss) - 12} more — full list in fetch.md")
            print("   Fetch again with --force; what is already here is skipped.")
            return
        if inventory["extra"]:
            print(f"   ({len(inventory['extra'])} file(s) arrived that aren't on the "
                  "inventory — see fetch.md)")
    elif args.expect is None:
        print(f"\n?? {len(photos)} photos arrived — UNVERIFIED. Nothing here knows how many\n"
              "   were sent. Holes inside the frame range are checked, but a download\n"
              "   that stopped early leaves no trace: the range just ends early and\n"
              "   looks intact. Ask the photographer for the count, then:\n"
              f'     ...fetch.py "{args.source}" --force --expect N')
    elif len(photos) != args.expect:
        print(f"\n!! {args.expect - len(photos)} photo(s) MISSING — {len(photos)} arrived, "
              f"{args.expect} expected.\n"
              "   Re-fetch before going on; finding this after the culling costs more.")
        return
    else:
        print(f"\nOK {len(photos)} photos, {args.expect} expected — delivery complete.")

    if not verified and (any(s["alarm"] for s in seqs)
                         or (parts and parts["alarm"])):
        print("   Also read the warnings in fetch.md before going on.")
    print(f"\nNext: ./_config/.venv/bin/python \"0 - selection/cull.py\" \"{rel(job)}\"")


if __name__ == "__main__":
    main()
