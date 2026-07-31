# AI Real Estate Photo Enhancer

Photos in, listing-ready photos out. Three folders, in order — a job moves
forward one folder at a time and never goes back.

**The one rule: enhance the real photo, never recreate it.** Same room, same
layout, same furniture, shot better. A beautiful photo of a *different* room is
a failed job — it misrepresents a property someone will rent or buy.

## Layout

```
0 - selection/     optional, upstream: cuts a 300-photo delivery to ~50 before
                   any of them cost money, and names every one after its room —
                   CONTEXT.md, drop/, 6 scripts
1 - input/         drop zone and organizer — CONTEXT.md, organize.py,
                   _originais/ (every drop, as it arrived)
2 - in progress/   the API stage and the approval gate — CONTEXT.md, PROMPT.md,
                   enhance.py, batch.py, review.py, plus the Job_NNNN/ folders
                   waiting, running, or waiting on you
3 - completed/     archive of approved Job_NNNN/ folders + index.md, one row each.
                   No contract, nothing runs here
_dependencies.md   what breaks what, when a file here changes
_config/           .env (FAL_KEY, gitignored — see .env.example), .venv/,
                   Seletor/RULES.md (how photos get chosen),
                   Seletor/AMBIENTES.md (what rooms are called)
```

A delivery of 30–60 photos someone already chose goes straight into `1 - input/`,
as it always did. `0 - selection/` is for the 300-photo dump.

## Naming convention

**A photo is named once, in `0 - selection/`, and keeps that name to the end.**

```
SALA_01_0002.jpg        ambiente · which room of that kind · which photo
SALA_01_0002_edit.jpg   the result
SALA_01_0002_log.md     what was sent and what came back
```

The ambiente comes from `_config/Seletor/AMBIENTES.md` — a fixed vocabulary, so
`SALA` means the same thing in every job. It is read out of the photographer's own
filename, which is right almost every time, and then **checked against the picture
and corrected when it is wrong**; a photo they never labelled is named from the
picture alone. Each shoot's `ambientes.md` records every file's answer and where it
came from, and is the file to edit when one is wrong — normally through
`contact.html`, which writes it for you.

**Deliveries are named `WC-NNNNN` — that `WC` is WeCare, never a bathroom.** The
vocabulary does map `wc` to `BANHEIRO`, correctly, so the reference is stripped
before any room word is matched (`AMBIENTES.md` → "Property codes"). Nothing in a
property's reference is ever a room.

Job numbers count up across all three stage folders so they never collide. Photo
numbers restart in every room. Nothing downstream renames anything: `organize.py`
only gathers photos into a `Job_NNNN/`, and `enhance.py` only appends `_edit`. A
re-run overwrites the `_edit` — one photo, one current edit — and the log records
which `PROMPT.md` produced it.

Names now sort by ambiente rather than by shooting order, so the walkthrough order
lives in `job.md`'s `#` column and in the shoot's `selection.md`.

## Routing

| Task | Go to | Read |
|---|---|---|
| A photographer sent a link, a zip, or hundreds of photos | `0 - selection/fetch.py` | `0 - selection/CONTEXT.md` |
| Change how photos get chosen | `_config/Seletor/RULES.md` | same → "Editing the rules" |
| Change what rooms are called, or add a photographer's word | `_config/Seletor/AMBIENTES.md` | that file → "The vocabulary" |
| One photo is filed under the wrong room | change it under the photo in `contact.html`, "Copy ambientes.md", re-run `cull.py --no-classify` | `0 - selection/CONTEXT.md` → "The contact sheet is the gate" |
| Two rooms of the same kind came back as one | same place — `+ novo QUARTO` on the photos of the second one | same |
| See what a room label maps to, free | `0 - selection/ambientes.py "Sala Cobertura"` | same |
| Organize a new drop into a job | `1 - input/organize.py` | `1 - input/CONTEXT.md` |
| Run a job through the API | `2 - in progress/batch.py` | `2 - in progress/CONTEXT.md` → "Running it" |
| Approve or reject a finished run | the job's `review.html`, then `batch.py --approve` | same → "The gate" |
| Redo the photos you rejected | `batch.py --rework` | same → "The gate" |
| Change how outputs look | `2 - in progress/PROMPT.md` | same → "Editing PROMPT.md" |
| Verify a prompt edit didn't break a rule | `enhance.py --check` (free, no photo) | same → "Editing PROMPT.md" |
| Change model, quality, workers, size | `2 - in progress/enhance.py` constants | same → "Config" |
| A run felt slow | the job's `<name>_log.md` timing row | same → "Speed" |
| Find a finished job | `3 - completed/index.md` | that file, then the job's `job.md` |
| Trace what a change breaks | `_dependencies.md` | that file |

## Running it

```bash
./_config/.venv/bin/python "1 - input/organize.py"     # drop -> Job_NNNN -> 2 - in progress/
./_config/.venv/bin/python "2 - in progress/batch.py"  # run it -> review.html, and stop
```

**Run those two straight through.** There is no dry run, no preview, no pre-flight
check to do first — asking for one, or opening `CONTEXT.md` to look for one, is the
wrong move. ("Run input" means both commands, end to end.)

Then the job **waits for the user**, in `2 - in progress/`, until they approve it:

```bash
./_config/.venv/bin/python "2 - in progress/batch.py" --rework   # redo what they rejected
./_config/.venv/bin/python "2 - in progress/batch.py" --approve  # -> 3 - completed/
```

**Never run `--approve` on your own initiative.** Approving is the user saying the
photos are good enough to send a client, and that is not a judgement to make for
them. Run it when they ask, and not before.

**Quote every path** — the folder names contain spaces. Photos run at
`medium` quality and ~2K; fal bills by quality tier *and* pixel count, so
check fal's dashboard for actual spend rather than expecting a pre-flight
estimate. Photos in a job run concurrently, a minute or two each, almost entirely
spent waiting on fal.ai. A photo that failed has no `_edit`, and re-running
`batch.py` retries only those.

**A finished run is handed over as-is — never open, compare, or grade the
results.** Point the user at `review.html` and stop there. Judging the photos is
theirs to do, on their screen, and that page is where the pipeline asks them to;
a script cannot tell a good edit from a subtly wrong one, and neither can you from
a file listing. When they report the same failure twice, tighten `PROMPT.md` — it
applies to every future photo — rather than re-running.
