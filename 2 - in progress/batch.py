#!/usr/bin/env python3
"""Run the job sitting in `2 - in progress/` through fal.ai, then wait for you.

    ./_config/.venv/bin/python "2 - in progress/batch.py"
    ./_config/.venv/bin/python "2 - in progress/batch.py" --job Job_0023 --workers 6
    ./_config/.venv/bin/python "2 - in progress/batch.py" --rework    # redo the rejected
    ./_config/.venv/bin/python "2 - in progress/batch.py" --approve   # -> 3 - completed/

One job at a time. The job folder arrives from `1 - input/organize.py` with its
photos already named — `SALA_01_0001.jpg` — and every result is written back into
that same folder under the same name plus `_edit`, so the job stays one bundle:
source, edit, and log side by side. Nothing is renamed at this stage.

Photos run **concurrently**, `--workers` at a time; each one is an independent
upload -> generate -> download chain and spends almost all of its time waiting
on fal, so wall clock is set by how many run at once, not by their sum. Each
photo's output is buffered and printed as one block, so parallel runs stay
readable.

A photo that already has an `_edit.jpg` is skipped, which makes a re-run after a
partial failure a retry of just the failures. `--redo` overrides that and
overwrites the edits it finds.

**The job does not archive itself.** It used to, the moment no photo had failed —
but "the API answered" and "this is good enough to send a client" are different
questions and only the first one a script can answer. So a finished run writes
`review.html`, a before-and-after of the whole job, and stops:

    batch.py            run it -> review.html
    (look at it)        tick what is not good enough, Copy rejected -> rework.txt
    batch.py --rework   deletes those edits and redoes only them -> review.html
    batch.py --approve  every photo has an edit and you said yes -> 3 - completed/

`--rework` needs no special machinery: deleting an `_edit.jpg` is exactly what
makes the ordinary skip logic above run that photo again. Archiving adds the job
to `3 - completed/index.md`, so a finished job can be found by the name it was
dropped under rather than by opening folders.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import enhance  # noqa: E402
import review  # noqa: E402

IN_PROGRESS_DIR = Path(__file__).resolve().parent
ROOT = enhance.ROOT
COMPLETED_DIR = ROOT / "3 - completed"

INDEX_PATH = COMPLETED_DIR / "index.md"

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
JOB_RE = re.compile(r"^Job_(\d+)$")
DROPPED_RE = re.compile(r"^\*\*Dropped as:\*\* (.+)$", re.M)

# What marks a file as a result rather than a source. `_edit` is the current
# suffix; `_enhanced` is what the first twenty-two jobs in `3 - completed/` were
# written with, and it stays here for good. Drop it and `--reindex` reads those
# results as sources and doubles every photo count in the archive index.
RESULT_MARKERS = ("_edit", "_enhanced")

INDEX_HEADER = """# Completed jobs

_One row per archived job. Written by `2 - in progress/batch.py` when you approve
one; rebuild it from the folders themselves with_
`./_config/.venv/bin/python "2 - in progress/batch.py" --reindex`.

