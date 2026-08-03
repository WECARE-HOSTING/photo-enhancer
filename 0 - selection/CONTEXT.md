# 0 — Selection

_Last updated: 2026-08-02_

Where a photographer's whole delivery becomes the handful of photos worth paying
to enhance. No photo is sent to `gpt-image-2` from this folder, ever — the cost
here is cents of vision calls, not dollars of image generation, and
`--no-classify` runs the whole stage for nothing.

**Input:** whatever the photographer sent — a link, a zip, a pile of zips, a
folder of RAW, 300 JPEGs
**Process:** fetch and verify → profile → proxies and measurements → **name every
room and check the name against the picture** → **tell two rooms of the same kind
apart** → quota per room → a vision model proposes the picks → you decide →
develop the picks
**Output:** `1 - edit/Job_NNNN/` holding `SALA_01_0001.jpg` … — the names the
photos keep for the rest of their lives

## Three things that are true here and nowhere else

The other three folders taught you a shape. This one breaks it, deliberately, in
three ways. Reading them as mistakes will cost you work.

**1. This folder receives and keeps. It does not consume and empty.** The other
three pass a `Job_NNNN/` along and are empty again; a shoot folder here holds its
3.7 GB of originals until you deliberately purge it. Only the ~50 chosen photos
leave as a job — but every photograph gets developed, and the rest wait in
`developed/` for the archive to collect them.

**2. There is a mandatory human gate in the middle.** The rest of the pipeline
runs straight through — that is the whole point of `CLAUDE.md`'s "run them
straight through". This stage stops at `review-selection.html` and waits for you. Nothing
downstream can proceed without a `picks.txt`, and nothing here will invent one.

**3. Your picks are final.** `develop.py` does not re-apply the quota, drop a
flagged frame, or reconsider. `cull.py` had its say on the contact sheet and lost
the argument the moment you edited the list.

**4. This is where a photo gets its name, and the name never changes again.** It
used to be a downstream job, as `Photo_0001.jpg`. Now the room is in the name —
`QUARTO_02_0001.jpg` — and nothing downstream renames it: `enhance.py` only
appends `_edit` and `marca.py` only `_final`. That makes the
naming decisions taken here visible in every folder the photo passes through, and
it makes getting one wrong visible too, which is why they are checked.

## Running it

```bash
# 1. get it onto disk — drop the photographer's folders/zips in drop/ first
./_config/.venv/bin/python "0 - selection/fetch.py" --name "Cobertura"
#    or point it at a path or a link:
./_config/.venv/bin/python "0 - selection/fetch.py" ~/Downloads/shoot-001.zip --name "Cobertura"

# 2. proxies, measurements, room names, quota, contact sheet
./_config/.venv/bin/python "0 - selection/cull.py" "0 - selection/Cobertura" --vision

#    cull.py then opens review-selection.html in a browser and waits there
#    until Ctrl-C. Steps 2b, 3 and 4 below are buttons on that page — each
#    confirms the exact command first, then runs it with the output on screen.

# 2b. a room is wrong, or one room is really two? fix it on the sheet itself —
#     change the room under the photograph, then 'Salvar e re-cortar'. Free: the
#     naming pass is already settled. Without a server: "Copy ambientes.md",
#     paste it over that file, and run
./_config/.venv/bin/python "0 - selection/cull.py" "0 - selection/Cobertura" --vision --no-classify

# 3. tick your picks. 'Salvar picks.txt' writes them; without a server, press
#    "Copiar picks" and paste into picks.txt yourself.

# 4. mint the job: develop the picks into 1 - edit/Job_NNNN/, and the rest
#    into developed/ for the archive to collect later. On the page that is
#    'Revelar o trabalho', which also ends the review session.
./_config/.venv/bin/python "0 - selection/develop.py" "0 - selection/Cobertura"

# 5. the API stage, then the mark, each with its own gate
./_config/.venv/bin/python "1 - edit/batch.py"
./_config/.venv/bin/python "2 - marca dagua/batch.py"
```

**Quote every path** — the folder names contain spaces.

**Every delivery comes in through `drop/`, including one that is already
curated.** There is no side door any more. A finished selection of 30–60 photos
still runs `fetch.py` and `cull.py`; `cull.py` recognises it (see "Type A"
below), cuts nothing, and pre-ticks the sheet, so the gate is one look and a
paste rather than a curation session. One way in is worth the extra command.

## The six scripts

