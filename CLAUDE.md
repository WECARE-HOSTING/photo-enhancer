# AI Real Estate Photo Enhancer

Photos in, listing-ready photos out. **Four folders, one per process step** — a
job moves forward one folder at a time, only ever when a human approves it, and
never goes back on its own.

**The one rule: enhance the real photo, never recreate it.** Same room, same
layout, same furniture, shot better. A beautiful photo of a *different* room is
a failed job — it misrepresents a property someone will rent or buy.

## Layout

```
0 - selection/     drop -> choose -> name -> develop. Keeps the shoot forever.
                   drop/, 6 scripts, ledger.md, CONTEXT.md
1 - edit/          the fal.ai stage, in two phases around one gate.
                   batch.py + review.py, ledger.md, CONTEXT.md
                   1 - edicao/   fase 1: PROMPT.md fixo, toda foto. enhance.py
                   2 - retoque/  fase 3: a frase do humano, uma foto. retoque.py
2 - marca dagua/   the WeCare mark. marca.py, batch.py, review.py
3 - completed/     the archive. index.md, archive.py, and the finished jobs
_config/           .env (FAL_KEY, gitignored), .venv/, requirements.txt,
                   logos/, Seletor/RULES.md + AMBIENTES.md,
                   paths.py ledger.py gate.py stage.py fal.py (shared)
_dependencies.md   what breaks what, when a file here changes
```

**`0 - selection/drop/` is the only way in.** A delivery of 30 already-chosen
photos enters there too — `cull.py` recognises a finished selection and cuts
nothing.

**The two folders inside `1 - edit/` hold tooling, never a job.** A `Job_NNNN/`
stays whole in `1 - edit/` — split it and stages 2 and 3 stop finding its files.

Every numbered folder keeps a `ledger.md`: one row per thing that happened in
it. `grep -n "Job_0023" */ledger.md` is a job's whole life, in order — so
`1 - edit/` keeps **one** ledger for both its phases, with the phase in the row.

## Naming convention

**A photo is named once, in `0 - selection/`, and keeps that name to the end.**

```
SALA_01_0002.jpg         ambiente · which room of that kind · which photo
SALA_01_0002_edit.jpg    what the API returned
SALA_01_0002_final.jpg   with the mark — this is what a client gets
SALA_01_0002_log.md      what was sent and what came back
```

The ambiente comes from `_config/Seletor/AMBIENTES.md` — a fixed vocabulary, so
`SALA` means the same thing in every job. It is read out of the photographer's own
filename, which is right almost every time, and then **checked against the picture
and corrected when it is wrong**; a photo they never labelled is named from the
picture alone. Each shoot's `ambientes.md` records every file's answer and where it
came from, and is the file to edit when one is wrong — normally through
`review-selection.html`, which writes it for you.

**Deliveries are named `WC-NNNNN` — that `WC` is WeCare, never a bathroom.** The
vocabulary does map `wc` to `BANHEIRO`, correctly, so the reference is stripped
before any room word is matched (`AMBIENTES.md` → "Property codes"). Nothing in a
property's reference is ever a room.

**A job is born in `develop.py`** — the one moment the shoot's name and a fresh
number are in the same process, which is what lets the archive know three stages
later which delivery a job came from. Numbers count up across all three job
folders and never collide. Photo numbers restart in every room.

Nothing downstream renames anything: `enhance.py` only appends `_edit`,
`marca.py` only `_final`. A re-run overwrites its own suffix — one photo, one
current edit, one current mark. The one extra name is `_edit_r1`, `_edit_r2`… —
edits a retouch replaced, kept so you can go back, and discarded on approval.

## Routing

