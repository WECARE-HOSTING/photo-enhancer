# 2 - marca dagua — the WeCare mark

_Last updated: 2026-08-03_

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

The mark is 166×205 px on a 2048 px photo — under 1% of the frame. That does not
survive a thumbnail, so the page's primary view is a **1:1 crop of the top-left
corner** at native resolution. It is done with `object-fit:none` in CSS, not by
writing crop files: 60 extra files per job would have cost 3.6 MB in every
archive forever, and a `<stem>_crop.jpg` carries no result marker, so
`photos_in()` would have read each one as a source photograph and **sent it to
the paid API**.

Each photo shows the measurement that chose its ink. Those numbers are measured
fresh on every page write, never read out of `marca.md` — no script in this
project reads a log to decide anything.

Marking a photo sends it back; the radios force the ink. Press **Refazer as
marcadas** and the page writes `gate.txt` and runs `--rework` for you; **Re-marcar
todas** is `--rebrand`, and **Aprovar e arquivar** ends the review. Without a
server, "Copiar marcações" and a paste into `gate.txt` do the same thing — both
buttons call the same function, so the bytes are identical. Either way the marks
travel through `gate.txt` the way stage 1's comments do:

```
SALA_01_0001   # a marca preta sumiu no rodapé escuro    variant=claro
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
| `LOGO_HEIGHT_PCT` | `0.10` | mark **height** over the photo's **long edge** — 205 px at 2048 |
| `MARGIN_PCT` | `0.03` | inset from top and left — 61 px |
| `OPACITY` | `0.85` | of the art |
| `MIN_CONTRAST` | `4.0` | below this the glow comes on — unreachable with this art |
| `BUSY_STD` | `0.18` | background spread that counts as busy |
| `GLOW_RADIUS_PCT` / `GLOW_OPACITY` | `0.35` / `0.45` | halo size and strength |
| `JPEG_QUALITY` / `JPEG_SUBSAMPLING` | `95` / `0` | 4:4:4 — the mark is the frame's one hard edge |

**By height, and over the long edge.** The lockup is **stacked** — pin over
`wecare. HOSTING`, taller than it is wide — so the constant that matters is its
height; sizing a stacked mark by its width makes it tower over the room. And over
the long edge, not the photo's own height, because by height a portrait photo
would get a mark 33% bigger than a landscape one in the same gallery. It is
205 px tall in both, since everything here is 2048 px on its long side.

## How the ink is chosen

Measured on the exact rectangle the art will cover, weighted by the art's own
alpha — only the pixels the strokes land on count, not the gaps between them.

1. Alpha-weighted WCAG relative luminance of that patch → `L`.
2. Contrast against each ink; the higher wins.
3. If even the winner is under `MIN_CONTRAST`, or the patch is busier than
   `BUSY_STD`, a soft glow goes underneath: the art's own alpha, gaussian
   blurred, in the opposite tone. **A halo that follows the letterforms — never
   a box or a band**, which would wreck the photograph.

Measured over 278 real photographs (the whole archive plus Job_0023) at this mark
size: **75% preta · 25% branca · glow on 21% · worst contrast 4.61:1 · median
9.34:1.**

**Step 2 can no longer fail, and that is a property of the art.** Pure black and
pure white sit at the two ends of the luminance scale, so the worst background
imaginable is the one where they tie — and even there the winner is 4.58:1.
`MIN_CONTRAST = 4.0` is therefore unreachable: with this art the glow is decided
by `BUSY_STD` alone. The constant stays because it is the floor a future
non-extreme colourway would need, and it is the number the page prints.

`BUSY_STD` was measured, not guessed, and it moves with the size: at `0.08` the
glow fires on 13% of photographs, at `0.10` on 21%, at `0.14` on 28% — a bigger
mark samples a bigger patch. **Re-measure when you change the size**; running
`marca.py` over `3 - completed/` costs nothing.

The one case no threshold catches is a mark that **straddles an edge** — half on a
dark headboard, half on a light ceiling reads as a low spread over a mid
luminance, and one half of the lockup goes quiet. That is what `glow=on` at the
gate is for.

## The art

`_config/logos/logo preto.png` and `_config/logos/logo branco.png` — the stacked
lockup, pin over `wecare. HOSTING`, 1301×1606 with one ink and nothing else in it.

| | |
|---|---|
| **`claro` and `escuro` name the ink, not the background** | Black `#000000` goes on a **light** wall; white `#FFFFFF` goes on a **dark** room. Reading these backwards is the obvious mistake |
| One ink, no third colour | The previous art was navy and cream, both carrying a mid-tone gold `#B79152` that lost force in warm light — the fragile part every threshold was built around. A single pure ink has no such part, which is why the contrast floor stopped mattering. **Do not put a third colour back into the PNGs without re-measuring** |
| The two exports do not crop alike | The white one carries 29 px more above the pin, so the aspects differ by 1.8%. `geometry()` runs **per art**, not once for the pair — deriving the width from the black one and painting the white one into it stretched it by that much. Same height, same corner, a couple of pixels narrower |
| One mask measures both | The patch is read through the black art's alpha whichever ink wins. Their coverage differs by 0.5%, far under anything the decision turns on, and measuring twice would only let two answers disagree about one patch |
| The PNGs carry transparent padding | 342 px left, 79 top, on a 2000×2000 canvas. `Logo` crops to the alpha bbox first — sizing by the canvas would render a third of the asked-for art and put the margin somewhere other than where the constant says |

**Replacing the art:** same two filenames, transparent PNG, at least 600 px on its
long side. The next run re-marks everything by mtime.

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
