#!/usr/bin/env python3
"""What `1 - edit/batch.py` and `2 - marca dagua/batch.py` both need.

    import stage
    job = stage.find_job(paths.EDIT_DIR, args.job)
    todo = [p for p in stage.photos_in(job) if not stage.is_done(job, p, "_edit")]

Shared **functions**, deliberately not a framework. The two callers look alike
but differ where it matters: stage 1 is network-bound, billed and
non-deterministic and wants threads; stage 2 is CPU-bound, free and
deterministic. A `Stage(worker=..., pool=...)` object would have to parameterise
that difference and would stop being simpler than the two `main()`s it replaced.
So each stage keeps its own `main()`, its own pool and its own printing, and
borrows the job bookkeeping from here.

**Rejecting a photo means deleting its result** — `is_done()` asks the filesystem
whether the file exists, `drop_results()` deletes the rejected ones, and the
ordinary skip rule re-runs exactly those. No retry list, no state file, nothing
that can disagree with the disk. That is how stage 2 works, and how stage 1's
phase 1 works.

**Stage 1's phase 3 is the exception, and it has to be.** A retouch *edits the
`_edit.jpg`* — the result is the input, so deleting it would destroy what the run
needs. So `1 - edit/batch.py --rework` passes an explicit list of stems instead of
leaning on the skip rule, and `shelve_result()` renames the old result aside rather
than dropping it. Read `1 - edit/2 - retoque/CONTEXT.md` before assuming the delete
rule is universal.
"""

from __future__ import annotations

import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ledger  # noqa: E402
import paths  # noqa: E402

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
JOB_RE = re.compile(r"^Job_(\d+)$")

# What marks a file as a result rather than a source.
#   `_edit`     the fal.ai output, stage 1
#   `_final`    the watermarked deliverable, stage 2
#   `_enhanced` what the first twenty-two archived jobs were written with
#
# `_enhanced` stays for good: drop it and `--reindex` reads 103 archived results
# as sources and doubles every count in the index. `_final` is the one that must
# never be forgotten — a `_final.jpg` that is not recognised as a result is read
# as a source photo and **sent to the paid API**.
RESULT_MARKERS = ("_edit", "_enhanced", "_final")

DROPPED_RE = re.compile(r"^\*\*Dropped as:\*\* (.+)$", re.M)
SHOOT_RE = re.compile(r"^\*\*Shoot:\*\* `(.+?)`", re.M)


# ------------------------------------------------------------------ job numbers

def all_job_dirs() -> "dict[str, Path]":
    """Every `Job_NNNN/` anywhere in the pipeline, by name.

    Scans all three job-holding stages, which is what stops a number from being
    minted twice. Checking only the next stage would let `develop.py` create
    `1 - edit/Job_0023` while `2 - marca dagua/Job_0023` still exists: two photo
    sets, one number, and the index row of one silently overwriting the other.
    """
    found: "dict[str, Path]" = {}
    for d in paths.JOB_DIRS:
        if not d.exists():
            continue
        for p in d.iterdir():
            if p.is_dir() and JOB_RE.match(p.name):
                found.setdefault(p.name, p)
    return found


def next_job_id() -> int:
    ids = [int(JOB_RE.match(n).group(1)) for n in all_job_dirs()]
    return max(ids) + 1 if ids else 1


def new_job_name() -> str:
    return f"Job_{next_job_id():04d}"


# ---------------------------------------------------------------- job contents