| Job | Photos | Dropped as | Finished |
|---|---|---|---|
"""

# How many photos are in flight at once. Each one spends most of its time
# waiting on fal.ai, so threads (not processes) are the right tool. 4 is a
# comfortable default; raise it if fal keeps up, lower it to spread cost.
WORKERS = 4


def find_job(name: "str | None") -> Path:
    """Pick the job to run: the one named, or the lowest-numbered waiting."""
    jobs = sorted((p for p in IN_PROGRESS_DIR.iterdir()
                   if p.is_dir() and JOB_RE.match(p.name)),
                  key=lambda p: p.name)
    if name:
        for job in jobs:
            if job.name == name:
                return job
        sys.exit(f"error: no {name} in 2 - in progress/"
                 + (f" — waiting: {', '.join(j.name for j in jobs)}" if jobs else ""))
    if not jobs:
        sys.exit("2 - in progress/ has no job — run:\n"
                 '  ./_config/.venv/bin/python "1 - input/organize.py"')
    if len(jobs) > 1:
        print(f"{len(jobs)} jobs waiting ({', '.join(j.name for j in jobs)}) — "
              f"running {jobs[0].name}. Use --job to pick another.")
    return jobs[0]


def photos_in(job: Path) -> "list[Path]":
    """Source photos only — an `_edit.jpg` is a result, not an input."""
    return sorted(p for p in job.iterdir()
                  if p.suffix.lower() in IMAGE_EXTS
                  and not any(m in p.stem for m in RESULT_MARKERS))


def strip_result(stem: str) -> str:
    """`SALA_01_0001_edit` -> `SALA_01_0001`. Unchanged if it is not a result."""
    for m in RESULT_MARKERS:
        if m in stem:
            return stem.split(m)[0]
    return stem


def photo_count(job: Path) -> int:
    """How many photographs the job holds, counted by identity rather than by file.

    Not the same as `len(photos_in(job))`, and the difference matters for the
    archive index. Several jobs in `3 - completed/` had their source photos deleted
    by hand to save space, leaving only the results — so counting sources reports
    them as empty, and `--reindex` used to overwrite an accurate row with a zero.
    Counting distinct photo identities, whether they survive as a source, as a
    result, or as both, makes rebuilding the index safe to run at any time.
    """
    return len({strip_result(p.stem) for p in job.iterdir()
                if p.suffix.lower() in IMAGE_EXTS})


def edit_of(photo: Path) -> "Path | None":
    """The photo's edit, if it has one.

    Two names are accepted because `enhance.NUM_IMAGES` decides which gets
    written: one image is `<name>_edit.jpg`, and two or three — which is what you
    set while tuning PROMPT.md — are `_edit_1`, `_edit_2`. Checking only the plain
    name meant a multi-image run never counted as done, so every photo was run
    again on every pass.
    """
    for candidate in (f"{photo.stem}_edit.jpg", f"{photo.stem}_edit_1.jpg"):
        p = photo.parent / candidate
        if p.exists():
            return p
    return None


def is_done(photo: Path) -> bool:
    return edit_of(photo) is not None


def process(photo: Path, model: str) -> "tuple[Path, str, list[str]]":
    """Run one photo and return (photo, status, its buffered output lines).

    Runs in a worker thread, so it must not print — lines go into a buffer the
    main thread prints as one block.
    """
    lines: "list[str]" = []
    try:
        enhance.run(photo, model=model, emit=lines.append)
    except Exception as e:                      # noqa: BLE001 — one bad photo must not stop the job
        lines.append(f"FAILED      {type(e).__name__}: {e} — re-run to retry this photo")
        return photo, "failed", lines
    return photo, "ok", lines


def log_run(job: Path, model: str, ok: int, failed: int, wall: str) -> None:
    """Append one line of job-level history to job.md."""
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    entry = (f"\n## Run {stamp}\n\n"
             f"- Model: `{model}`\n"
             f"- Result: {ok} enhanced · {failed} failed · {wall} wall clock\n")
    with (job / "job.md").open("a", encoding="utf-8") as fh:
        fh.write(entry)


def job_row(job: Path) -> str:
    """One index line for an archived job, read from the job itself."""
    job_md = job / "job.md"
    found = DROPPED_RE.search(job_md.read_text(encoding="utf-8")) if job_md.exists() else None
    label = found.group(1).strip() if found else "—"
    finished = datetime.fromtimestamp(job.stat().st_mtime, timezone.utc).date()
    return f"| [{job.name}]({job.name}/) | {photo_count(job)} | {label} | {finished} |"


def archived_jobs() -> "list[Path]":
    return sorted((p for p in COMPLETED_DIR.iterdir()
                   if p.is_dir() and JOB_RE.match(p.name)),
                  key=lambda p: p.name)


def rebuild_index() -> None:
    """Regenerate the index from the archive folders — the folders are the
    truth, the index is a convenience. Run it after moving jobs by hand."""
    COMPLETED_DIR.mkdir(exist_ok=True)
    jobs = archived_jobs()
    text = INDEX_HEADER + "".join(job_row(j) + "\n" for j in jobs)

    # Anything in the archive that isn't a job — older work, hand-made folders.
    # The table can't describe it, but leaving it unmentioned makes the index
    # look like a complete picture of the folder when it isn't.
    strays = sorted(p.name for p in COMPLETED_DIR.iterdir()
                    if p.is_dir() and not JOB_RE.match(p.name))
    if strays:
        text += ("\nAlso here, outside the job structure: "
                 + ", ".join(f"`{s}/`" for s in strays) + "\n")
    INDEX_PATH.write_text(text, encoding="utf-8")
    print(f"index       {len(jobs)} job(s) -> 3 - completed/index.md")


def add_to_index(job: Path) -> None:
    """Append this job's row, or refresh it if it is already listed."""
    if not INDEX_PATH.exists():
        rebuild_index()
        return
    row = job_row(job)
    lines = INDEX_PATH.read_text(encoding="utf-8").splitlines()
    marker = f"| [{job.name}]("
    for i, line in enumerate(lines):
        if line.startswith(marker):
            lines[i] = row
            break
    else:
        # Insert after the last table line, not at the end of the file —
        # rebuild_index() can leave a footnote below the table.
        last = max((i for i, l in enumerate(lines)
                    if l.startswith("| [") or l.startswith("|---")),
                   default=len(lines) - 1)
        lines.insert(last + 1, row)
    INDEX_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("indexed     3 - completed/index.md")