| Script | Does | Costs |
|---|---|---|
| `fetch.py` | link/zip/folder → `source/`, verified against a named inventory | nothing |
| `ingest.py` | one file → a proxy, its EXIF, its geometry. A module; `cull.py` calls it per file | nothing |
| `ambientes.py` | the canonical room vocabulary, label → slug, and the shoot's `ambientes.md`. A module, and a CLI for testing a label | nothing |
| `vision.py` | asks the model two different questions: what room is this, and which of these is best. A module; also standalone per room | per call |
| `cull.py` | profile, group, **name and verify the rooms**, allocate the quota, write `review-selection.html` + `ambientes.md` + `selection.md` | the naming pass, unless `--no-classify` |
| `develop.py` | `picks.txt` → `1 - edit/Job_NNNN/` under the final names, developing raw and fusing brackets; also develops the unpicked into `developed/`, mints the job number, writes `job.md`, `originais.md` and `gate.md` | nothing |

`ingest.py`, `ambientes.py` and `vision.py` also run standalone on one file, one
label or one room, which is how you judge a change without paying for a whole
delivery:

```bash
./_config/.venv/bin/python "0 - selection/ambientes.py"                    # the vocabulary
./_config/.venv/bin/python "0 - selection/ambientes.py" "Sala Cobertura"   # what it maps to
```

## What each part does, and why it is built that way

### The delivery is profiled before it is processed

`cull.py` opens no pixels until it has decided what kind of delivery this is,
from filenames and EXIF headers alone. On 307 files that pass is instant; the
pixel pass that follows is 14 seconds. Getting the delivery wrong is caught
before the work, not after.

| Type | What it is | What happens |
|---|---|---|
| **A** | already culled — ≤60 photos, ~3 per room | **nothing is cut.** Every frame is pre-ticked |
| **B** | JPEG with the room named in each filename | quota per room, ranked, vision picks |
| **C** | JPEG with camera filenames | the room has to be recognised from the picture |
| **D** | RAW with exposure brackets | brackets merged in `develop.py` |
| **E** | RAW, single frames | developed in `develop.py` |

`--profile-only` prints the verdict and stops. `--type` forces it. The reasoning
lands in the shoot's `profile.md`.

**Type A matters more than it looks.** It is the pipeline's original path. A
delivery someone has already chosen must not be curated again — cutting it drops
photos that were picked on purpose. When the type is guessed from a small
unlabelled delivery, the near-duplicate count from the pixel pass is used to
check the guess and contradicts it out loud if it was wrong.

### The RAW file is never opened to judge it

Every camera writes a full JPEG preview inside its own raw file.
`rawpy.extract_thumb()` hands that over with no demosaicing — milliseconds, not
seconds, and no 150 MB intermediate. Judging happens on 1600 px proxies (82 MB
for a 3.7 GB delivery); the negatives are only developed for the frames that get
picked.

### Two reductions, and they are different things

**Brackets** collapse several exposures of one scene into one future photo,
detected from timestamps plus a varying exposure bias. Both are required —
a burst at one setting is not a bracket, and merging it would silently turn five
compositions into one.

**Clusters** group the same corner shot repeatedly, by perceptual hash, and only
within one room: a bathroom and a bedroom can hash alike, and merging them would
drop one of the two entirely.

**How much this buys you depends on the photographer, and it is worth measuring
rather than assuming.** On the delivery this stage was built against, 307 photos
collapsed to 273 distinct angles — the median hash distance *within* a room was
30, meaning that photographer shoots genuinely different angles rather than
variations of one. Clustering was nearly useless there. Going from 307 to 50 was
curation, not deduplication.

### Geometry is measured; content is judged

`ingest.py` measures two things the strategy document rejects outright:

- **roll** — the whole frame rotated. A level correction fixes it.
- **convergence** — the camera pitched up or down, so verticals splay. This is
  the "falling backwards" look, and no rotation fixes it.

Both come from fitting a line through the lean of every near-vertical segment
against its horizontal position: lean that correlates with position is
convergence, lean that is uniform is roll.

**Getting this measurement to mean anything took three attempts, and the
failures are instructive.** Least squares let a handful of stray segments drag
the fit; a narrow spread of verticals let the slope be extrapolated across the
whole frame; and a 32° tolerance collected ceiling drying racks and floor grout
instead of walls, reporting a 40° roll for a laundry whose walls are plainly
straight. What works: Theil-Sen instead of least squares, a required 35%
horizontal span, and a 15° tolerance. After that, roll p50 fell from 2.04° to
0.47° and the flag rate from 29% to 8.5%.

