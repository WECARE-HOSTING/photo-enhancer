# 2 - marca dagua — the WeCare mark

_Last updated: 2026-07-31_

**Input:** a `Job_NNNN/` approved at the edit gate, every photo carrying its
`_edit.jpg`
**Process:** compose the WeCare mark into the top-left corner of each one,
locally, choosing the ink per photo so it stays legible
**Output:** `<name>_final.jpg` — **the deliverable** — plus one `marca.md` for
the job, and a stop at `review-marca.html`

**Nothing here calls an API and nothing here costs money.** That single fact
shapes the whole stage: being wrong is cheap, so the tuning loop is
`--rebrand`, not a careful first attempt.

---

## Running it

```bash
./_config/.venv/bin/python "2 - marca dagua/batch.py"            # mark what needs it
./_config/.venv/bin/python "2 - marca dagua/batch.py" --rebrand  # redo all — free
./_config/.venv/bin/python "2 - marca dagua/batch.py" --rework   # redo what you marked
./_config/.venv/bin/python "2 - marca dagua/batch.py" --approve  # -> 3 - completed/

./_config/.venv/bin/python "2 - marca dagua/marca.py" "<some>_edit.jpg" --out /tmp
```

The last one is the tuning bench: one photo, anywhere on disk — including an
archived one — written wherever you point it. `--variant claro|escuro` forces
the ink so you can see both.

Serial, not threaded. Stage 1 wants four photos in flight because it is waiting
on a network; this is Pillow on the CPU, where threads buy nothing and only make
the output interleave. Sixty photos take about twenty seconds.

## When a photo gets re-marked

Missing `_final`, a `_final` older than its `_edit`, or a `_final` older than the
logo file itself. That last one matters: **drop a new PNG into `_config/logos/`
and the next run re-marks the whole job**, without anyone having to remember to
ask for it.

## The gate

`review-marca.html` asks one question the other two pages cannot: *is the mark
legible where it landed?*

The mark is 295×56 px on a 2048 px photo — 2% of the frame. That does not
survive a thumbnail, so the page's primary view is a **1:1 crop of the top-left
corner** at native resolution. It is done with `object-fit:none` in CSS, not by
writing crop files: 60 extra files per job would have cost 3.6 MB in every
archive forever, and a `<stem>_crop.jpg` carries no result marker, so
`photos_in()` would have read each one as a source photograph and **sent it to
the paid API**.

Each photo shows the measurement that chose its ink. Those numbers are measured
fresh on every page write, never read out of `marca.md` — no script in this
project reads a log to decide anything.

Marking a photo sends it back; the radios force the ink. Both travel through
`gate.txt` the same way stage 1's comments do:

```
SALA_01_0001   # o navy sumiu no rodapé claro    variant=claro
```

An override applies to that run. **It is not remembered anywhere**, and it does
not need to be: the `_final.jpg` on disk already carries it. A file that stored
the override would be a second source of truth able to disagree with the image.

## Tuning the mark

Every number is a constant at the top of `marca.py`. Change one, run
`--rebrand`, look. There is no `MARCA.md` and there should not be: `PROMPT.md`
exists because it is 2.7 KB of prose edited weekly, and this is six numbers.

| Constant | Now | What it does |
|---|---|---|
| `LOGO_WIDTH_PCT` | `0.144` | mark width over the photo's **long edge** — 295 px at 2048 |
| `MARGIN_PCT` | `0.03` | inset from top and left — 61 px |
| `OPACITY` | `0.85` | of the art |
| `MIN_CONTRAST` | `4.0` | below this the glow comes on |
| `BUSY_STD` | `0.18` | background spread that counts as busy |
| `GLOW_RADIUS_PCT` / `GLOW_OPACITY` | `0.35` / `0.45` | halo size and strength |
| `JPEG_QUALITY` / `JPEG_SUBSAMPLING` | `95` / `0` | 4:4:4 — chroma subsampling smears the gold against the navy |

**Scaled by the long edge, not the width.** By width, a portrait photo would get
a mark 33% smaller than a landscape one in the same gallery. By long edge it is
295×56 in both, because everything here is 2048 px on its long side.

## How the ink is chosen

Measured on the exact rectangle the art will cover, weighted by the art's own
alpha — only the pixels the strokes land on count, not the gaps between them.

1. Alpha-weighted WCAG relative luminance of that patch → `L`.
2. Contrast against each ink; the higher wins.
3. If even the winner is under `MIN_CONTRAST`, or the patch is busier than
   `BUSY_STD`, a soft glow goes underneath: the art's own alpha, gaussian
   blurred, in the opposite tone. **A halo that follows the letterforms — never
   a box or a band**, which would wreck the photograph.

Calibrated against the 174 archived photographs: **68% navy · 31% cream · glow
on 32% · worst contrast 3.37:1 · median 6.02:1.**

Both thresholds were measured, not guessed, and the guesses were wrong in both
directions: `3.0` would never have fired at all (the worst real case is 3.37:1)
and `0.10` fired on 43% of photographs. If you change them, re-measure — running
`marca.py` over `3 - completed/` costs nothing.

## The art

`_config/logos/wecare-hosting-horizontal-{escuro,claro}.png`.

| | |
|---|---|
| **`claro` and `escuro` name the ink, not the background** | The navy `#0C2330` goes on a **light** wall; the cream `#F2EAD9` goes on a **dark** room. Reading these backwards is the obvious mistake |
| Both share one alpha geometry | Same bbox, same coverage. One mask, two inks, which is what makes the glow simple |
| The PNGs carry transparent padding | 52 px left, 55 px top, and the two lockups pad differently. `Logo` crops to the alpha bbox first — sizing by the canvas would render 5% less art and put the margin somewhere other than where the constant says |
| The gold `#B79152` is the fragile part | It is in both colourways and is a mid-tone, so in warm light it loses force while the navy or cream carries the mark. If it starts disappearing, raise `MIN_CONTRAST` — do not change the algorithm |
| The empilhado lockup and the SVGs are unused | Kept in the folder, read by nothing. Measured, the choice between lockups was pure taste: the glow rate follows the **area** the art covers, not its shape |

**Replacing the art:** same two filenames, transparent PNG, at least 600 px
wide. The next run re-marks everything by mtime.

## Why the mark is composed here and not asked of the model

`PROMPT.md` forbids adding anything to a room, and — separately — **naming a
watermark in a prompt trips fal's content policy**: the request is rejected
before it reaches the model, so no charge and no image. `1 - edit/CONTEXT.md`
records the measurement. Local compositing is the only route compatible with the
stage contract, and `PROMPT.md` must never learn that this stage exists.

## Not grading

This stage reads pixels — luminance, contrast, spread. That is **measurement**,
and it is how the ink gets chosen. The project's rule that nothing opens a
result to judge it is about *who decides whether a photograph is good*, and that
is still only ever the person at the gate page.

## Next stage

`3 - completed/` — see its `CONTEXT.md`. `--approve` assembles `originais/`
before it moves the folder, because once the job is archived the process that
knew which shoot it came from has exited.