def read_rework(job: Path) -> "tuple[list[str], list[str]]":
    """Parse `rework.txt` into (stems that exist, lines that match nothing).

    Forgiving about what you paste: the page copies bare stems, but a whole
    filename, an `_edit.jpg`, or a path is the same photo and worth accepting
    rather than rejecting on a formality.
    """
    path = job / review.REWORK_NAME
    if not path.exists():
        sys.exit(f"error: no {path.relative_to(ROOT)}.\n"
                 f"       Open {job.name}/{review.REVIEW_NAME}, tick what needs "
                 "redoing, press\n       'Copy rejected', and paste it into that "
                 "file.")
    known = {p.stem: p for p in photos_in(job)}
    found, unknown = [], []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        stem = Path(line).stem
        for marker in RESULT_MARKERS:
            if marker in stem:
                stem = stem.split(marker)[0]
                break
        (found if stem in known else unknown).append(stem)
    return list(dict.fromkeys(found)), unknown


def drop_edits(job: Path, stems: "list[str]") -> int:
    """Delete the edits and logs of the rejected photos. Returns files removed.

    This *is* the rework mechanism. `is_done()` above asks whether a photo has an
    edit, so removing one puts that photo back in the queue and leaves every
    approved photo alone — no separate retry list, no state file, nothing that can
    disagree with what is on disk.
    """
    removed = 0
    for stem in stems:
        for p in sorted(job.glob(f"{stem}_edit*.jpg")) + [job / f"{stem}_log.md"]:
            if p.exists():
                p.unlink()
                removed += 1
    return removed


def pairs_in(job: Path) -> "tuple[list[tuple[Path, Path]], list[str]]":
    """(source, edit) for every photo that has one, plus the stems that do not."""
    pairs, missing = [], []
    for p in photos_in(job):
        edit = edit_of(p)
        if edit:
            pairs.append((p, edit))
        else:
            missing.append(p.stem)
    return pairs, missing


def write_review(job: Path, model: str, wall: str) -> Path:
    pairs, missing = pairs_in(job)
    dest = review.write(job, pairs, model, wall, missing)
    print(f"review      {dest.relative_to(ROOT)}")
    print(f"\nOpen it:  open \"{dest}\"")
    return dest


def approve(job: Path) -> None:
    """You said it is good. Check that it is finished, then archive it.

    The check is not second-guessing you — it is the one thing you cannot see on
    the page, because a photo with no edit has nothing to show and so does not
    appear there at all. Archiving a job with a hole in it would put it beyond the
    stage that knows how to fill it.
    """
    pairs, missing = pairs_in(job)
    if missing:
        sys.exit(f"error: {len(missing)} photo(s) in {job.name} have no edit, so it "
                 "is not finished:\n"
                 f"       {', '.join(missing[:8])}"
                 f"{' ...' if len(missing) > 8 else ''}\n"
                 "       Run batch.py to make them, then approve it.")
    for scratch in (job / review.REVIEW_NAME, job / review.REWORK_NAME):
        if scratch.exists():
            scratch.unlink()
    print(f"approved    {job.name} · {len(pairs)} photo(s)")
    finish(job)


