# 1 — Edição · fase 1 do estágio de edição

_Last updated: 2026-08-01_

**One prompt, every photo.** This is the phase that turns a job's sources into
`_edit.jpg` files: `PROMPT.md` is the only tuning surface, and it tells the model
what to preserve, fix, remove and tidy. `enhance.py` sends it and the source photo
to fal.ai together and lets the model read the image itself. Nothing here looks at
a photo or writes a per-photo prompt.

**What lives here is the phase's tooling, not the work.** A `Job_NNNN/` stays whole
one folder up, in `1 - edit/`, with its source, its `_edit` and its `_log` side by
side — this folder only holds the prompt and the script that sends it.

**Input:** a source photo, by path, from `1 - edit/batch.py` (or from the CLI below)
**Process:** `PROMPT.md` + that photo to fal.ai, once, with no per-photo variation
**Output:** `<name>_edit.jpg` and `<name>_log.md` written beside the source

```bash
# the whole job — this is the normal way in
./_config/.venv/bin/python "1 - edit/batch.py"

# one photo, by path — for tuning, not for jobs
./_config/.venv/bin/python "1 - edit/1 - edicao/enhance.py" "1 - edit/Job_0023/SALA_01_0001.jpg"

# audit the prompt for self-contradictions — free, instant, no photo
./_config/.venv/bin/python "1 - edit/1 - edicao/enhance.py" --check
```

The folder names have spaces in them — **quote every path**.

## What this phase is not

**It never takes a per-photo instruction.** When you send a photo back at the gate
with a comment, `../2 - retoque/` runs it — and that phase does not read `PROMPT.md`
at all, because the comment exists precisely to override rules written here.

That split is the point. A rule added to `PROMPT.md` applies to **every future
photo**; a gate comment applies to **exactly one**. So when the same complaint comes
back twice, the fix belongs here, not in another comment — the retouch fixes one
photo, this file fixes the rest of them forever.

**A re-run overwrites the `_edit` and rewrites the log from scratch.** One photo has
one current edit. (A retouch does the opposite: it *appends* to the log and shelves
the previous edit as `_edit_rN.jpg`. See `../2 - retoque/CONTEXT.md`.)

**The journey is not here either.** Prepare, upload, submit, download and every
setting that governs them live in `../../_config/fal.py`, shared with phase 3.
What stays in `enhance.py` is what is only true of this phase: reading `PROMPT.md`,
fingerprinting it, `--check`, and the log it writes.

---

## Config — edit to change model/behavior

Everything tunable is a constant at the top of `../../_config/fal.py` (or
`../batch.py` for `WORKERS`) — edit the constant, no flags to remember. **They are
shared with phase 3**, so a change here lands on the retouch too:

| Constant | Default | What it does |
|---|---|---|
| `DEFAULT_MODEL` | `openai/gpt-image-2/edit` | Which fal.ai model handles the edit |
| `QUALITY` | `medium` | gpt-image-2 only: `auto` / `low` / `medium` / `high` |
| `TARGET_LONG_EDGE` | `2048` | gpt-image-2 only: output long edge in px (2048 ≈ "2K") |
| `UPLOAD_LONG_EDGE` | `2048` | Downscale the source to this before upload. `None` uploads originals |
| `UPLOAD_JPEG_QUALITY` | `92` | JPEG quality of that downscaled upload |
| `DOWNLOAD_TIMEOUT` | `120` | Seconds per download attempt, then retry (3 attempts) |
| `RESOLUTION` | `2K` | nano-banana family only: `1K` / `2K` / `4K` |
| `SEED` | `None` | nano-banana family only: set an int to reuse a seed |
| `NUM_IMAGES` | `1` | Variants to generate per run |
| `WORKERS` (`batch.py`) | `4` | Photos in flight at once; `--workers N` overrides |

`--model` on the command line overrides `DEFAULT_MODEL` for a one-off run,
e.g. to try `fal-ai/nano-banana-pro/edit` on a photo that's giving gpt-image-2
trouble. `enhance.py` branches its request payload on whether the model name
contains `"gpt-image"`, since the two families take different fields
(`image_size`+`quality` vs `aspect_ratio`+`resolution`; only the nano-banana
family has a `seed`). Confirm a new model's schema at
`https://fal.ai/models/{model-id}/api` before pointing at it — field names
vary, and pricing does too.

**Why `openai/gpt-image-2/edit` is the default** — strong instruction-following
on text and fine detail (signage, labels) alongside the object-relationship
understanding needed to hold composition, depth, and lighting while changing
only what it's told.

