Image 1 is image 2 after a professional real estate listing enhancement. Everything that enhancement achieved stays. Image 2 is the original camera photograph of the same room, before editing — reference only, for recovering how a detail really looked. Apply the following instruction to image 1:

===== END OF PROMPT — everything below is NOT sent to the model =====

## What this file is

The **only** thing this phase adds to what the human wrote. Their sentence is
appended below this text, verbatim, and nothing else is sent — no rules, no
preservation language, no `1 - edicao/PROMPT.md`.

That is the whole design. The human looked at the result and is allowed to ask for
what phase 1 forbids: put the person back, shift the angle, stretch a side. A rule
from phase 1 arriving in the same string would outrank their sentence, because
absolute-sounding preservation language always does — that failure is documented at
length in `../1 - edicao/CONTEXT.md` → "When an instruction is being ignored".

## Why these three sentences exist at all

They are addressing, not policy. The model receives two images and cannot know
which is which, or that the differences between them were deliberate.

Without the first sentence, the model reads image 2 as the truth and image 1 as
something to correct back toward it: it returns the resident's clutter that phase 1
removed, re-darkens the exposure phase 1 balanced, unmakes the bed. It is not
disobeying — it has no way to tell a deliberate edit from a defect.

Without the second, the original is just a second reference to blend, and detail
from it bleeds into a result that was supposed to keep image 1's look.

**Keep it short.** Every sentence here competes with the human's own, and theirs is
the one that matters. If a retouch keeps going wrong in the same way, the fix is
usually a clearer sentence in the box — not more text in this file.

## fal.ai request settings

Read from `../../_config/fal.py`, shared with phase 1. Two differences, both forced
by `retoque.py` rather than by a constant:

| Setting | Value | Why |
|---|---|---|
| `image_urls` | `[the _edit, the original]` | in that order — the frame above names them "image 1" and "image 2" |
| `num_images` | always `1` | a retouch answers one instruction; variants are a phase-1 tuning tool |
| `image_size` | the `_edit`'s own dimensions | already ~2K at the source's ratio, so a retouch never changes the frame's proportion |

**The marker line above is load-bearing.** `retoque.py` splits on
`===== END OF PROMPT` and sends only what precedes it. If you edit this file, leave
that line in place — the script fails loudly rather than sending these notes to the
model as prompt text.