def finish(job: Path) -> None:
    """Every photo has a result and you approved it, so archive it."""
    COMPLETED_DIR.mkdir(exist_ok=True)
    dest = COMPLETED_DIR / job.name
    if dest.exists():
        sys.exit(f"error: 3 - completed/{job.name} already exists — "
                 "rename one of them by hand")
    shutil.move(str(job), str(dest))
    print(f"archived    2 - in progress/{job.name} -> 3 - completed/{job.name}")
    add_to_index(dest)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--job", help="job folder name, e.g. Job_0003 "
                                  "(default: lowest-numbered waiting)")
    ap.add_argument("--model", default=enhance.DEFAULT_MODEL)
    ap.add_argument("--workers", type=int, default=WORKERS,
                    help=f"photos in flight at once (default {WORKERS})")
    ap.add_argument("--redo", action="store_true",
                    help="re-run photos that already have a result, overwriting it")
    ap.add_argument("--rework", action="store_true",
                    help=f"read {review.REWORK_NAME} in the job folder, throw away "
                         "the edits it lists, and run just those again")
    ap.add_argument("--approve", action="store_true",
                    help="you have looked at review.html and it is good — archive "
                         "the job to 3 - completed/ and index it")
    ap.add_argument("--reindex", action="store_true",
                    help="rebuild 3 - completed/index.md from the archived "
                         "folders; run nothing")
    args = ap.parse_args()

    if args.reindex:
        rebuild_index()
        return

    job = find_job(args.job)
    all_photos = photos_in(job)
    if not all_photos:
        sys.exit(f"error: {job.name} has no photos in it")

    if args.approve:
        approve(job)
        return

    if args.rework:
        stems, unknown = read_rework(job)
        if unknown:
            print(f"note        {len(unknown)} line(s) in {review.REWORK_NAME} name "
                  f"no photo in {job.name} and were ignored: "
                  f"{', '.join(unknown[:4])}")
        if not stems:
            sys.exit(f"error: {review.REWORK_NAME} lists no photo of {job.name}")
        removed = drop_edits(job, stems)
        print(f"rework      {len(stems)} photo(s) sent back, {removed} file(s) "
              f"deleted: {', '.join(stems[:4])}"
              f"{' ...' if len(stems) > 4 else ''}")

    photos = all_photos if args.redo else [
        p for p in all_photos if not is_done(p)]
    skipped = len(all_photos) - len(photos)

    if not photos:
        print(f"{job.name}: all {len(all_photos)} photo(s) already have an edit — "
              "use --redo to run them again")
        write_review(job, args.model, "no run")
        print(f"\nNothing to run. Approve it when it looks right:\n"
              f'  ./_config/.venv/bin/python "2 - in progress/batch.py" --approve '
              f'--job {job.name}')
        return

    workers = max(1, min(args.workers, len(photos)))
    print(f"\n{job.name} · {len(photos)} photo(s)"
          f"{f' ({skipped} already done, skipped)' if skipped else ''}"
          f" · {workers} at a time · {args.model}")

    t_start = time.time()
    tally = {"ok": 0, "failed": 0}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(process, p, args.model): p for p in photos}
        for n, future in enumerate(as_completed(futures), 1):
            photo, status, lines = future.result()
            tally[status] += 1
            print(f"\n--- {photo.name}  [{n}/{len(photos)}] ---")
            for line in lines:
                print(line)

    elapsed = time.time() - t_start
    wall = f"{elapsed:.0f}s" if elapsed < 90 else f"{elapsed / 60:.1f} min"
    print(f"\n=== {job.name}: {tally['ok']} ok · {tally['failed']} failed · "
          f"{wall} wall clock ({elapsed / len(photos):.1f}s per photo) ===")

    log_run(job, args.model, tally["ok"], tally["failed"], wall)
    write_review(job, args.model, wall)

    if tally["failed"]:
        print(f"\n{tally['failed']} photo(s) failed — re-run to retry just those. "
              "The page above\nshows the ones that did work.")
        return
    print("\nLook at it, then either send the ones that missed back:\n"
          f"  tick them, 'Copy rejected', paste into {job.name}/"
          f"{review.REWORK_NAME}, then\n"
          '  ./_config/.venv/bin/python "2 - in progress/batch.py" --rework '
          f"--job {job.name}\n"
          "\nor approve the job, which is the only thing that archives it:\n"
          '  ./_config/.venv/bin/python "2 - in progress/batch.py" --approve '
          f"--job {job.name}")


if __name__ == "__main__":
    main()