Alternatives, only with a reason:

| Model | Use when |
|---|---|
| `fal-ai/nano-banana-pro/edit` | gpt-image-2 drifts on a specific photo, or you need true multi-reference-image input |
| `fal-ai/nano-banana-2/edit` | Cheaper bulk passes where fidelity can slip slightly |
| `bytedance/seedream/v5/pro/edit` | A region-precise edit that gpt-image-2 keeps smearing |
| `fal-ai/flux-2-pro/edit` | Two other models have drifted on the same photo |

Cost for gpt-image-2 isn't estimated anywhere in this pipeline — fal prices
it by quality tier *and* pixel count (bigger image, higher price,
non-linearly), not a flat per-resolution rate, so any estimate was only ever
a ballpark. Check fal's dashboard for actual spend.

---

## Editing PROMPT.md

### What actually controls quality is nouns, not length (2026-07-26)

Four revisions were tested on `007`, 3 variants each, cutting 10.5K → 1.5K.
**The winner is the shortest one** (`#8692b566`, 1,495 chars, clean 3 of 3 —
the best result of the session). But the path there is the lesson, because the
1.2K attempt in between was the worst prompt yet:

| Revision | Chars | Result on `007` (3 variants) |
|---|---|---|
| `#f0a610f3` | 2,566 | Clean except empty racks survived 3/3 |
| `#46c80d89` | 1,243 | **4 regressions** — see below |
| `#36a2e252` | 1,429 | Those 4 fixed, but blender *removed* 2/3 |
| `#8692b566` | 1,495 | Staging clean 3/3, but pull-back barely fired |
| `#42b50be1` | 1,771 | Pull-back restored — but invented a left-edge door 3/3 |
| `#916f4572` | 1,981 | Staging clean 3/3, framing excellent 3/3, left-edge door 2/3 — but relit a night photo as day |
| `#66a66d46` | 1,956 | Night held on the pool photo; hour lock added while getting shorter |
| `#4cec3414` | **1,990** | **Current.** Pull-back permission removed entirely — the frame is now fixed (see below) |

Cutting 2.6K → 1.2K by rewriting the enumerations as principles broke four
things at once. In every case a general rule replaced a concrete noun:

| Noun removed | Principle that replaced it | What happened |
|---|---|---|
| "every towel/cloth/bag left on the floor" | "whatever belongs to the resident" | Floor towel kept and *tidied into a mat*, 2 of 3 |
| "empty rack, dispenser, holder" | (nothing) | Racks survived 3 of 3 |
| "Daytime: maximize natural light" | (nothing; only the night clause kept) | A ceramic vase rendered **glowing like a lit lamp** in a daytime photo |
| "every cord end to end, device left in place" | "cords gone but devices in place" | Blender cord visible 2 of 3 |

Restoring just those nouns (+186 chars) fixed all four — but then the blender
itself vanished 2 of 3, because the *keep* side had been compressed to "keep
whatever shows what the property offers" with no noun in it either, while the
remove side had a six-item list. Adding "the appliances and equipment that
prove it is provisioned stay" (+66 chars) balanced it and produced the clean
3/3.