def find_job(stage_dir: Path, name: "str | None") -> Path:
    """The job to work on: the one named, or the lowest-numbered waiting here."""
    jobs = sorted((p for p in stage_dir.iterdir()
                   if p.is_dir() and JOB_RE.match(p.name)), key=lambda p: p.name)
    if name:
        for job in jobs:
            if job.name == name:
                return job
        elsewhere = all_job_dirs().get(name)
        hint = f" — it is in {paths.rel(elsewhere.parent)}/" if elsewhere else ""
        sys.exit(f"error: no {name} in {paths.rel(stage_dir)}/{hint}"
                 + (f"\n       waiting here: {', '.join(j.name for j in jobs)}"
                    if jobs else ""))
    if not jobs:
        sys.exit(f"{paths.rel(stage_dir)}/ has no job waiting.")
    if len(jobs) > 1:
        print(f"{len(jobs)} jobs waiting ({', '.join(j.name for j in jobs)}) — "
              f"running {jobs[0].name}. Use --job to pick another.")
    return jobs[0]


def photos_in(job: Path) -> "list[Path]":
    """Source photos only. A result is not an input, and `originais/` is a
    subfolder so `iterdir()` never sees inside it."""
    return sorted(p for p in job.iterdir()
                  if p.is_file() and p.suffix.lower() in IMAGE_EXTS
                  and not any(m in p.stem for m in RESULT_MARKERS))


def strip_result(stem: str) -> str:
    """`SALA_01_0001_edit` -> `SALA_01_0001`. Unchanged if it is not a result."""
    for m in RESULT_MARKERS:
        if m in stem:
            return stem.split(m)[0]
    return stem


def photo_count(job: Path) -> int:
    """How many photographs the job holds, counted by identity rather than file.

    Several archived jobs had their sources deleted by hand to save space,
    leaving only results — counting sources reported them as empty and
    `--reindex` overwrote an accurate row with a zero.
    """
    return len({strip_result(p.stem) for p in job.iterdir()
                if p.is_file() and p.suffix.lower() in IMAGE_EXTS})


def result_of(job: Path, photo: Path, suffix: str) -> "Path | None":
    """This photo's result at this stage, if it has one.

    Two names are accepted because `NUM_IMAGES` decides which gets written: one
    image is `<name><suffix>.jpg`, and two or three — which is what you set while
    tuning the prompt — are `<name><suffix>_1.jpg`.
    """
    for candidate in (f"{photo.stem}{suffix}.jpg", f"{photo.stem}{suffix}_1.jpg"):
        p = job / candidate
        if p.exists():
            return p
    return None


def is_done(job: Path, photo: Path, suffix: str) -> bool:
    return result_of(job, photo, suffix) is not None


def pairs_in(job: Path, suffix: str) -> "tuple[list[tuple[Path, Path]], list[str]]":
    """(source, result) for every photo that has one, plus the stems that do not."""
    pairs, missing = [], []
    for p in photos_in(job):
        got = result_of(job, p, suffix)
        (pairs.append((p, got)) if got else missing.append(p.stem))
    return pairs, missing


def drop_results(job: Path, stems: "list[str]", suffix: str,
                 also: "tuple[str, ...]" = ()) -> int:
    """Delete the rejected results so the skip rule runs those photos again.

    `also` names extra per-photo files this stage owns — stage 1 passes
    `("_log.md",)` because the fal receipt describes the run being discarded.
    Stage 2 passes nothing: its `_log.md` belongs to stage 1 and deleting it
    would destroy the only record of which prompt produced the image, with no
    way to rewrite it from here.
    """
    removed = 0
    for stem in stems:
        targets = sorted(job.glob(f"{stem}{suffix}*.jpg"))
        targets += [job / f"{stem}{s}" for s in also]
        for p in targets:
            if p.exists():
                p.unlink()
                removed += 1
    return removed


SHELVED_RE = re.compile(r"_edit_r\d+\.jpg$", re.I)


