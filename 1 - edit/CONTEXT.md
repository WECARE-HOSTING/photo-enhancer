# 1 — Edit

_Last updated: 2026-08-01_

Where a job meets the API, and where a person decides whether it worked. **This is
the only stage that costs money** — stage 0 and stage 2 are local.

**Three phases, one gate.** The gate is in the middle, and it is the whole reason
the stage is shaped this way:

| | Phase | What runs | The prompt |
|---|---|---|---|
| 1 | **edição** | every selected photo → fal.ai | `1 - edicao/PROMPT.md`, the same text for all of them |
| 2 | **o portão** | nothing — `review-edit.html` waits for you | — |
| 3 | **retoque** | only the photos you marked → fal.ai again | your own sentence, per photo, and nothing else |

Phase 1 asks *make every photo of this job listing-ready*. Phase 3 asks *this one
photo, this one thing*. They are different enough questions that they get separate
folders, separate contracts and separate prompts — see `1 - edicao/CONTEXT.md` and
`2 - retoque/CONTEXT.md` for each.

**Input:** `Job_NNNN/` with its photos under their own names, `job.md` and `gate.md`, minted by `0 - selection/develop.py`
**Process:** phase 1 → the gate → phase 3, as many times as you send photos back
**Output:** `<name>_edit.jpg` + `<name>_log.md` beside each source, and the job moves to `2 - marca dagua/` **only when you approve it**

**Nothing is renamed here.** The name arrives settled from `0 - selection/`; phase 1
appends `_edit` and phase 3 overwrites that same `_edit`. `SALA_01_0001.jpg`
produces `SALA_01_0001_edit.jpg` and `SALA_01_0001_log.md`, whatever happens.

## Layout

```
1 - edit/
  CONTEXT.md          this file — the stage: three phases, one gate
  batch.py            the only entry point; every flag below is its
  review.py           writes review-edit.html, the gate itself
  ledger.md           one row per thing that happened in this stage
  1 - edicao/         phase 1 — PROMPT.md, enhance.py, its CONTEXT.md
  2 - retoque/        phase 3 — PROMPT.md, retoque.py, its CONTEXT.md
  Job_0023/           a job in flight: source, _edit and _log side by side
```

The two phase folders hold **tooling**. The job never moves into one of them: a
`Job_NNNN/` stays whole right here, because stages 2 and 3 find files by name in
the job folder and splitting it would hide them.

`ledger.md` stays one file, not one per phase. `grep -n "Job_0023" */ledger.md` is a
job's whole life **in order**, and that ordering is the only reason the file exists;
the phase is already a column in the row (`run 1`, `gate`, `retoque 1`).

## Running it

```bash
./_config/.venv/bin/python "1 - edit/batch.py"                        # fase 1 -> a página, e para
./_config/.venv/bin/python "1 - edit/batch.py" --job Job_0023 --workers 6
./_config/.venv/bin/python "1 - edit/batch.py" --rework               # fase 3 -> só as marcadas
./_config/.venv/bin/python "1 - edit/batch.py" --approve              # -> 2 - marca dagua/
./_config/.venv/bin/python "1 - edit/batch.py" --redo                 # fase 1 de novo, em tudo
./_config/.venv/bin/python "1 - edit/batch.py" --no-serve             # sem servidor, volta ao prompt
```

The folder names have spaces in them — **quote every path**.

**A run ends by opening the page in a browser and waiting there until Ctrl-C.**
`--rework`, `--redo` and `--approve` are all buttons on it, each behind a dialog
naming the exact command; the output streams onto the page and into the terminal
both, so closing the tab loses nothing. `--no-serve` skips all of that and gives
the prompt straight back — which is also what happens automatically when stdout
is not a terminal, so an agent never waits on a server it cannot stop.

