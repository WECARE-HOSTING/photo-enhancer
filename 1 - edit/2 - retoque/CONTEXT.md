# 2 — Retoque · fase 3 do estágio de edição

_Last updated: 2026-08-01_

**One photo, one sentence, no rules.** This is what runs when you tick a photo on
`review-edit.html` and write in the box. What you wrote is the entire prompt — the
phase-1 `PROMPT.md` is not read at all — and it is applied to **the edit you were
looking at**, not to the original.

That is the whole design, and it is deliberate at every point. You looked at the
result. You are allowed to ask for what phase 1 forbids: put the person back, shift
the angle, stretch a side. A rule from phase 1 arriving in the same string would
outrank your sentence, because absolute-sounding preservation language always does
— documented at length in `../1 - edicao/CONTEXT.md` → "When an instruction is being
ignored, look for the conflict".

**Input:** a source photo, its `_edit.jpg`, and one sentence a human wrote
**Process:** the `_edit` + the original + that sentence → fal.ai, once
**Output:** the `_edit.jpg` overwritten, the previous one shelved as `_edit_rN.jpg`, and a `## Retoque N` block appended to `<name>_log.md`

```bash
# the normal way in — reads the sentences out of gate.txt
./_config/.venv/bin/python "1 - edit/batch.py" --rework

# one photo by hand, for trying something
./_config/.venv/bin/python "1 - edit/2 - retoque/retoque.py" \
    "1 - edit/Job_0023/SALA_01_0001.jpg" "põe a pessoa da janela de volta"
```

## The two images, and why the original comes along

`openai/gpt-image-2/edit` takes `image_urls` as an **array of up to 16 images**
("images to use as a reference for the generation"), so both go in one request:

| | What | Why |
|---|---|---|
| image 1 | the `_edit.jpg` | the photograph being edited — the one the human judged and wrote about |
| image 2 | the original | reference only, for recovering how a detail really looked |

The original earns its place because your sentence is often *about* something the
original had: "a pessoa da janela sumiu, devolve ela" is unanswerable without a
picture of that person. Without image 2, the model invents one.

**The original is not uploaded again.** Phase 1 already put it on fal's CDN and
recorded the URL in `<name>_log.md`, on the line `| Uploaded source | … |`. This
phase reads it back, confirms with a `HEAD` that it still serves (~200ms against a
~4s upload), and reuses it. Only if the URL is missing or dead does it upload the
file, and the log block says which of the two happened.

**Order is a contract with `PROMPT.md`.** The frame text calls them "image 1" and
"image 2"; swap them in the payload and it describes the wrong picture, which is
worse than sending no frame at all.

## Why `PROMPT.md` here is only three sentences

They are addressing, not policy. The model gets two images and cannot know which is
which, or that the differences between them were on purpose.

Without them it reads image 2 as the truth and image 1 as something to correct back
toward it: the resident's clutter phase 1 removed comes back, the exposure phase 1
balanced re-darkens, the bed unmakes. It is not disobeying — it has no way to tell a
deliberate edit from a defect.

**Keep it short.** Every sentence there competes with the human's own, and theirs is
the one that matters. If retouches keep going wrong the same way, the fix is usually
a clearer sentence in the box, not more text in that file.

## What it will not do

**It cannot widen the frame.** `image_size` is taken from the `_edit`'s own
dimensions, so "expande o lado direito" makes the model *recompose inside the same
rectangle* — more of the right, less of the left — rather than growing the canvas.
Widening for real would need a `ratio=16:9` token in the comment and a new grammar
in `../../_config/gate.py`; `OPT_RE` and `fal.RATIOS` already exist, so it is about
ten lines when it is actually wanted. It was left out so the core change could be
tested clean.

**It refuses a photo ticked with an empty box**, naming which, before anything is
recorded in `gate.md` and before anything is spent. Phase 3 *is* the sentence. If
what you want is another draw from the fixed prompt, that is `--redo` — phase 1
again, from the original.

## Nothing here is deleted, and that is the exception in this project

Everywhere else, **rejecting a photo means deleting its result** and letting the
skip rule re-run it — `_config/stage.py` explains why that is the best idea in the
codebase. Phase 3 cannot work that way:

- the `_edit.jpg` **is the input**, so deleting it destroys what the run needs;
- the `_log.md` carries the original's CDN URL, so deleting it costs an upload.

So `batch.py --rework` passes an explicit list of stems instead of leaning on the
skip rule, and the previous edit is **shelved, not dropped**:

```
SALA_01_0001.jpg           the original, never touched
SALA_01_0001_edit.jpg      the current one   (retoque 2)
SALA_01_0001_edit_r1.jpg   what phase 1 made
SALA_01_0001_edit_r2.jpg   what retoque 1 made
SALA_01_0001_log.md        all three passes, in order
```

A retouch that fixes what you asked and breaks something else costs a **rename** to
undo, not another paid run. `_edit_rN` never collides with `_edit_1`, which is what
`NUM_IMAGES > 1` writes and what `result_of()` looks for; stages 2 and 3 ignore the
shelved files entirely, because `photos_in()` excludes any name containing `_edit`.

**`--approve` discards them**, saying how many. They exist so you can choose between
rounds; once the job has moved there is nothing left to choose, and `3 - completed/`
would otherwise fill with 2K images nobody opens. What happened stays in `gate.md`
and in each `_log.md`.

## The log is appended to, never rewritten

Phase 1 writes the header — source, model, prompt fingerprint, and the CDN URL — and
every retouch adds a `## Retoque N` block below it, numbered by counting the blocks
already there rather than from any state file. One file per photograph, the honest
order of what was asked of it and when.

This is why the log stopped being only a record: **it is now an input.** Change the
wording of `| Uploaded source | … |` in `../1 - edicao/enhance.py` and this phase
quietly starts uploading the original a second time on every retouch — it still
works, just slower, which is the kind of breakage nobody notices. Both sides name
the constant (`SOURCE_URL_LABEL`, `SOURCE_URL_RE`) and `_dependencies.md` records
the edge.

**And the block below it has a second reader too.** `history()`, in this folder's
`retoque.py`, reads every `## Retoque N` heading and its `| Instrução humana |`
and `| Edit anterior |` rows back out, so `review-edit.html` can show you what
you asked next to what came back. Nothing *decides* anything from it — the page
draws, and a log that has been hand-edited costs that photograph its history and
nothing else — but the row labels are now a contract. Rename one here and rename
it in `history()` in the same commit.

The instruction goes through `ledger.cell()` on the way in, the way `gate.md`'s
does: a `|` typed inside a sentence would end the row early, and a sentence
truncated at the first pipe is exactly what would appear on the page. The `Prompt
as sent` fence below it is untouched and stays verbatim — that is the record of
what the model actually received.

## Config

Everything tunable is in `../../_config/fal.py`, shared with phase 1 — model,
quality, target size, timeouts. Two things this phase forces regardless:

| | Value | Why |
|---|---|---|
| `num_images` | always `1` | a retouch answers one instruction; variants are a phase-1 tuning tool |
| `image_size` | the `_edit`'s dimensions | already ~2K at the source's ratio, so the proportion never drifts across rounds |

**Resolution does not degrade between rounds.** Every request carries an explicit
`image_size`, so each pass comes back at ~2K whatever went in. What *does* soften
slightly is texture: round 2's input is already a model rendering. That is the price
of editing the new photograph instead of re-rolling the original, and it is the
right trade — re-rolling throws away everything phase 1 got right.