**The pull-back confirmed the same lesson twice more** — history now, since the
pull-back was cut on 2026-07-27; what survives is the lesson about nouns.
Compressed to a
conditional ("pull back to un-clip anything the edges cut") it barely fired at
all — framing came back at nearly the source crop. Rewritten as a *default*
("pull the camera back — wider is the default, not a fallback", plus "check the
top edge hardest") it fired hard: the clipped tapestry came back whole, with
wall above it, in 3 of 3 — a thing that was previously a coin flip across twelve
runs. But it also invented a wooden left-edge door in 3 of 3, and one variant
grew a beamed ceiling. Restoring the old prompt's explicit noun ban ("no door,
doorway, arch, window, beam, cabinet, shelf, rug, or picture appears there")
cut that to 2 of 3 — better, not solved. Both halves of the framing rule needed
their concrete form back, and the ban needs the *nouns*, not just "never a new
opening or object."

### The pull-back is gone — the frame is fixed (2026-07-27)

**Decided after reviewing a batch run under `#66a66d46`: widening kept
manufacturing space and shapes the room never had.** That is the project's one
rule broken, so the permission was cut rather than tuned again — exactly the
escape hatch the geometry note below had reserved. `#4cec3414` replaces the
whole pull-back paragraph with a fixed-frame one: same crop, same vantage, same
focal length, every border on the same content as the source, and **anything the
source clips at a border stays clipped** — half a lamp stays half a lamp,
"completing it is an error."

The ban nouns stayed (door, doorway, arch, window, beam, cabinet, shelf, rug,
picture) but are now scoped to the whole image instead of to a margin that no
longer exists. Both directions are stated, because forbidding only widening
invites the opposite: no zoom out **and** no crop in or concealment.

What this buys: the invent-a-room failure loses its opportunity — there is no
synthesized area to fill, so the ~1-in-3 margin-invention rate and the
coin-flip top edge both stop being live risks. What it costs: a photo shot too
tight ships too tight. **That is now the client's crop, not ours** — if a frame
is unusably tight, the fix is a new source photo, not a prompt that regenerates
the missing space. Framing is no longer something this pipeline improves.

**So: a principle is not a substitute for the instance it must catch, and both
sides of a judgment call need equal concreteness.** "Whatever belongs to the
resident" is a correct rule the model does not resolve to "that towel." Cut
prose freely — explanation, rationale, restatement, and the model's own defaults
are all dead weight — but every hard-won behavior needs its noun to survive, and
if you name six things to remove, name what to keep too. Length is a symptom;
noun coverage is the variable.

**Rewritten 2026-07-26 to ~2.0K chars** in the
Change → Preserve → Constraints structure that OpenAI's cookbook and fal.ai's
GPT Image 2 guide recommend for edit prompts — every practitioner source puts
fidelity-preserving edit prompts at a few hundred words, and gpt-image-2's edit
endpoint is high input-fidelity by default, so most of the old preservation
prose was defending against a failure mode the model already suppresses. The
full 10.5K predecessor is kept verbatim at `PROMPT_backup_2026-07-26_v1.md`,
and the 2.6K intermediate at `PROMPT_backup_2026-07-26_v2_5915027c.md`, either
of which can be copied back over `PROMPT.md` to roll
back. Deliberately dropped: the Optical rendering
section, composition-grid theory, per-room subsections, and the
bookshelf/screens/mirror micro-rules. If one of those behaviors visibly
regresses, re-add it as a single condensed line — not the old prose block.

**`PROMPT.md` is expected to keep changing — that's the whole point of the
file, and the system is built for it.** It is re-read from disk on every
single photo, so an edit lands on the next photo without restarting anything
(including mid-batch). You never need to touch the Python to change how photos
come out.

**Re-running a photo in this phase overwrites the previous result** —
`<name>_edit.jpg` and `<name>_log.md` both, whichever route you came by (`batch.py`,
`--redo`, or `enhance.py` on the path directly). One photo has one current edit, and
a fresh phase-1 run is a fresh start.

**`--rework` is not one of those routes.** A retouch edits the `_edit.jpg` rather
than replacing it, so it *appends* to the log and shelves the old edit as
`_edit_rN.jpg` instead of overwriting either. See `../2 - retoque/CONTEXT.md`.

Until 2026-07-31 a re-run with a changed prompt wrote a second file tagged with
the prompt's fingerprint, so the two could be judged side by side. That was
deliberately dropped for a folder that stays readable. What survives of it is the
fingerprint inside each `_log.md`, which still answers *which wording produced the
file I am looking at* — and if you want two prompts compared deliberately rather
than accidentally, copy one photo somewhere else and run `enhance.py` on it twice,
which is a better experiment anyway because you choose the photo.

Re-running a job that has already been approved and archived means working in
`3 - completed/Job_NNNN/` with `enhance.py` directly, or moving the folder back
here first.

**The prompt is verified to reach the model in full.** `openai/gpt-image-2/edit`
declares `maxLength: 32000` for `prompt`; ours is ~2.0K, so nothing is
truncated. Confirmed empirically on 2026-07-26 by appending a "render in
grayscale" sentinel as the very last line of a 7.1K-char prompt — the output
came back fully grayscale, proving the tail is read and obeyed. **So when an
instruction is ignored, delivery is not the cause.** Look for a conflicting
instruction earlier in the prompt instead — that is what actually happens (see
the two examples below).

**Run the conflict check after every prompt edit.** Free, instant, no photo:

```bash
./_config/.venv/bin/python "1 - edit/1 - edicao/enhance.py" --check
```

It reports length against the API limit, confirms the marker, and lists every
object named in **both** a removal instruction and a keep instruction, printing
both sentences so you can judge each in a second. Most pairs it surfaces are
deliberate (bathroom towels stay, floor towels go) — the point is that a real
conflict becomes impossible to miss. This is the single highest-value habit
when editing the prompt, because contradiction is the failure mode that has
cost the most money here: five occurrences, every one invisible in the text and
only discoverable in a generated image. Validated against the real kettle bug —
it flags it when present and stays quiet when fixed.

Three things make editing safe:

- **Every log carries a prompt fingerprint** — `#66af6734`, the first 8 hex of
  the prompt's SHA-256 — plus the full prompt text as sent. Two photos with
  the same fingerprint got byte-identical instructions; two that differ did
  not. This is what makes "did that edit actually help?" answerable a week
  later instead of a guess.
- **The `===== END OF PROMPT` marker is load-bearing.** Everything above it is
  sent verbatim; everything below (the settings table) is reference only. If an
  edit deletes the marker, `enhance.py` fails loudly rather than shipping the
  settings table to the model as prompt text.
- **A gutted prompt fails too.** Under 100 characters above the marker is
  treated as a bad edit, not a prompt.

Things to keep in mind when you edit the prompt itself:

- **No negative-prompt field exists** on any of these models. Every "don't"
  has to be carried by a positive instruction — "keep the window frame
  rectangular" rather than "don't distort the window."
- **Never ask it to remove a watermark.** That clause alone triggers fal's
  content-policy rejection (`content_policy_violation`) and the request never
  reaches the model — no charge, but no image either.
- **Nothing may be added to a room.** The prompt currently allows *zero* new
  props: staging works only with what is already in the frame. If you ever
  loosen that, state an explicit ceiling in the prompt, because the model has
  no per-photo analysis telling it when a room is bare enough to justify it.
- **The governing staging principle is a question, not a list** (decided
  2026-07-26): *does this tell someone considering this property something worth
  knowing about it?* Keep what demonstrates a **feature**, remove what
  demonstrates a **resident**. A blender stays — cleaned, squared, cord hidden —
  because it tells a guest the kitchen is equipped; shoes by the door go.
  Tidying is the default action, removal the exception. Everything downstream
  (counters, floors, rooms, people, vehicles) is an application of that one
  test, so **if you change the test, re-read all of them.** Note this reversed
  the earlier "remove all small appliances" rule — an equipped kitchen
  photographed well beats a bare one.
- **Geometry: latitude is back, and this is the one to watch.** `PROMPT.md` as
  it stands says *"Reframe for composition from the same vantage, keeping
  everything the source shows. Widened margins continue the surfaces already
  meeting that edge, in the same material"* and asks for Rule of Thirds,
  symmetry, level horizon and headroom. The vantage is still fixed and nothing
  may be cropped away — but the frame may be widened, which means canvas that
  was never photographed.

  **This reverses the 2026-07-27 rule**, which was "no pull-back, no added
  canvas" and which existed because a wider establishing frame had paid for
  itself in invented architecture — see "The pull-back is gone" above, which is
  now history rather than current policy. Read that section before loosening
  this any further: the failure it records is real, and the guard against it now
  rests entirely on *"Widened margins continue the surfaces already meeting that
  edge"* rather than on refusing to widen at all.
- **An object clipped at a border stays clipped — that is the prompt working.**
  A half-visible tapestry, chair leg, or cabinet coming back still half-visible
  is correct. Restoring it would mean generating room that was never
  photographed, which is the one thing this project forbids.
- **What a window shows is fixed content (2026-08-04).** The model kept painting
  sky, trees and gardens into panes the source never photographed — the project's
  one rule broken, and on the attribute that sells a property. `PROMPT.md` now
  caps it: what the glass shows in the source is all it ever shows, a shape
  behind a pane may only lose its colour cast and haze, a blown-out pane keeps
  its flat bright wash, and **doubt resolves to that wash, never to a view** —
  the same stated-fallback shape the frame margin needed. The ban carries its
  nouns (sky, cloud, sun, horizon, tree, garden, lawn, hill, mountain, beach,
  ocean, pool, street, car, building, city view), because a nounless ban has
  never held here. Two other lines were the actual doors in: `bracketed HDR
  merge` is *the* technique that reveals a window view, so it is now scoped to
  the interior, and the reflection rule is scoped to opaque surfaces — stripping
  the reflection off glass opens a void the model fills with landscape. If you
  ever loosen one of the three, expect the invented view back.
- **Planting is settled as intended behavior (2026-07-26), so don't "fix" it.**
  Planting already in frame renders green and healthy, bounded by layout —
  nothing planted that wasn't there, and one ground surface never becomes
  another (bare earth stays bare earth, gravel stays gravel).
- **People and vehicles are no longer the model's call.** `PROMPT.md` now keeps
  every one of them — *"every person, hand, arm and sleeve already in the source
  stays — same position, same pose, same clothing, never erased or replaced by
  empty surface"* — plus an explicit anatomy instruction for hands. The earlier
  policy let the model decide per photo and erase a figure it could not render
  cleanly; that judgement is gone, so a badly-rendered person now comes back in
  the photograph rather than being removed from it. That is what the gate is for.
- Avoid words like *dramatic, cinematic, moody, HDR-crunched* — they push
  toward a look buyers read as manipulated, not enhanced.

### Judging a prompt edit: one image is not evidence

**`openai/gpt-image-2/edit` accepts no `seed`.** Its input schema is
`prompt, image_urls, image_size, quality, num_images, mask_url, output_format,
sync_mode` — that's all. Runs are therefore not reproducible, and the same
prompt on the same photo gives visibly different staging decisions each time.

This has already caused a false reading: an item cleared from a counter on one
run came back on the next, which looks exactly like a regression caused by the
edit in between — but with no seed there is no way to tell that from sampling
noise. **Do not conclude a prompt change helped or hurt from a single image.**

Set `NUM_IMAGES = 2` or `3` while tuning the prompt. Cost scales per image, but
you see the spread instead of one draw from it, and an instruction that lands on
all three is genuinely landing. Put it back to `1` for production batches.

### When an instruction is being ignored, look for the conflict

This is the failure mode of a long prompt, and it has bitten twice. Both times
the ignored instruction was fine and something else was overriding it:

- **"Straighten dining chairs" did nothing** because *"Large furniture does not
  move — sofas, beds, dining tables... stay exactly where they are"* made the
  model group the chairs with the table and freeze them. Fixed by naming chairs
  as explicitly *not* large furniture.
- **Nothing was ever cleared off a bar counter** because the only clearing rule
  was scoped to *Kitchen*, and a `balcão` / bar counter didn't qualify. Fixed
  with a rule covering any counter, bar, shelf, or ledge.

The general shape: **absolute-sounding preservation language outranks permissive
staging language.** That is why `Preserve` now says in as many words that it
governs the building and not the loose objects in it, and that
`Staging and tidying` wins for anything portable. If a new instruction won't
take, grep the prompt for whatever forbids it before making the instruction
louder.

**An unscoped adjective outranks a conditional clause.** A night pool photo came
back as broad daylight, even though the prompt said *"at dusk or night, switch on
the room's existing lamps at 2700–3000K."* The culprit was three words earlier and
unconditional: *"Neutral white balance, bright and inviting."* The model read
"bright" as an instruction about the whole image and the conditional never got a
chance. Fixed by deleting "bright and inviting" and stating the hour as a
preservation rule with its concrete instance — *"keep the source's hour — never
brighten night or dusk into daylight"* — plus "sky and unlit ground stay dark" on
the night branch. Same lesson as the kettle: the unconditional sentence wins, so
scope every mood word or delete it. Also dropped "the room's" from the lamp
clause, which had been quietly scoping it to interiors.

**A permissive clause after a prohibition cancels it.** The clearing rule listed
utility objects to remove, then said "keep the two or three most attractive."
Metal napkin holders survived **3 runs out of 3** — the model was obeying the
keep-allowance and electing them as decor. Order matters inside a paragraph, not
just between sections. (That "most attractive" wording is now gone entirely: the
keeper decision is made by the feature-vs-resident test, which doesn't rely on
the model's taste.)

**A rule written for one purpose can silently reverse another.** The cables rule
said "the lamp, TV, or **kettle** stays exactly where it is" — purely to explain
that a device shouldn't vanish along with its cord. But the counter rule said to
remove kettles, and the newer, more concrete sentence won: the blender came back
in **3 runs out of 3** after being removed in 3 of 3. Cost three generations to
find. This is precisely what `--check` now catches, and the bug it was validated
against.

**The frame margin invents architecture unless told what to do with doubt.**
Once the canvas exception was granted, all 3 variants added a wooden door frame
at the left edge — the model reasoning about what a room like this probably has
just out of frame. Fixed with an explicit default: *uncertainty resolves to
blank surface, never to a feature.* Any permission to generate needs a stated
fallback, or the model fills the gap with something plausible.

**And beware example lists — they read as menus.** A clearing rule once said
"keep two or three pieces — a ceramic vessel, a bowl of fruit, a plant, a framed
picture" and the model *added a potted plant that was never in the room*. Naming
a category of object anywhere near a staging permission is read as license to
place one. Describe what to keep by reference to the photo, never by example.
