# 1 — Input

_Last updated: 2026-07-31_

The drop zone. Photos arrive here however the photographer sent them — loose
files, a folder, a folder of folders — and leave as one numbered job. Nothing
here touches the fal.ai API, reads a photo's content, or costs anything.

**This stage no longer renames anything.** It used to be where naming happened:
every drop became `Photo_0001.jpg`, `Photo_0002.jpg`, and the photographer's
filename survived only in `job.md`. Naming moved upstream to `0 - selection/`,
which reads the room out of the filename, checks it against the picture, and
writes `SALA_01_0002.jpg`. Renaming that to `Photo_0007.jpg` here would throw away
the one part of the name a person can read. So the name a photo arrives with is
the name it keeps, all the way to `3 - completed/`.

**Input:** whatever is sitting in `1 - input/`, at any depth, named anything
**Process:** copy every image into one `Job_NNNN/` keeping its name, preserve the drop in `_originais/`, write `job.md`, move the job to `2 - in progress/`
**Output:** `2 - in progress/Job_NNNN/` — the photos under their own names + `job.md`

## Running it

```bash
./_config/.venv/bin/python "1 - input/organize.py"
```

The folder names have spaces in them — **quote every path** or the shell will
split it and the command will fail with a confusing "no such file."

## What it does, and why each part matters

**One drop = one job.** Everything found in `1 - input/` — loose files plus
anything inside dropped folders, at any depth — goes into a single
`Job_NNNN/`. Two shoots dropped at once become one job, so organize the first
one before dropping the second.

**Job numbers are global, photo numbers are not.** `Job_NNNN` counts up across
`1 - input/`, `_originais/`, `2 - in progress/` and `3 - completed/` at once, so a
number is never reused while an older job is still running, sitting in the
archive, or keeping its originals. The photo numbers inside a name restart per
room and are `0 - selection/`'s business, not this stage's.

**Nothing is renamed; only the extension is touched.** `.JPG` becomes `.jpg`,
because `.JPG` and `.jpg` are the same thing to everyone except a string
comparison, and `batch.py` does string comparisons.

**A name used twice is a hard stop.** Two dropped subfolders can each hold a
`SALA_01_0001.jpg`, and a job folder is flat. Renaming one out of the way would
break the promise that a name survives the pipeline, so the run lists the
conflicts and exits without moving anything.

**A drop that never went through `0 - selection/` keeps the photographer's
names.** That works end to end — `enhance.py` derives every output name from the
source's, whatever it is — and the run says which files are not named after a
room, so you can decide whether it matters. To get the room into the name, put
the drop through `0 - selection/` instead.

**The drop is preserved, not consumed.** `1 - input/_originais/Job_NNNN/` holds
the delivery exactly as it arrived, folder structure and all, under the number of
the job it became. The job folder gets copies. This is the same reason
`0 - selection/` never deletes `source/`: when a job goes wrong, the originals are
what a re-run has to start from.

The originals **move** into `_originais/` rather than being left where they fell.
The drop zone has to end up empty or the next run would find the same photos and
build a second job out of them. They move first, before the copy, so that a run
that dies half way leaves nothing to duplicate.

`_originais/` is skipped by name, not by its leading underscore. Skipping every
`_`-prefixed folder would be tidier to write and would silently swallow a drop
that happened to be named one — and a drop this script ignores is a delivery
nobody notices is missing.

**`job.md` records what each photo was, and the order it came in.** Less
load-bearing than it used to be, now that the name itself survives, but still the
only place the photographer's original filename is written down — and now the only
place the walkthrough order is, because names sort by ambiente (`AREA_SERVICO`
lands above `SALA` on disk whatever order they were shot in). The `#` column is
the order they were dropped, which for a job out of `0 - selection/` is the gallery
order. **Never delete it from a job folder.**

Its `**Dropped as:**` line names the job the way a person would — the dropped
folder's name, or the first filename if the drop was loose files. That line is
what `batch.py` copies into `3 - completed/index.md` when the job is archived,
so it is worth editing by hand if the automatic label is unhelpful. It is also the
only text one script parses out of another's output, so its wording is fixed.

**Non-images are left behind.** A `.txt`, `.pdf`, or `.zip` in the drop is
reported and travels into `_originais/` with the rest; only `.jpg`, `.jpeg`,
`.png`, and `.webp` reach the job. `organize.py` and this file are skipped,
obviously.

**An interrupted run is safe to re-run.** If a `Job_NNNN/` folder is still
sitting in `1 - input/` — the process died between building it and moving it —
the next run finishes the hand-off instead of building a job inside a job.

## When it stops

`organize.py` exits without moving anything if `2 - in progress/` already has a
job folder of the same name, if `_originais/` already holds that job, or if two
dropped files want the same name. The first two should be impossible with the
shared counter; if they happen, something was renamed by hand, and it wants a
human rather than a guess.

Note that `2 - in progress/` holding *another* job is fine and does not block
organizing — the jobs queue there, and `batch.py` runs the lowest-numbered one
first. It is one job at a time through the API, not one job at a time in the
building.

## Next stage

The job is now `2 - in progress/Job_NNNN/`. Read `2 - in progress/CONTEXT.md`
to run it — and note that it no longer archives itself: it stops at a
`review.html` and waits for you to approve it.