The cost of the tight tolerance, stated plainly: a frame tilted more than ~15°
now reports *unmeasurable* rather than a large number. That is the right way
round — a tilt that large is obvious at a glance, and the reason to measure is
the 3–6° lean that slips past the eye.

**Wide-angle is checked from EXIF and often cannot be checked at all.** The
delivery this was built against carried no EXIF whatsoever in any of its 307
files, so the focal-length rule never fired once. Focal length cannot be
recovered from pixels. When it matters, ask the photographer to export with
metadata intact.

### The room comes from the filename, then gets checked against the picture

The cheapest, most accurate room classifier is the photographer's own naming.
One delivery named 277 of 307 files `NN_Ambiente_N.JPG`; all 307 were labelled
correctly, including the walkthrough order, at no cost. A model would be slower,
dearer, and worse at it. So the filename is read first, and it is believed.

It is then **verified**, because "right almost every time" is not the same as
right, and a wrong room now travels in the filename all the way to a client. One
call per room shows the model that room's photographs and asks it to confirm the
label or correct it. Measured on the delivery above: 18 of 18 labels confirmed,
which is the outcome to expect — this pass earns its keep on the delivery where
one is wrong, not on the ones where none are.

It runs by default and is skipped by `--no-classify` or by having no `FAL_KEY`.
The sheet and the catalogue both say plainly when the names were not checked,
because an unverified name looks exactly like a verified one otherwise.

**With no label, the question changes shape — and so does the unit of a call.** A
group of photographs only exists because something put those files together, and
when that something is a folder named `3_Condomínio/`, it is not evidence of a
room. Asking "which room is this?" of a gym, a lobby and a pool deck at once gets
one answer for all three — measured: 28 files arrived as one imaginary
`SALAO_FESTAS`. So an unlabelled photograph is named **on its own, in its own
call**, and the grouping that follows splits them into the real places they were.
This is the type-C path, and it is the reason the type-C stub is gone.

One call per photograph is dearer than one per room and it is not optional.
Twelve photographs used to go in together with an array of twelve answers asked
for back; that array truncates at the token limit, and every photograph missing
from it silently inherited whatever the rest of the batch had voted for. Measured
on `WC-00284`: three photographs of a bed were delivered as `COZINHA`, and nothing
in the output said a guess had been substituted for an answer. A photograph now
gets its own answer or an honest `NAO_IDENTIFICADO` — never another photograph's.

The prompt for that call is a **separate block** in `AMBIENTES.md` from the one
that confirms a label, and separating them was half the fix. The confirm text
opens "photographs of ONE room of ONE property" and "agree unless you can see that
they are wrong"; both are false when there is no label, and the unlabelled path was
being handed both. It asks for the fixtures in view — a bed, a cooktop, a toilet,
a shower box — **before** the room name, because naming the room first is how a
photograph of a bed becomes a kitchen.

**A property reference is not a room, and one of them looks exactly like one.**
WeCare names its properties `WC-NNNNN`, and `wc` is a perfectly good synonym of
`BANHEIRO` — in Portuguese a WC *is* a bathroom. When the filenames name no room,
the innermost folder is the fallback, so `WC-00660 - Casa MAD Alter` labelled a
whole house as a bathroom: 48 photographs, one imaginary room, and the vision pass
could only correct that single answer rather than split it. The vocabulary keeps
`wc → BANHEIRO`, because it is right; the collision is settled by shape instead,
in the `Property codes` table in `AMBIENTES.md`. Add a row there when a client's
reference format contains a room word.

`ambientes.md` in the shoot folder records every file's ambiente, the room it
belongs to, and where the answer came from. **It is the file to edit when one is
wrong** — usually via the sheet rather than by hand — and it is read back on the
next run.

`Sala` is an input too — the `02` in `QUARTO_02`. Changing a row's `Ambiente`
discards its `Sala`, because a room number only means something inside the
ambiente it was handed out in.

**Which room of that kind is now asked of the pictures**, once every photograph
knows what *kind* of room it is: one call per ambiente holding two or more
photographs, showing all of them at once, asking which are the same physical room.
Nothing else in the stage can answer it — every other source of a room's identity
is a token in a folder or a filename, and a flat folder of camera filenames has
none. A perceptual hash cannot stand in either, and not marginally: two views of
one room from opposite corners hash further apart than two rooms furnished from
the same shop.