| Task | Go to | Read |
|---|---|---|
| A photographer sent a link, a zip, or hundreds of photos | `0 - selection/fetch.py` | `0 - selection/CONTEXT.md` |
| Change how photos get chosen | `_config/Seletor/RULES.md` | same → "Editing the rules" |
| Change what rooms are called, or add a photographer's word | `_config/Seletor/AMBIENTES.md` | that file → "The vocabulary" |
| One photo is filed under the wrong room | change it under the photo in `review-selection.html`, "Copy ambientes.md", re-run `cull.py --no-classify` | `0 - selection/CONTEXT.md` → "The contact sheet is the gate" |
| Two rooms of the same kind came back as one | same place — `+ novo QUARTO` on the photos of the second one | same |
| See what a room label maps to, free | `0 - selection/ambientes.py "Sala Cobertura"` | same |
| Turn the picks into a job | `0 - selection/develop.py <shoot>` | same → "The handoff" |
| Run a job through the API | `1 - edit/batch.py` | `1 - edit/CONTEXT.md` → "Running it" |
| Judge the edits, send some back | the job's `review-edit.html` → `gate.txt` → `batch.py --rework` | same → "The gate" |
| Change how outputs look, for every photo | `1 - edit/1 - edicao/PROMPT.md` | that folder's `CONTEXT.md` → "Editing PROMPT.md" |
| Fix one photo, in your own words | the box under it in `review-edit.html` — that text is the whole prompt | `1 - edit/2 - retoque/CONTEXT.md` |
| Change what the retouch tells the model about the two images | `1 - edit/2 - retoque/PROMPT.md` | same |
| Verify a prompt edit didn't break a rule | `1 - edicao/enhance.py --check` (free, no photo) | `1 - edicao/CONTEXT.md` → "Editing PROMPT.md" |
| Change model, quality, size, timeouts | `_config/fal.py` constants (both phases) | `1 - edicao/CONTEXT.md` → "Config" |
| Change how many photos run at once | `1 - edit/batch.py` → `WORKERS` | same |
| Put the mark on a job | `2 - marca dagua/batch.py` | `2 - marca dagua/CONTEXT.md` |
| The mark is too big, or in the wrong place | `2 - marca dagua/marca.py` constants, then `batch.py --rebrand` (free) | same → "Tuning the mark" |
| Replace the logo art | `_config/logos/` — same filenames | same |
| Find a finished job | `3 - completed/index.md` | `3 - completed/CONTEXT.md` |
| Something feels off — a folder got dragged? | `3 - completed/archive.py --check` (free) | same |
| Reclaim disk from a finished shoot | `archive.py --purge-source <shoot>` | same → "Deleting the originals" |
| What happened in a phase | that folder's `ledger.md` | — |
| Trace what a change breaks | `_dependencies.md` | that file |

## Running it

Three stages, three commands, three stops. **Each stop is a human decision the
pipeline cannot make**, and each is a page in the job folder:

```bash
./_config/.venv/bin/python "0 - selection/cull.py" "0 - selection/<shoot>"   # -> review-selection.html
#   tick your picks, 'Copiar picks', paste into picks.txt
./_config/.venv/bin/python "0 - selection/develop.py" "0 - selection/<shoot>"  # -> 1 - edit/Job_NNNN

./_config/.venv/bin/python "1 - edit/batch.py"            # fase 1 -> review-edit.html, and stop
#   a / b flips before-after full screen; mark what is wrong, write WHAT TO CHANGE —
#   that text is the whole prompt of the retouch, and may ask what fase 1 forbids
./_config/.venv/bin/python "1 - edit/batch.py" --rework   # fase 3 -> só as marcadas
./_config/.venv/bin/python "1 - edit/batch.py" --approve  # -> 2 - marca dagua/

./_config/.venv/bin/python "2 - marca dagua/batch.py"           # -> review-marca.html
./_config/.venv/bin/python "2 - marca dagua/batch.py" --rebrand # tune it, free
./_config/.venv/bin/python "2 - marca dagua/batch.py" --approve # -> 3 - completed/
```

**Run each command straight through.** There is no dry run, no preview, no
pre-flight check — asking for one, or opening `CONTEXT.md` to look for one, is
the wrong move.

**Never run `--approve` on your own initiative**, at any stage. Approving is the
user saying this is good enough to send a client, and that is not a judgement to
make for them. The same goes for `develop.py`, which moves a job just as much as
`--approve` does, and for `archive.py --purge-source`, which deletes photographs.
Run them when asked, and not before.

**Quote every path** — the folder names contain spaces.

**Only `1 - edit/` costs money.** Photos run at `medium` quality and ~2K,
concurrently, a minute or two each, almost entirely spent waiting on fal.ai; fal
bills by quality tier *and* pixel count, so check fal's dashboard rather than
expecting an estimate. A photo that failed has no `_edit`, and re-running
retries only those. **Stage 0 and stage 2 are local and free** — `--rebrand` and
`cull.py --no-classify` can be run as often as you like.

**A finished run is handed over as-is — never open, compare, or grade the
results.** Point the user at the page and stop there. Judging the photos is
theirs to do, on their screen, and that page is where the pipeline asks them to;
a script cannot tell a good edit from a subtly wrong one, and neither can you
from a file listing. When they report the same failure twice, tighten
`PROMPT.md` — it applies to every future photo — rather than re-running.

*(The watermark stage reads pixels — background luminance, contrast, spread. That
is **measurement**, and it is how the mark picks its ink. It is not grading, and
the rule above is untouched.)*