def shelve_result(job: Path, photo: Path, suffix: str) -> "Path | None":
    """Rename this photo's current result aside, keeping it. Returns the new path.

    The counterpart to `drop_results()`, for the one place where a rejected result
    must not be deleted: a retouch edits the `_edit.jpg`, so the previous edit is
    both the thing being replaced and the only way back if the retouch fixes what
    you asked and breaks something else. Renaming makes that undo a free rename
    instead of another paid run.

    `_edit_r1`, `_edit_r2`… — never `_edit_1`, which is what `NUM_IMAGES > 1`
    writes and what `result_of()` looks for. The two must not collide.

    Returns None when there was nothing to shelve, which is not an error: a
    retouch of a photo whose edit went missing still has work to do.
    """
    current = result_of(job, photo, suffix)
    if current is None:
        return None
    n = 1
    while (job / f"{photo.stem}{suffix}_r{n}.jpg").exists():
        n += 1
    dest = job / f"{photo.stem}{suffix}_r{n}.jpg"
    current.rename(dest)
    return dest


def drop_shelved(job: Path) -> int:
    """Delete every shelved edit in the job. Returns how many went.

    Called by `--approve`: the versions exist so a human can choose between
    retouch rounds, and once the job has moved on there is nothing left to choose.
    Without this, `3 - completed/` fills with 2K images nobody will ever open.
    What happened is still in `gate.md` and in each `_log.md`.

    Matched by regex rather than by glob so that a hand-named file like
    `SALA_01_0001_edit_red.jpg` is never swept up by a `*_edit_r*.jpg` pattern.
    """
    removed = 0
    for p in sorted(job.glob("*_edit_r*.jpg")):
        if SHELVED_RE.search(p.name):
            p.unlink()
            removed += 1
    return removed


# --------------------------------------------------------------------- job.md

def job_field(job: Path, which: str) -> str:
    """Read `**Dropped as:**` or `**Shoot:**` out of job.md.

    These two lines and `gate.txt` are the only text one script parses out of
    another's output in this project. Change the wording in the writer and the
    reader silently falls back to a dash.
    """
    md = job / "job.md"
    if not md.exists():
        return ""
    rx = SHOOT_RE if which == "shoot" else DROPPED_RE
    found = rx.search(md.read_text(encoding="utf-8"))
    return found.group(1).strip() if found else ""


def log_run(job: Path, lines: "list[str]") -> None:
    """Append one run block to job.md. Creates the file if it is missing."""
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    body = "\n".join(f"- {l}" for l in lines)
    with (job / "job.md").open("a", encoding="utf-8") as fh:
        fh.write(f"\n## Run {stamp}\n\n{body}\n")


# ---------------------------------------------------------------------- moving

def advance(job: Path, dest_dir: Path, stage_dir: Path, photos: int) -> Path:
    """Move the whole job folder to the next stage. The only thing that moves a
    job forward, and the only place `shutil.move` is called on one.

    Refuses rather than merges if the name already exists there: two different
    photo sets under one number is worse than a stopped pipeline.
    """
    dest_dir.mkdir(exist_ok=True)
    dest = dest_dir / job.name
    if dest.exists():
        sys.exit(f"error: {paths.rel(dest)} already exists — a job cannot be in "
                 "two stages at once.\n       Rename or remove one of them by "
                 "hand and run this again.")
    ledger.append(stage_dir, job.name, "left", photos, f"-> `{paths.rel(dest)}`")
    shutil.move(str(job), str(dest))
    print(f"moved       {paths.rel(stage_dir)}/{job.name} -> {paths.rel(dest)}")
    return dest


def failure_summary(errors: "list[str]") -> str:
    """One line when a batch failed wholesale rather than photo by photo.

    Sixty identical failures is a key, a quota or an outage — not sixty photo
    problems — and telling someone to "re-run to retry just those" would burn
    another half hour and more money failing the same way.
    """
    if len(errors) < 2:
        return ""
    kinds = {e.split(":", 1)[0].strip() for e in errors}
    if len(kinds) > 1:
        return ""
    return (f"as {len(errors)} falharam com o mesmo erro ({kinds.pop()}) — isto "
            "não é problema de foto.\n            Confira o FAL_KEY e o status "
            "da fal.ai antes de rodar de novo.")