It is asked only where the photographer's own labels say nothing. Someone who
filed into `2_Quarto_1/` and `3_Quarto_2/` walked the property and knows, and no
model overrules that. An *absent* label is not a distinguishing one — a veranda
photograph nobody had named used to land in a `VARANDA_02` of its own next to
three photographs of the same hammock.

**Every doubt resolves to one room.** A file missing from the answer, a file
listed twice, more photographs than can be compared in one look: all leave the
ambiente merged. A merge is one click to fix on the sheet; a `QUARTO_02` that does
not exist is a wrong filename at the client.

Your number still wins, and needs no second column to prove you set it: a row of
the catalogue that still applies outranks the pass, so a `Sala` you typed survives
every re-run and the pass is not even asked about that ambiente again.

Two columns answer "did a person change this?", and one column cannot. `Ambiente`
is the answer in force and the column you edit; `Visto` is what the last run's
check saw. A run always writes `Visto` to whatever it just computed, so the two
agree unless you pulled them apart — which makes a difference *proof* of your
edit, rather than merely proof that this run disagreed with the last one.
Per-photo classification of an unsorted folder is not deterministic and does
disagree with itself occasionally; without the second column, that drift would be
recorded as your decision and would then outrank every future check.

A room you have corrected is skipped entirely on later runs. Everything else is
re-checked every run — that is the difference between a cache and a decision.

Category and priority still come from `RULES.md`, but keyed on the canonical
ambiente rather than matched against free text. The matching that produces the
ambiente uses the same rule as before, **by where the keyword appears and not by
how long it is**: room names put the noun first and the qualifier after — `Sala
Cobertura` is a living room *in* the penthouse — so preferring the longest keyword
filed it as a roof terrace, because `cobertura` is longer than `sala`.

### The quota: three per room as a floor, 40–60 as the target

Three per room is the rule this project's team was already running by hand, and
it is a good floor because it forces every room to be shown. The gallery target
is what the whole set must land in; rooms get extra slots to reach it.

Growing and shrinking are **not** mirror images, and each direction is right for
its own reason. **Expanding spreads** — the eighth angle on a terrace tells a
guest less than the fourth angle in a bathroom, so every room gets its extra slot
in turn. **Trimming concentrates at the bottom** — the third photograph of a
staircase is worth less than the third of a bedroom, which has a bed
configuration to prove, so the lowest-priority band is spent down to one before
the band above loses anything.

Neither direction ever exceeds the distinct angles a room actually has, and no
room with a photograph delivered ends at zero.

The keyword table, the priorities and the target all live in
`../_config/Seletor/RULES.md`.

### The ranking pass asks one question per room, not per photograph

Choosing the best three of twenty-one kitchen shots is a **comparison**, and a
comparison cannot be made one photograph at a time. `fal-ai/any-llm/vision` takes
`image_urls` as an array, so a whole room goes into one call. A room with more
angles than fit runs a tournament, with batches dealt by rank rather than sliced
in file order — slicing puts the strong stretch in one heat and lets a good frame
lose to weaker neighbours.

(The naming pass above goes the other way for an unlabelled photograph — one call
each. The unit of a call follows what has to be in view to answer the question,
not a house style.)

Measured: 19 rooms, 39 calls, 149 seconds, 52 of 56 slots proposed with a written
reason in Portuguese. The four empty slots are the prompt working — it is allowed
to return fewer when fewer deserve it.

**It may refuse the room it was handed.** The ranking pass is told which room it
is looking at, and until it could push back it simply wrote a reason agreeing with
whatever it was told: a terrace filed under `COZINHA` was praised for *"destacando
a geladeira"*, and the mislabel was invisible because that sentence was the only
per-photo text on the sheet. It now returns `nao_pertence` for a photograph that is
of somewhere else, and the tile shows both voices side by side — `viu` from the
pass that named the room, `escolheu` from the pass that picked the photograph.
When they disagree, the sheet says so in red and the run prints it.

**Near-repeats are rejected by the prompt, not by a hash.** `quase repetida` is one
of the outright rejections in `RULES.md`, and returning fewer photographs is
preferred to returning two versions of one view. The threshold route was measured
and abandoned: on `WC-00284` the tightest genuine repeat sat at Hamming 20 and the
tightest genuinely useful pair at 22, so no value of `PHASH_MAX_DISTANCE` catches
the first without swallowing the second. Telling one from the other needs eyes.