**There is no preview step. `batch.py` submits.** No `--dry-run`, no pre-flight cost
estimate, nothing to check first — the command above is the whole thing. (A
`--dry-run` flag existed until 2026-07-27; watching real results was trusted over
its price preview. The dead code sits in `1 - edit/_archive/dry_run.py` and is wired
to nothing. Don't go looking for a preview flag — this paragraph is the answer.)

`batch.py` takes **one job at a time** — the lowest-numbered `Job_NNNN/` waiting here
unless `--job` names another. Photos run **concurrently**, `--workers` at a time, and
each photo's output is buffered and printed as one block so parallel runs stay
readable.

**A photo that already has an `_edit.jpg` is skipped.** That is what makes re-running
after a partial failure a retry of just the failures, at no cost for the photos that
already worked. `--redo` overrides it and overwrites.

**When a whole batch fails the same way**, the run says so instead of telling you to
retry: sixty identical failures is a key, a quota or an outage, and "re-run to retry
just those" would burn another half hour and more money failing identically. The
summary also says whether each failure died **before or after** the request reached
fal, which is the only thing that answers "did I pay for 60 or for 62" without
opening sixty logs.

## The gate

**The job does not advance itself.** It used to archive itself the moment no photo
had failed. But "the API answered" and "this is good enough to send a client" are
different questions, and a script can only answer the first. So a finished run
writes `review-edit.html` into the job folder and stops.

The page is the job's before-and-after: each photo's source and its `_edit` side by
side, half the window each, grouped by ambiente. It is deliberately not the contact
sheet's 215px thumbnails — that page compares fifty photographs to each other, this
one compares exactly two, and the difference between a good edit and a subtly wrong
one does not survive a thumbnail.

**Click an image and press `a` / `b`.** That is the point of this page. Side by side
answers *did it change*; it does not answer *did it change correctly*, because the
eye cannot carry a 3° wall lean or an invented chair across a gap. The flip swaps the
two in place, at identical scale and position, and a wrong edit that survives a
side-by-side does not survive it.

**A photograph that has come back from a retouch shows three panes, and what you
asked for.** `original / edição anterior / retoque`, flipped with `a` / `c` / `b`,
and under them the sentences you wrote — newest always open, older ones folded,
each with a button that opens the edit *that* request replaced. After eight
requests in one round nobody remembers which sentence went with which
photograph, and without them on the page the second look answers "is this good"
when the question is "is this what I asked for". A request whose retouch failed
says so where its result would have been.

The sentences are read back out of each photograph's `<stem>_log.md` and out of
`gate.md`, by `retoque.history()` and `gate.passes()`. That makes the retouch
block a format with a second reader — see `2 - retoque/CONTEXT.md`.

Mark what is **not** good enough, **write why in the box under it**, and press
**Refazer as marcadas** — the dialog lists every photograph going back with the
sentence you wrote under it, which is the last chance to notice a sentence typed
under the wrong photo, and says that fal.ai bills per photograph. Confirm and it
writes `gate.txt`, runs `--rework`, and reloads the page on the results.

Without a server: press **Copiar marcações** and paste into `gate.txt` beside the
page — the file is already there, created by the run, so `open -e` gives you plain
text and the job is ⌘A ⌘V ⌘S. Both buttons produce the same bytes; they call the
same function.

    SALA_01_0002        # a pessoa da janela sumiu, põe de volta
    +COZINHA_01_0001    # bancada clareou mais do que eu queria, mas passa

A bare name sends the photo back; `+` keeps it and records the note anyway. It is
forgiving about what you paste — a bare stem, a filename, an `_edit.jpg`, or a path
all name the same photo.

**What you write in that box is the entire instruction phase 3 sends.** Not a note
appended to `PROMPT.md` — the whole prompt, about the photo on the **right**, free to
ask for what phase 1 forbids. That is the mechanism, and `2 - retoque/CONTEXT.md`
is where it is explained.

**A photo marked back with no comment stops the run.** There is nothing to send, so
`--rework` names those photos and refuses, before recording anything and before
spending anything. Write the why, or untick it. (Want another draw from the same
prompt instead? That is `--redo`, phase 1 again.)

**When the same photo comes back twice, the run says so.** A photo failing the same
way in two rounds is a `1 - edicao/PROMPT.md` problem, not another retouch: the
comment fixes one photo, the file fixes every future one.

When it is right, **you** approve it:

```bash
./_config/.venv/bin/python "1 - edit/batch.py" --approve --job Job_0023
```

`--approve` checks that every photo actually has an edit before moving on — not to
second-guess you, but because a photo with no edit has nothing to show and so does
not appear on that page at all, and passing a job with a hole in it would put it
beyond the stage that knows how to fill it. It also refuses while `gate.txt` still
marks photos for rework, which would otherwise be thrown away silently.

**The order is: record, then delete, then move.** The gate's decisions are folded
into `gate.md` and a row is written to `ledger.md` *before* the scratch files go and
the folder moves. Until 2026-07-31 it did the opposite — unlinked the page and the
rework list and then archived — which destroyed the rejection history at the exact
moment it became permanent.

Approving also **discards the shelved `_edit_rN.jpg` versions**, saying how many. They
exist so you can choose between retouch rounds; once the job has moved there is
nothing left to choose, and `3 - completed/` would otherwise fill with images nobody
opens. The record of what happened stays in `gate.md` and in each `_log.md`.

**Approving is the user's call and nobody else's.** An agent running `--approve` on
its own initiative has decided for them that photos they have not seen are fit to
send a client.

---

## Speed — where the time actually goes

Measured on a 17.8 MB, 4240×2832 camera original (`006.jpg`, 2026-07-26):

| Phase | Before | Now | Why |
|---|---|---|---|
| Prepare | — | 0.2s | Downscale to 2048px in memory |
| Upload | **67.3s** | **5.0s** | 17.8 MB → 1.8 MB over the wire |
| Generate | 45s | 45s | fal.ai's inference — the real floor |
| Download | ~53s | ~53s | fal's CDN edge, cold (see below) |
| **Total** | **~165s** | **103s** | |

Two things dominate, and only one of them is ours:

**The upload was the big waste.** Camera originals are 8–18 MB. The models
render at `TARGET_LONG_EDGE` and read the input through a vision encoder that
downscales anyway, so uploading a 4240px original bought nothing and cost ~63
seconds per photo. `UPLOAD_LONG_EDGE = 2048` downscales in memory first —
17.9× faster upload, no quality loss. A photo already at or under 2048px is
uploaded as-is, with no re-encode. EXIF orientation is baked in before
measuring, so rotated phone photos size correctly.

**The download is fal's, not ours.** The first fetch of a fresh result
materializes the object at fal's CDN edge; the same file that took 52.7s
cold re-downloads in 1.3s. Nothing to fix on this side — but `download()` has
a `DOWNLOAD_TIMEOUT` and retries, because the bare `urlretrieve` it replaced
had no timeout at all and a hung fetch would have stalled a whole batch
forever.

**Parallelism covers the rest.** What's left per photo is almost entirely
waiting on fal, so `batch.py` runs `WORKERS` photos at once. A 20-photo drop
that took ~55 min serially with full-size uploads lands around 9 min at 4
workers. Raise `--workers` if fal keeps up; lower it to spread cost over time.
Every log records its own phase timings, so a slow batch is diagnosable after
the fact rather than by guesswork.

---

## Setup

Requires `FAL_KEY` from https://fal.ai/dashboard/keys. Put it in `_config/.env` —
`cp _config/.env.example _config/.env`, then paste the key in. The script loads
it automatically. `_config/.env` holds a live billing credential: never commit
it, never paste it into chat.

One venv serves all four stages, so rebuild it from the declared list — never
by naming packages by hand:

```bash
python3 -m venv _config/.venv
./_config/.venv/bin/pip install -r _config/requirements.txt
```

This stage would run on `fal-client`, `pillow` and `python-dotenv` alone, which
is what this paragraph used to say. Installing only those three silently breaks
`0 - selection/` entirely — no `rawpy`, no `opencv`, and above all no
`pillow-heif`, without which Pillow cannot open a phone's `.heic` **and does not
say so**: a 48-photo delivery was once curated on the strength of the two JPEGs
in it.
