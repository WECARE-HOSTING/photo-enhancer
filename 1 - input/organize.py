#!/usr/bin/env python3
"""Gather whatever was dropped in `1 - input/` into one numbered job, then hand
it to `2 - in progress/`.

    ./_config/.venv/bin/python "1 - input/organize.py"

Drop loose photos, a folder of photos, or both. Everything found — at any depth —
becomes ONE job: `Job_NNNN/` holding the photos plus `job.md`.

**Nothing is renamed here.** The name a photo arrives with is the name it keeps,
because it was settled upstream: `0 - selection/` reads the room out of the
photographer's own filename, checks it against the pictures, and writes
`SALA_01_0002.jpg`. Renaming that to `Photo_0007.jpg` — which is what this script
used to do — threw away the one part of the name a person can read.

A drop that never went through `0 - selection/` keeps whatever the photographer
called it. That still works end to end, and the run says which files are not
named after a room so you can decide whether it matters.

Two copies exist afterwards, on purpose:

    _originais/Job_NNNN/    the drop exactly as it arrived, structure and all
    Job_NNNN/               the job, flat, in the names it will be worked under

The originals never leave this stage. They are what a re-run has to start from
when a job goes wrong, and the same reason `0 - selection/` never deletes
`source/`. The `_originais/` name starts with an underscore so the next run's scan
steps over it — without that, every drop would be re-organized into a second job
forever.

Job numbers count up across all three stage folders so they never collide. Read
`1 - input/CONTEXT.md`.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

INPUT_DIR = Path(__file__).resolve().parent
ROOT = INPUT_DIR.parent
IN_PROGRESS_DIR = ROOT / "2 - in progress"
COMPLETED_DIR = ROOT / "3 - completed"
ORIGINALS_DIR = INPUT_DIR / "_originais"

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}

# This stage's own files. They live in the same folder the photos land in, so
# the scan has to step over them.
OWN_FILES = {"organize.py", "CONTEXT.md"}

JOB_RE = re.compile(r"^Job_(\d+)$")

# The canonical name `0 - selection/` writes: `SALA_01_0002`, `AREA_SERVICO_01_0003`.
# The owner of this shape is `0 - selection/ambientes.py` — this is a copy, because
# a folder name with spaces in it cannot be imported across. `_dependencies.md`
# lists every copy; grep for `NAME_RE` before changing the shape of a name.
NAME_RE = re.compile(r"^[A-Z][A-Z_]*_\d{2}_\d{4}$")


def next_job_id() -> int:
    """One counter across every stage, so a job number is never reused while an
    older job is still in flight, sitting in the archive, or keeping originals."""
    used = [
        int(m.group(1))
        for d in (INPUT_DIR, ORIGINALS_DIR, IN_PROGRESS_DIR, COMPLETED_DIR)
        if d.is_dir()
        for p in d.iterdir() if p.is_dir() and (m := JOB_RE.match(p.name))
    ]
    return max(used, default=0) + 1


def scan() -> "tuple[list[Path], list[Path], list[Path]]":
    """Walk the drop zone once. Returns (photos, other_files, existing_jobs).

    Already-numbered job folders are left intact rather than absorbed — that
    is what makes an interrupted run safe to re-run: the second pass just
    finishes moving them instead of building a job inside a job.

    `_originais/` is skipped by name and not by its underscore. Skipping every
    `_`-prefixed folder would be tidier to write and would silently swallow a drop
    that happened to be named one — and a drop this script ignores is a delivery
    nobody notices is missing.
    """
    photos, others, jobs = [], [], []
    for p in sorted(INPUT_DIR.iterdir(), key=lambda p: p.name.lower()):
        if p.name.startswith(".") or p.name in OWN_FILES:
            continue
        if p == ORIGINALS_DIR:
            continue
        if p.is_dir():
            if JOB_RE.match(p.name):
                jobs.append(p)
                continue
            for child in sorted(p.rglob("*"), key=lambda c: str(c).lower()):
                if child.is_file() and not child.name.startswith("."):
                    (photos if child.suffix.lower() in IMAGE_EXTS
                     else others).append(child)
        elif p.is_file():
            (photos if p.suffix.lower() in IMAGE_EXTS else others).append(p)
    return photos, others, jobs


def target_name(src: Path) -> str:
    """The name the photo keeps. Only the extension is touched.

    Lowercased because `.JPG` and `.jpg` are the same thing to everyone except a
    string comparison, and `batch.py` does string comparisons.
    """
    return src.stem + src.suffix.lower()


def find_collisions(photos: "list[Path]") -> "dict[str, list[Path]]":
    """Names that two dropped files share. Fatal, and deliberately so.

    Two subfolders can each hold a `SALA_01_0001.jpg`, and a flat job folder has
    room for only one of them. Renaming one out of the way would break the promise
    that a name survives the whole pipeline, so the run stops and says which files
    to sort out instead of quietly picking a winner.
    """
    seen: "dict[str, list[Path]]" = {}
    for p in photos:
        seen.setdefault(target_name(p).lower(), []).append(p)
    return {k: v for k, v in seen.items() if len(v) > 1}


def source_label(pairs: "list[tuple[Path, str]]") -> str:
    """A short human name for this drop, for the archive index.

    The folder the photos were dropped in is what a person remembers a job by
    ("the Casa Nirvana shoot"), so prefer that; fall back to the first
    filename when the drop was loose files.
    """
    tops, loose = [], []
    for src, _ in pairs:
        parts = src.relative_to(INPUT_DIR).parts
        (tops if len(parts) > 1 else loose).append(parts[0])
    names = list(dict.fromkeys(tops))
    if names:
        label = names[0] if len(names) == 1 else f"{names[0]} +{len(names) - 1} more"
        return f"{label} + loose files" if loose else label
    return loose[0] if len(loose) == 1 else f"{loose[0]} +{len(loose) - 1} more"


def write_job_md(job_dir: Path, pairs: "list[tuple[Path, str]]") -> None:
    """The job's own record: which file each photo was, and where it sat.

    Less load-bearing than it used to be, now that the name itself survives — but
    still the only place the photographer's original filename is written down, and
    the only place the gallery order survives. Names now sort by ambiente, so
    `AREA_SERVICO` lands above `SALA` on disk whatever order they were shot in;
    the `#` column below is the order they were picked in.
    """
    lines = [
        f"# {job_dir.name}", "",
        f"**Dropped as:** `{source_label(pairs)}`", "",
        f"{len(pairs)} photo(s), gathered by `1 - input/organize.py`. Names were "
        "kept as they arrived — nothing here renames a photo.", "",
        "`#` is the order the photos were dropped in, which for a job out of "
        "`0 - selection/` is the gallery order. The originals are in "
        f"`1 - input/_originais/{job_dir.name}/`.", "",
        "| # | Photo | Came from | Size |", "|---|---|---|---|",
    ]
    for i, (src, new_name) in enumerate(pairs, 1):
        try:
            origin = src.relative_to(INPUT_DIR)
        except ValueError:
            origin = src.name
        size = (job_dir / new_name).stat().st_size / 1e6
        lines.append(f"| {i} | `{new_name}` | `{origin}` | {size:.1f} MB |")
    lines += ["", "Enhanced results and per-photo logs are written into this "
              "same folder by `2 - in progress/batch.py`, as "
              "`<name>_edit.jpg` and `<name>_log.md`.", ""]
    (job_dir / "job.md").write_text("\n".join(lines), encoding="utf-8")


def preserve_originals(job_name: str, entries: "list[str]") -> Path:
    """Move the drop, structure intact, into `_originais/Job_NNNN/`.

    A move rather than a copy: the drop zone has to end up empty or the next run
    would find the same photos and build a second job out of them. The photos are
    not lost — they are one folder away, under the number of the job they became.
    """
    dest = ORIGINALS_DIR / job_name
    if dest.exists():
        sys.exit(f"error: {dest.relative_to(ROOT)} already exists — resolve it "
                 "by hand before organizing another job")
    dest.mkdir(parents=True)
    for name in entries:
        shutil.move(str(INPUT_DIR / name), str(dest / name))
    return dest


def hand_off(job_dir: Path) -> Path:
    dest = IN_PROGRESS_DIR / job_dir.name
    if dest.exists():
        sys.exit(f"error: {dest.relative_to(ROOT)} already exists — "
                 "resolve that job before organizing another")
    IN_PROGRESS_DIR.mkdir(exist_ok=True)
    shutil.move(str(job_dir), str(dest))
    print(f"handed off  {job_dir.name} -> 2 - in progress/{job_dir.name}")
    return dest


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.parse_args()

    photos, others, existing = scan()

    # An interrupted run leaves an assembled job behind. Finish it, don't
    # rebuild it.
    for job in existing:
        hand_off(job)

    if not photos:
        if others:
            print(f"skipped     {len(others)} non-image file(s): "
                  f"{', '.join(o.name for o in others[:5])}")
        if not existing:
            print("1 - input/ has no photos — drop files or a folder in and "
                  "run this again")
        return

    clashes = find_collisions(photos)
    if clashes:
        print(f"error: {len(clashes)} name(s) are used by more than one dropped "
              "file, and a job\n       folder is flat, so they cannot all keep "
              "their name:\n")
        for name, srcs in list(clashes.items())[:8]:
            print(f"  {name}")
            for s in srcs:
                print(f"    <- {s.relative_to(INPUT_DIR)}")
        print("\n       Rename or separate them and run this again. Nothing has "
              "been moved.")
        sys.exit(1)

    job_id = next_job_id()
    job_name = f"Job_{job_id:04d}"
    print(f"job         {job_name} · {len(photos)} photo(s)")

    # The originals move first, so the drop zone is clear even if the copy below
    # dies half way — a second run then finds nothing to organize and says so,
    # rather than building a duplicate job out of the same photos.
    tops = list(dict.fromkeys(p.relative_to(INPUT_DIR).parts[0]
                              for p in photos + others))
    originals = preserve_originals(job_name, tops)
    print(f"originals   {len(tops)} item(s) -> "
          f"{originals.relative_to(INPUT_DIR)}/")

    job_dir = INPUT_DIR / job_name
    job_dir.mkdir()
    pairs, odd = [], []
    for src in photos:
        moved = originals / src.relative_to(INPUT_DIR)
        new_name = target_name(src)
        shutil.copy2(moved, job_dir / new_name)
        if not NAME_RE.match(Path(new_name).stem):
            odd.append(new_name)
        pairs.append((src, new_name))
    print(f"gathered    {len(pairs)} photo(s), names kept")

    if odd:
        print(f"note        {len(odd)} photo(s) are not named after a room: "
              f"{', '.join(odd[:4])}"
              f"{' ...' if len(odd) > 4 else ''}\n"
              "            They run fine. To have the room in the name, put the "
              "drop through\n            0 - selection/ instead — see its "
              "CONTEXT.md.")
    if others:
        print(f"skipped     {len(others)} non-image file(s): "
              f"{', '.join(o.name for o in others[:5])}"
              f"{' ...' if len(others) > 5 else ''} — kept with the originals")

    write_job_md(job_dir, pairs)
    dest = hand_off(job_dir)
    print(f"\nNext: ./_config/.venv/bin/python \"2 - in progress/batch.py\""
          f"   # run {dest.name}")


if __name__ == "__main__":
    main()