**Measurements are sent as verdicts, never as numbers.** Handed `sharpness 1/30`,
meaning rank 1 of 30, the model wrote *"nitidez muito baixa (1/10)"* and rejected
the sharpest frame in the room. Handed `lean 0.9°` it wrote *"inclinação
acentuada"*, when 0.9° is better than that photographer's median. A number means
nothing without the scale it sits on, and the scale is in `RULES.md`, which the
model never sees. So the thresholds are applied first and only `level`,
`verticals splay badly`, `FAULT: …` travel.

Blur is left to the model on purpose: the sharpness score is only comparable
between frames of the *same* subject, so it ranks within one angle and is never
quoted as a quality.

**The vision pass is optional and never fatal.** Without `--vision`, or without a
`FAL_KEY`, the sheet is built from the measurements and the quota with nothing
pre-ticked, and says so in its header. A room the model cannot judge simply
arrives empty.

### The contact sheet is the gate

One self-contained HTML file, proxies by relative path, grouped by room in the
photographer's own walkthrough order. Each room's counter turns red past its
share. HTML rather than markdown because the work is comparing and toggling, not
reading.

Opened from the disk it cannot write into the folder — a browser page can't — so
"Copiar picks" puts the list on the clipboard and you paste it into `picks.txt`.
Opened from the local server `cull.py` starts (`_config/serve.py`), 'Salvar
picks.txt' writes that same text for you, and 'Revelar o trabalho' writes it and
runs `develop.py`. **The page composes nothing either way**: both routes call
`picksText()`, so a saved file and a pasted one are the same bytes. Both sets of
buttons are always there; under `file://` only the clipboard ones appear.

**It is also where a room gets corrected**, and that is not a convenience. The
line under each photograph is the room it will be delivered as, and it is the
last place anyone looks before that name becomes a file a client receives.

Two bedrooms which photograph alike are now separated by the pass described above,
so this is the appeal rather than the only court. When it gets it wrong,
`+ novo QUARTO` gives the second room its own number, its own quota floor of
three, and its own `QUARTO_02_NNNN.jpg`; the same edit merges two it split. Your
number outranks the model's on that row for good — the pass is not asked about
that ambiente again.

The second copy button hands back the whole of `ambientes.md` with the changed
cells rewritten, to paste over the file — or 'Salvar e re-cortar' writes exactly
that text and re-runs the free pass for you, which is steps two and three of the
paragraph below in one click. Rewritten rather than composed: the
markdown format lives in `ambientes.py` and a copy of it in the page's JavaScript
would go stale the first time a column moved. `Visto` is deliberately left as it
was — the page is not a check, and the gap between the two columns is what marks
the change as yours.

Then re-run `cull.py --no-classify`. That re-groups, re-cuts the quota for the
rooms you just created, and redraws the sheet, **without paying for the naming
pass again** — it reads the answers already in the catalogue. Add `--vision` to
re-do the cheap best-of pass, which you want after a split: a bedroom of four
photographs and a bedroom of three are two different comparisons.

`selection.md` is written beside it: the picks by room, each with its reason and
scores. That file is for people — it is what makes a selection defensible to a
client and auditable later when a listing underperforms. `picks.txt` is the same
decision for the machine.

### The handoff is a name **and** a number

This stage names the photo and every stage after it leaves the name alone. Since
2026-07-31 it also mints the job — see "Next stage" for why that moved here.

`develop.py` writes `1 - edit/Job_NNNN/`, each file named `AMBIENTE_NN_NNNN.jpg`:

    SALA_01_0002.jpg      ambiente · which room of that kind · which photo

- the **ambiente** comes from `ambientes.md`, so it is the answer that was checked
  against the picture and possibly corrected by you — not re-derived here.
- the **room index** counts physical rooms of that kind in walkthrough order, so
  the first bedroom the photographer entered is `QUARTO_01`. Two bedrooms stay
  distinguishable, which a bare `QUARTO_0001…QUARTO_0006` would not.
- the **photo number** is assigned here and nowhere earlier, restarting per room
  and following `picks.txt`. It cannot be settled during naming: only once the
  picks are known is the sequence contiguous rather than full of gaps where the
  unpicked photos were.
- the **job number** is minted here, and here only. It used to be claimed
  downstream, which meant nothing linked a finished job back to the delivery it
  came from — and the archive needs exactly that link to assemble `originais/`.
  It goes into `job.md` as `**Shoot:**`.

**The trade-off, stated plainly:** names now sort by ambiente, so `AREA_SERVICO`
lands above `SALA` on disk whatever order they were shot in, and the zero-padded
`NN_` prefix that used to carry gallery order through a downstream text sort is
gone. The walkthrough order lives in `selection.md` and in `job.md`'s `#` column
instead. That order was never the delivery order once the filename grouped by
ambiente, and a sheet ordered one way with a folder ordered another helps nobody —
so `review-selection.html` groups by ambiente too.

A pick that is not in `ambientes.md` stops the run before anything is written.
Guessing would produce a file whose name claims a room nobody verified, and that
name goes to a client.

### Merging a bracket is fidelity, not polish

Send `gpt-image-2` the middle frame of a bracket and the window is a white
rectangle — so the model **invents** the view. A different building, a different
sky. That breaks the project's one rule directly. A fused bracket gives it the
view that was actually there.

`cv2.createMergeMertens()` is used rather than an HDR tone-map: it blends the
best-exposed pixels across the stack and yields a normal-looking photograph, with
nothing to tone-map afterwards and nothing that reads as "an HDR". Alignment runs
first, because even a tripod drifts and a misaligned fusion ghosts every edge.

**Untested.** No bracketed delivery has arrived yet. The detection is deliberately
conservative — it needs a timestamp *and* a varying exposure bias, and refuses to
fuse frames of different sizes — but it has never run on a real bracket. Check
two or three fused windows the first time it does.

## Editing the rules

`../_config/Seletor/RULES.md` is to this stage what `PROMPT.md` is to the enhance
stage: the one tuning surface, read fresh on every run.

**When the selection makes the same mistake twice, change that file** — not the
picks. A pick fixed by hand is wrong again on the next property.

The strategy document it was distilled from sits beside it as the source. It is
187 lines of argument and is deliberately not loaded per run.

Geometry thresholds live there too, with the percentiles that justify them.
**Re-measure when a new photographer starts sending work.** A tripod-and-shift
shooter and a run-and-gun shooter do not share a baseline, and a threshold
inherited from the wrong one is worse than none.

## Disk

A delivery is 3–15 GB and it stays until you delete it.

| | |
|---|---|
| `source/` | the camera originals. **No script deletes this on its own** |
| `developed/` | every photo nobody picked, at 2400px. ~370 MB. Written by `develop.py`, copied into the archive when the job is approved |
| `_proxies/` | 1600px, for judging. Regenerable; `develop.py --prune` clears it |
| everything else | kilobytes |

**Why the unpicked photographs are developed at all**, and at 2400px rather than
reusing the 1600px proxies that already exist: because the archive is meant to
make the camera originals deletable, and the resolution that goes into the
archive is the permanent ceiling on every future re-pick. The pipeline delivers
at 2048px. A 1600px archive copy would have been free and would have quietly
closed the door on ever promoting a discarded frame to a real deliverable.

Once a job is archived **with its `originais/`**, the raw can go:

```bash
./_config/.venv/bin/python "3 - completed/archive.py" --purge-source "0 - selection/Cobertura"
```

That is the one exception to the rule above, and it is human-run: it refuses
unless the work is safely archived, prints what it will delete, and asks you to
type the shoot's name. **Never run it on your own initiative** — it deletes
photographs. See `3 - completed/CONTEXT.md` → "Deleting the originals".

## When it stops

- **`fetch.py` refuses to hand off a short delivery.** With an `expected.txt`
  inventory in the shoot folder it names the missing files; with `--expect N` it
  reports the count. Without either it says the count is *unverified* rather than
  implying it checked — nothing in the files reveals a download that stopped
  early, because the evidence is what is absent.
- **`cull.py` will not run without `RULES.md` and its `=====` markers.** There is
  no safe default for a quota or a prompt.
- **`develop.py` writes nothing if any line of `picks.txt` names a file that is
  not in `source/`.** It lists them and exits, so a typo is fixed before half a
  drop exists.
- **A room the vision pass fails** arrives with nothing pre-ticked and is named in
  the sheet's header. The delivery is never abandoned for it.

## Next stage

`develop.py` has minted `1 - edit/Job_NNNN/`. Read `1 - edit/CONTEXT.md`.

**This is where a job is born**, and it is the only place a job number is ever
minted. Not for tidiness: this is the one moment in the whole pipeline when the
shoot's name and a fresh number exist in the same process, and the archive needs
that link three stages later to know which delivery a finished job came out of.
It is written into `job.md` as `**Shoot:**`, and `archive.py` reads it to
assemble `originais/`.

A number already used anywhere — in any of the three job folders — is a hard
stop. Two photo sets under one number is worse than a stopped run.
