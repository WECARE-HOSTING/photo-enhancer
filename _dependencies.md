# Dependencies — what breaks what

_Last updated: 2026-08-02 (stage 0 classification: one call per photograph, plus
the pass that tells two bedrooms apart)_

Small project, one file. Before changing anything below, read its "Depended on
by" row. After changing it, run:

```bash
grep -rn "CHANGED_NAME" . --include="*.md" --include="*.py" \
  --exclude-dir=.venv --exclude-dir="3 - completed"
```

Every hit is a file that may now embed a stale assumption. `3 - completed/` is
excluded because it is an archive: its logs record what was true when they were
written and are never updated.

---

## The shape, since 2026-07-31

Four folders, one per process step. A job moves forward one folder at a time,
**only when a human approves it**, and never goes back on its own.

```
0 - selection/    drop -> choose -> name -> develop -> mint the job
1 - edit/         fal.ai            [the only stage that costs money]
2 - marca dagua/  the WeCare mark   [local, free, deterministic]
3 - completed/    archive           [no gate — nothing runs on a photo here]
```

**What changed, and what not to "fix" back:**

| | |
|---|---|
| `1 - input/organize.py` is gone | Its only job was accepting an already-curated delivery that skipped selection. Every delivery now enters at `0 - selection/drop/`, so the script was a copy step between two folders that both already knew which files were in play. Deleting it also removed `OWN_FILES` (a two-item allowlist protecting the stage's own scripts from being swept into a job), `find_collisions()`, and an `IMAGE_EXTS` narrower than what stage 0 accepts — which silently dropped `.heic` |
| `2 - in progress/` became `1 - edit/` | Same stage, renamed to say what it does |
| `2 - marca dagua/` is new | Unaccented ASCII on purpose. The NFC/NFD fold bug bit this project three times; a folder name with no accent cannot be the fourth |
| Numbers 1 and 2 were **reused**, not vacated | This is the dangerous part of the rename and the reason `_config/paths.py` exists. A stale `ROOT / "1 - input"` resolves to a folder that exists and is wrong: nothing raises, and photographs land silently in the wrong stage |
| Every numbered folder has a `ledger.md` | One row per event. Did not exist before, in any form |
| Three gates, not one | `0 - selection`, `1 - edit`, `2 - marca dagua`. `3 - completed` has none — approving what is already home approves nothing |

## `_config/paths.py`

**Nothing else in the codebase may hold a stage-folder literal.** Five did before
the restructure; three of them were in `organize.py` and died with it.

| | |
|---|---|
| Depended on by | every script in the project |
| Owns | `SELECTION_DIR` `EDIT_DIR` `MARCA_DIR` `COMPLETED_DIR`, `JOB_DIRS`, `rel()`, `cmd()`, `notify()` |
| Why `cmd()` exists | There were **34** hardcoded `./_config/.venv/bin/python "<stage>/<script>.py"` strings in printed next-steps, argparse help and docstrings — including one baked inside the generated review page's JavaScript, which is what the Approve button puts on your clipboard. Derived from `__file__`, a printed command cannot outlive a rename; typed out, it fails silently and confusingly |
| The one that nearly bit | `develop.py`'s `INPUT_DIR = ROOT / "1 - input"`. The row in this file whose entire purpose was making a folder rename safe **did not list it** |
| Renaming a stage | Change it here and nowhere else, then run the grep at the top of this file for the old name |

## `_config/ledger.py`

| | |
|---|---|
| Depended on by | `cull.py`, `develop.py`, both `batch.py`, `archive.py`, `gate.py` (for `cell()`) |
| Owns | `ledger.md`'s five columns and the five-word event vocabulary |
| **The rule that keeps this safe** | **Logs are write-only for the pipeline and read-only for humans. No script ever reads a log to decide what to do next.** The filesystem is still the state. The moment a log becomes an input it can disagree with the disk — the exact class of bug rework-by-deletion was built to eliminate |
| The event words are closed | `entered` · `run` · `gate` · `left` · `stopped`. Closed because a free vocabulary drifts across five scripts, and because `grep '\| gate \|' */ledger.md` has to mean one thing |
| A row must not hold a fact that exists nowhere else | Counts, a timestamp, a name, a pointer. Lose a job folder and you lose the detail but keep that it existed and where it went |
| The `left` row names its destination | That pointer is the only thing stopping a stage log from being divorced from its subject once the job has moved on |
| `cell()` writes `\|` as `∣` (U+2223) | Not a backslash escape, which would need an unescape on the way out — and nothing ever reads a ledger back, so the escape would exist only to be forgotten |
| Free to test | Entirely. Appending a row costs nothing and the file is hand-editable |

## `_config/gate.py`

| | |
|---|---|
| Depended on by | both `review.py`, both `batch.py`, `develop.py`, `cull.py` (`PAGES` only) |
| Owns | the palette, the shared page CSS/JS, `copy()`, the `gate.txt` format, `gate.md`, and the three page names |
| **The wire format** | `NAME  # why` sends a photo back; `+NAME  # note` keeps it and records the note. That is the old `rework.txt` grammar plus two characters, so muscle memory survives. **A trailing `#` is a comment** — see the live bugs below |
| Options ride in the comment | `variant=claro`, `glow=on`. Applied to that run only. **Never persisted**: the resulting `_final.jpg` on disk *is* the persistence, and a file storing the override would be a second source of truth able to disagree with the image |
| CSS/JS are injected via `.format()` | So they no longer need doubled braces. `review.py`'s stylesheet used to be written `{{ … }}` throughout for that reason alone |
| Why the clipboard, still | A browser page cannot write into the folder it sits in, and a download landing in `~/Downloads` would be worse than a copy button |
| The copy button copies the **whole file** | Not the delta. Pasting twice is then harmless; a delta would silently double every record |
| Every run pre-creates `gate.txt` | Telling someone to paste into a file that does not exist means TextEdit, and TextEdit defaults to RTF. You get `gate.txt.rtf` and an error saying "no gate.txt", which points at the wrong problem. `parse()` also **rejects RTF by name** and says how to fix it |
| The page is pre-filled from `gate.txt` | Which is why there is no `localStorage` layer: the durable draft is the file, and Safari refuses browser storage under `file://` anyway. A `beforeunload` warning prevents the loss instead of recovering from it |
| The comment box is a **sibling** of the `<label>` | A form control inside a `<label>` toggles that label's checkbox when clicked. `cull.py`'s room `<select>` is a sibling for the same reason |

## `_config/stage.py`

Shared **functions**, deliberately not a framework.

| | |
|---|---|
| Depended on by | both `batch.py`, `develop.py`, `archive.py` |
| Owns | `RESULT_MARKERS`, `JOB_RE`, job discovery, the skip rule, `drop_results`, `advance`, `job_field`, `next_job_id` |
| Why not a `Stage` object | Two callers, and they differ where it matters: stage 1 is network-bound, billed, non-deterministic and wants threads; stage 2 is CPU-bound, free and deterministic and runs serially. Parameterising the pool would have made the abstraction bigger than the two `main()`s it replaced. **A fix to one `batch.py` should be checked against the other** — that is what this row is for |
| **`RESULT_MARKERS = ("_edit", "_enhanced", "_final")`** | `_enhanced` stays **for good**: the 22 archived jobs used it, and dropping it makes `--reindex` read 103 archived results as sources and double every count. `_final` is the one that must never be forgotten — a `_final.jpg` not recognised as a result is read as a source photograph and **sent to the paid API** |
| Five places encode "what a result looks like" | `RESULT_MARKERS`, `strip_result`, `result_of`'s two-name list, `drop_results`'s glob, and `ambientes.RESULT_SUFFIX_RE`. Adding a suffix means all five |
| `next_job_id()` scans **all three** job folders | Checking only the next stage let `develop.py` create `1 - edit/Job_0023` while `2 - marca dagua/Job_0023` still existed: two photo sets, one number, and `add_to_index` silently overwriting one row with the other |
| `drop_results` takes both suffixes | Stage 1 passes `("_log.md",)` because the fal receipt describes the run being discarded. **Stage 2 passes nothing**: that log belongs to stage 1, is the only record of which prompt produced the image, and cannot be rewritten from there |
| `photo_count()` ≠ `len(photos_in())` | The index counts photographs by identity. Several archived jobs had their sources deleted by hand, and counting sources made `--reindex` overwrite an accurate row with a zero |
| `advance()` refuses rather than merges | Two different photo sets under one number is worse than a stopped pipeline |

## `0 - selection/` — receives and keeps

Still shaped differently from the other three, and still deliberately.

| | |
|---|---|
| Receives and keeps | A shoot folder holds its 3.7 GB indefinitely. **No script deletes `source/` on its own** — the exception is `archive.py --purge-source`, which is human-run, refuses unless the work is archived with its `originais/`, and asks you to type the shoot's name. This wording replaced a flat "never deleted", and both halves matter |
| Has a human gate | `cull.py` stops at `review-selection.html` and waits |
| **Mints the job number** (since 2026-07-31) | Reverses the old "claims no job number" rule. This is the one moment the shoot's name and a fresh number are in the same process, and the archive needs that link to assemble `originais/`. It goes into `job.md` as `**Shoot:**` |
| Owns the naming convention | Every filename in the system is decided here and nothing downstream renames it |
| Hands off by | Writing `1 - edit/Job_NNNN/` directly, with `job.md`, `gate.md` and `originais.md` |
| Develops **everything** (since 2026-07-31) | Not only the picks. The unpicked go to `<shoot>/developed/` at 2400px and wait for the archive to collect them. The 1600px proxies would have been free but are below the 2048px the pipeline delivers, and the archive resolution is the permanent ceiling on every future re-pick |
| Load-bearing detail | `ambientes.md`. `develop.py` refuses to run without it, because guessing would put an unverified room name on a file that goes to a client |
| Free to test | All of it except the two vision passes |

### Unicode in filenames — bitten three times

Any new comparison of filenames in this project needs the same treatment.

| Where | What happened | Fix |
|---|---|---|
| `fetch.py` → `compare_to_list()` | macOS stores `Área` decomposed (NFD); Drive and browsers give it composed (NFC). 78 of 307 names carried an accent, so a complete delivery reported a quarter of itself missing | `same_name()` normalises to NFC and casefolds |
| `vision.py` → `upload_for_vision()` | `fal_client.upload()` rejects a non-ASCII `file_name` and reports `Invalid storage type`, which names nothing. 7 of 19 rooms failed and **every failure had an accent** | `ascii_name()` transliterates |
| `develop.py` → `resolve()` | `picks.txt` comes back through a browser and a clipboard, either of which may recompose accents | `fold_name()`, same normalisation |

**Two folds, one owner each, and mixing them is the next version of this bug.**
`ambientes.fold()` strips accents entirely and is for **keywords** (`Terraço`
must match `terraco`). `ambientes.fold_name()` composes to NFC and casefolds and
is for **filenames**, where `Suíte` and `Suite` could be two real files.

## `_config/Seletor/AMBIENTES.md` and `RULES.md`

Unchanged by the restructure. `AMBIENTES.md` is what you edit to change what
rooms are called; `RULES.md` is what you edit to change which photos get chosen.

| | |
|---|---|
| Must not change | Their `=====` marker lines. Both loaders hard-fail without them rather than send the documentation below into a prompt |
| `AMBIENTES.md` holds **three** prompts since 2026-08-02 | `CONFIRM` (is the label right?), `NAME` (what is this one photograph?), `SPLIT` (which of these are the same room?). They must appear in that order — each block ends where the next begins — and `ambientes.py` refuses to load if one is missing or out of order. They were one block, and sharing it was the bug: the text opens "photographs of ONE room" and "agree unless you can see that they are wrong", which is false with no label to confirm |
| Slug shape is a contract | Uppercase and `_` only, **never a digit** — the digits are what let `AREA_SERVICO_01_0003` be parsed back apart |
| `NAO_IDENTIFICADO` must exist | It is what an unnameable room falls back to |
| Synonym gotcha | Matched by **where** the word appears, not how long it is. `Sala Cobertura` is a living room in the penthouse; preferring the longest keyword filed it as a roof terrace |
| `condomínio` is deliberately absent | A folder of that name holds a gym, a lobby, a pool deck and a party room. With nothing matching, the per-photo pass names each one |
| Calibrated against one photographer | The percentiles in `RULES.md` come from a single 307-photo delivery. **Re-measure when a new photographer starts sending work** |
| Not retroactive | A job already in a later stage keeps the names it was given |

## `0 - selection/ambientes.py`

| | |
|---|---|
| Depends on | `AMBIENTES.md` only. Imports nothing from this project, which is what lets `cull.py`, `develop.py` and both `review.py` import **it** without a cycle |
| **Owns the only `NAME_RE`** | There were three. The stated reason — "a sibling folder whose name has spaces cannot be imported" — was never true: every stage already inserts a path and imports across. `grep -rn "NAME_RE" --include=*.py .` must show exactly one **definition**; the other hits are comments and the two `import ambientes` lines that name it |
| `parse_name` strips every result suffix | `RESULT_SUFFIX_RE`, kept in step with `stage.RESULT_MARKERS`. It knew only `_edit` before; a `_final` stem returned `None` and every photo collapsed into one section headed `—` with an invalid HTML id |
| The catalogue has two answer columns | `Ambiente` is the answer in force and what a person edits; `Visto` is what the last run saw. A difference is **proof of a human edit** rather than proof that two runs disagreed |
| `Sala` is input too | It is the only way to say that two rooms of the same kind are two rooms |
| Free to test | Entirely. With no arguments it prints the vocabulary; with a label it prints what that maps to and why |

## `0 - selection/cull.py`, `vision.py`, `ingest.py`, `fetch.py`

| | |
|---|---|
| `ROOM_PATTERNS` | How a room label is read out of a filename. **Add a photographer's scheme here** |
| `group_rooms()` runs **twice**, and the calls mean different things | The first is provisional, bucketing by the photographer's label to gather each room into one cheap batch. The second runs with `ambiente` in the key and is authoritative — that is what splits a stray photograph into its own room. Collapsing them silently removes the splitting |
| Three questions, one endpoint | `classify()` asks *what room is this*, `split_rooms()` asks *which of these are the same room*, `choose()` asks *which of these is best*. An unlabelled folder is not evidence of a room — 28 files of common areas came back as one imaginary room until the first split |
| **Unlabelled classification is one call per photograph** | Not one per room. It batched twelve and asked for an array of twelve answers; the array truncated at `MAX_TOKENS` and every missing entry silently inherited the batch's majority vote. On `WC-00284` three photographs of a bed were delivered as `COZINHA`. A photograph now gets its own answer or an honest `NAO_IDENTIFICADO` — never another photograph's. **Never re-batch this to save calls** |
| `labels_distinguish()` decides who owns room identity | The photographer's label goes in `group_rooms`'s key only where it actually separates two rooms of one ambiente. An *absent* label is not a distinguishing one: counting it as one put a veranda photo nobody had named into a `VARANDA_02` of its own. `split_ambientes` uses the same function to decide what to ask about, so the two cannot disagree about who is deciding |
| The split pass never invents a room on doubt | Missing file, repeated file, unparseable answer, more than `SPLIT_MAX_IMAGES` photos — every failure resolves to *one room*. A merge is one click to fix on the sheet; a wrong `QUARTO_02` is a wrong filename at the client |
| `CLASSIFY_TEMPERATURE = 0.0` | For naming and splitting only; ranking stays at `TEMPERATURE`. "Is there a bed in this picture" has an answer, and at 0.2 one cold run in three split a veranda into two rooms over four photos of one hammock. Three cold runs at 0.0 are byte-identical |
| `PHASH_MAX_DISTANCE` cannot catch near-repeats | Measured on `WC-00284`: tightest genuine repeat at 20, tightest genuinely useful pair at 22. No threshold fits in that gap. The `quase repetida` rejection in `RULES.md` is where that judgement lives |
| `cluster_scenes()` runs **twice** too | First on the photographer's label, then on the ambiente once one is known. On a delivery where every file carries the same label, the first bucket is the whole house |
| Type A is protective | A delivery profiled as already-culled gets **no quota and no cuts**. This is now also the path an already-curated delivery takes, since `drop/` is the only way in |
| `vision.py` never kills a run | It returns a verdict carrying an error instead of raising |
| `VERTICAL_TOLERANCE_DEG = 15` | Load-bearing. At 32° it measured ceiling drying racks. Changing it invalidates every threshold in `RULES.md` |
| `CROP_FACTORS` is a stub by design | An unknown body reports the 35mm equivalent as unknown rather than guessing |
| OpenCV version sensitivity | `HoughLinesP` returns `(N,1,4)` in v4 and `(N,4)` in v5; `vertical_geometry()` reshapes for both |
| Clipboard | `copyOut()` is shared and **has a rejection branch**. It did not before: a blocked clipboard on the contact sheet did nothing at all and said nothing, which is worse than a broken button because you paste the previous clipboard and never notice |
| Free to test | `cull.py --no-classify`, `--profile-only`, `ambientes.py` on a label, `vision.py --room X` |

## `0 - selection/develop.py`

| | |
|---|---|
| Depends on | `picks.txt`, `ambientes.md`, `source/`, `stage.new_job_name()`, `1 - edit/` existing |
| Owns | the job number, `job.md`, `originais.md`, the shoot's `gate.md`, `developed/` |
| Refuses to run without `ambientes.md` | The names come from there and are not re-derived |
| **`--force` refuses once results exist** | It used to `rmtree` the destination. With the destination now a live `Job_NNNN/`, that would delete paid `_edit.jpg` files, the logs saying which prompt made them, and the gate record. It now refuses if any `*_edit*.jpg` is present and tells you to delete the folder by hand |
| Deliberately does not | Re-apply the quota, skip a flagged frame, or reconsider a pick. **The human's list is final** |
| Output size | 2400px, for the picks and the unpicked alike |
| `originais.md` is written here | Only here does one process know both which source file became which name and which were left out. `archive.py` copies the finished manifest rather than re-deriving it — which would mean reading a record back |

## `1 - edit/1 - edicao/PROMPT.md`

**The file you will edit most.** The only surface that changes how photos come out
**in phase 1** — which is every photo of every job.

**Phase 3 does not read it.** `2 - retoque/` sends the human's own sentence and
nothing else, on purpose: that sentence exists to override rules written here. So a
rule added here binds every future photo, and a gate comment binds exactly one.

| | |
|---|---|
| Depended on by | `enhance.py` (`load_prompt()`, fresh per photo), every `<name>_log.md`, `1 - edicao/CONTEXT.md` → "Editing PROMPT.md" |
| **Not** depended on by | `2 - retoque/retoque.py` — deliberately, and the whole point of phase 3 |
| Must not change | The `===== END OF PROMPT` marker line |
| Safe to change freely | All prose above it. No code parses its structure |
| Guard against self-contradiction | `1 - edicao/enhance.py --check` — free, instant, needs no photo. **Run after every edit** |
| **Must never learn the watermark exists** | Naming a watermark in a prompt trips fal's content policy: `content_policy_violation`, the request never reaches the model, no charge and no image. The mark is composed locally and `PROMPT.md` is not told |
| Known hazard: conflicts | An absolute-sounding rule earlier in the file silently outranks a permission later in it |
| Known hazard: example lists | Naming object categories near a staging permission reads as a menu and gets them *added* to the room |
| Known hazard: cutting length | Removing a concrete noun in favour of a general principle silently drops the behaviour. Cut prose, keep nouns |
| The fingerprint is the trail | `#xxxxxxxx` in each log answers *which wording produced this image*. A per-photo gate comment is recorded **beside** it, never folded into it |

## `_config/fal.py`

The trip to fal.ai, and every constant that governs it. Split out of `enhance.py`
on 2026-08-01 so that phases 1 and 3 could share it **without one importing the
other** — `retoque.py` importing `enhance.py` would make phase 3 depend on phase 1,
and the two would stop being independent contracts, which is why they were split.

| | |
|---|---|
| Depended on by | `1 - edicao/enhance.py`, `2 - retoque/retoque.py` |
| Owns | `DEFAULT_MODEL`, `QUALITY`, `TARGET_LONG_EDGE`, `UPLOAD_*`, `DOWNLOAD_TIMEOUT`, `RATIOS`, `EnhanceError` |
| **Constants are shared** | Change `QUALITY` and both phases change. If one ever needs its own, give it its own constant there rather than a per-folder copy |
| `download()` is atomic | Writes `<dest>.part`, then `os.replace()`. **Load-bearing for phase 3**, where the destination *is* the image just uploaded as input: a failed download must not be able to leave the job with no `_edit.jpg` |
| `payload_for()` branches on family | gpt-image-2 takes `image_size` + `quality`; nano-banana takes `aspect_ratio` + `resolution` + `seed`. Both phases need the same branch |
| `url_alive()` | A `HEAD` (~200ms) before reusing a CDN URL from an old log, against a ~4s re-upload. Being wrong means a billed request with a broken reference |
| Cost is not estimated anywhere | fal prices by quality tier **and** pixel count. Check fal's dashboard. Do not add an estimator — a `--dry-run` existed until 2026-07-27 and watching real results was trusted over its preview |

## `1 - edit/1 - edicao/enhance.py` — phase 1

| | |
|---|---|
| Depended on by | `batch.py` (imports `run`, `DEFAULT_MODEL`, `EnhanceError`) |
| Contract `batch.py` relies on | `run()` accepts `emit=` and raises `EnhanceError` instead of exiting. A `sys.exit` inside a worker thread kills nothing and hangs everything |
| Took a per-photo `extra=` until 2026-08-01 | It appended the gate comment to `PROMPT.md`'s text — which meant an absolute rule earlier in the file outranked the human's own sentence. That is now phase 3's job, with no `PROMPT.md` at all |
| `EnhanceError.phase` | `before` or `after` the request reached fal — which is whether it may have been billed. It is what lets a run say "2 falhas (1 antes do envio, 1 depois)" instead of leaving you to open sixty logs |
| Where results go | The photo's own folder by default. That is what keeps a job self-contained |
| Stays standalone | Never renames, moves or archives. Runs against any path, including one outside the project |
| **Writes the line phase 3 parses** | `SOURCE_URL_LABEL` — see `<name>_log.md` below |

## `1 - edit/2 - retoque/retoque.py` — phase 3

| | |
|---|---|
| Depended on by | `batch.py` (imports `run`) |
| Depends on | `fal`, `stage.result_of` / `shelve_result`, and **`<name>_log.md` as an input** |
| Sends | `image_urls = [the _edit, the original]`, in that order, with `PROMPT.md`'s frame + the human's sentence and nothing else |
| **Order is a contract with its `PROMPT.md`** | The frame names them "image 1" and "image 2". Swap them in the payload and it describes the wrong picture |
| Forces `num_images = 1` | A retouch answers one instruction; variants are a phase-1 tuning tool |
| `image_size` from the `_edit` | Already ~2K at the source's ratio, so the proportion never drifts across rounds — and the source file never has to be opened when its URL is reused |
| Deletes nothing | The `_edit.jpg` is the input; the old one is **shelved** as `_edit_rN.jpg` by `stage.shelve_result()` |
| Download-then-swap | Writes `<stem>_edit.new.jpg`, then shelves, then renames into place. Two atomic renames, so a failed download can never leave the photo with no edit |
| Cannot widen the frame | `image_size` is fixed to the edit's proportion, so "expande a direita" recomposes inside the same rectangle. Widening would need a `ratio=` token in `gate.py`'s `OPT_RE`. Not built — see `2 - retoque/CONTEXT.md` |

## `Job_NNNN/<name>_log.md` — a record that became an input

**Read this before changing anything about a log's format.** Until 2026-08-01 the
per-photo log was write-only, like every other log in this project — `ledger.py`'s
docstring still states the rule, and it is still right everywhere else. This one
file is the exception, and it is the single most breakable edge in the pipeline
because breaking it **fails silently and still works**.

| | |
|---|---|
| Written by | `1 - edicao/enhance.py` — the whole file, from scratch, on every phase-1 run |
| Appended to by | `2 - retoque/retoque.py` — one `## Retoque N` block per retouch, never rewriting what is above |
| **Parsed by** | `2 - retoque/retoque.py`, for exactly one line: `\| Uploaded source \| <url> \|` |
| The pair that must agree | `enhance.SOURCE_URL_LABEL` writes it, `retoque.SOURCE_URL_RE` reads it. **Change one and change the other** |
| What breaks if they disagree | The original is uploaded a second time on every retouch. ~4s and a few cents per photo, no error, no wrong output — the kind of breakage nobody notices for months |
| Why the first match wins | Phase 1's block is at the top and its URL is the original photograph. A later retouch block may record a re-upload: same image, but not the authoritative row |
| Why a retouch must not delete it | It is where that URL lives. This is why stage 1's `--rework` deletes nothing, unlike every other rejection here |
| Deleted by hand? | `retoque.py` starts a fresh log saying phase 1's block is missing, and uploads the original. Degraded, never fatal |
| `--rework` no longer deletes it | It did until 2026-08-01, together with the `_edit.jpg` — which destroyed the URL at the exact moment it became useful |

## `1 - edit/batch.py` and `2 - marca dagua/batch.py`

Siblings. **A fix to one should be checked against the other.**

| | |
|---|---|
| Depend on | `stage`, `gate`, `ledger`, `paths`, their own `review.py`, and their worker (`enhance.run` / `marca.run`) |
| Own | job selection, the skip rule, the gate fold, `--rework`, `--approve`, the move |
| **Neither advances on its own** | Only `--approve` calls `advance()` |
| **The order is record, delete, move** | The gate is folded into `gate.md` and a ledger row written *before* the scratch files go and the folder moves. It used to be the reverse: `approve()` unlinked the page and the rework list and *then* archived, destroying the rejection history at the exact moment it became permanent. A crash must leave a recorded decision with unfinished work, not finished work with no record |
| Stage 2's `--rework` has no machinery | It deletes the rejected results, and deleting one is what makes the ordinary skip rule run that photo again. No retry list, no state file, nothing that can disagree with disk |
| **Stage 1's `--rework` is the exception** | Phase 3 *edits* the `_edit.jpg`, so the result is the input and deleting it destroys what the run needs. It passes an explicit list of stems instead, deletes nothing, and shelves the old edit. Do not "restore" the delete rule here |
| Stage 1 refuses a mark with no comment | Before `fold_gate()` and before any spend — phase 3 *is* the comment. `gate.txt` is left intact so the marks survive being written on. Another draw from the fixed prompt is `--redo` |
| `--approve` refuses on a hole | A photo with no result has nothing to show and so never appeared on the page |
| `--approve` refuses on pending marks | Otherwise a rework list would be thrown away silently |
| Stage 1's `--approve` drops the shelved edits | `stage.drop_shelved()`, said out loud with a count. They exist so a human can choose between retouch rounds; once the job has moved there is nothing to choose |
| Stage 1 threads, stage 2 does not | Network wait vs. CPU. Do not "fix" stage 2 to use a pool |
| Gate comments ride in memory | From `--rework` into the run of the same invocation. Nothing writes them where a later run could read them back; the durable record is `gate.md` and the `_log.md` block |
| One ledger for both phases | The phase goes in the **detail**; the event stays `run`. `ledger.EVENTS` is closed and identical in all four stages, and `grep -n "Job_0023" */ledger.md` is a job's life *in order* |

## `1 - edit/review.py` and `2 - marca dagua/review.py`

| | |
|---|---|
| Depended on by | their own `batch.py` (imports `write`, `NAME`) |
| Own | their page's layout and their own CSS/JS. Everything they share is in `gate.py` |
| Why they are separate files | The layouts differ because the decisions differ: stage 1 compares two whole photographs, stage 2 judges 2% of one frame. A single builder for both needed 33 parameters and three escape hatches, and did not come out smaller |
| Stage 1's A/B flip | Side by side answers *did it change*, not *did it change correctly* — the eye cannot carry a 3° lean across a gap. Both images are already in the DOM, so swapping the lightbox `src` is instant and lands on the same pixels |
| Stage 2's 1:1 crop is **CSS**, not a file | `object-fit:none` with `object-position:0 0` shows native pixels with no resampling. Crop files would have cost 3.6 MB per job forever — and a `<stem>_crop.jpg` carries no result marker, so `photos_in()` would read each one as a source photograph and send it to the paid API |
| Stage 2's numbers are measured fresh | `marca.run(write=False)`, never read out of `marca.md`. No script reads a log to decide anything |

## `2 - marca dagua/marca.py`

| | |
|---|---|
| Depends on | `_config/logos/wecare-hosting-horizontal-{escuro,claro}.png`, Pillow, numpy |
| Depended on by | `batch.py`, `review.py` (for `run(write=False)`) |
| **`claro` and `escuro` name the ink, not the background** | Navy on a light wall, cream on a dark room. Reading it backwards is the obvious mistake |
| Crops to the alpha bbox first | The PNGs carry 52px/55px of transparent padding and the two lockups pad differently. Sizing by the canvas renders 5% less art and puts the margin in the wrong place |
| Scaled by the **long edge** | By width, a portrait photo gets a mark 33% smaller than a landscape one in the same gallery |
| Thresholds were measured, not chosen | `MIN_CONTRAST = 4.0`, `BUSY_STD = 0.18`, against all 174 archived photographs: 69% navy, 31% cream, glow on 33%, worst 3.37:1, median 6.02:1. The first guesses were wrong in both directions — `3.0` would never have fired, `0.10` fired on 52%. **Re-measure if you change them**; it is free, and the numbers move with `LOGO_WIDTH_PCT` because a bigger mark samples a bigger patch |
| Always reads the `_edit` | Never a `_final`. Marking is idempotent and JPEG loss never accumulates |
| Replacing the logo re-marks everything | `needs_mark()` compares against the PNG's mtime |
| No `MARCA.md` | `PROMPT.md` exists because it is 2.7 KB of prose edited weekly. This is six numbers, already calibrated. Constants at the top of the file, with the reasoning in comments |
| Reads pixels, does not grade | Measurement. See "The no-inspection rule" |

## `3 - completed/archive.py`

| | |
|---|---|
| Depended on by | `2 - marca dagua/batch.py`, which imports `build_originais` and `add_to_index` |
| Why stage 2 imports from stage 3 | `originais/` must be assembled **before** the folder moves, because afterwards the process that knew which shoot it came from has exited. Assembling the archive is still this file's business |
| `originais/` is real copies, not hard links | Links cost zero bytes and show 4.18 GB *apparent* per job; any Finder drag or Dropbox sync of the archive would silently materialise all of it. ~370 MB of honest bytes is the better trade |
| `build_originais` is never fatal | A job whose shoot is gone still archives, and says so |
| `add_to_index` checks the header | The columns changed under 22 legacy rows. Inserting would put a 5-cell row under a 4-cell header and nothing would raise — the table would just render wrong. A mismatch triggers a rebuild instead |
| `--check` skips pre-restructure jobs | They have no `_final` and no `originais/`, and that is not wrong. Judging them by today's rules buried the one real problem under 44 complaints about history |
| `--check` is the only defence against a Finder drag | A job's folder location **is** its status and nothing else records it. That is deliberate — a second record can disagree — and the cost is that dragging a folder silently rewrites the truth |
| `--purge-source` | Human-run, refuses unless the work is archived with its `originais/`, prints what it will delete, requires the shoot's name typed. **Never run it on your own initiative** |
| `index.md` is not the source of truth | The folders are. `--reindex` rebuilds from what is actually there. Safe to hand-edit, but a rebuild overwrites the whole file |
| Non-job folders | Listed in a footnote under the table, because a table of jobs alone would read as a complete picture of the folder when it is not |

## The no-inspection rule

**Results are handed over as-is. Nothing in this system reads an enhanced photo
back against its source** — not the scripts, not the agent. The user judges the
photos on their own screen.

| | |
|---|---|
| Amended 2026-07-31 | There are now three formal places for it: the three gate pages. What is unchanged is that the scripts and the agent do not grade a photo, and the agent never runs an advancing command on its own initiative |
| **Measurement is not grading** | `marca.py` reads background luminance, contrast and spread. That is how the ink is chosen, it is arithmetic, and it decides nothing about whether the photograph is good. Both statements of the rule must say so, or the next reader concludes it was abandoned |
| Stated in | `CLAUDE.md` → "Running it" and each stage's `CONTEXT.md` → "The gate". They must agree |
| Breaks if reintroduced | Any file that tells the agent to open, compare or grade a result contradicts `CLAUDE.md`. Fix the feedback loop through `PROMPT.md` instead |
| The live feedback path | Report a repeated failure → the gate comment fixes that photo → the same comment twice means tighten `PROMPT.md` → `enhance.py --check` → next run |

## The commands that move or destroy

`develop.py`, `1 - edit/batch.py --approve`, `2 - marca dagua/batch.py --approve`,
`archive.py --return`, and `archive.py --purge-source`, which deletes
photographs.

**None of them may be run by an agent on its own initiative.** Stated in
`CLAUDE.md` → "Running it" and repeated in each `CONTEXT.md`.

## Text one script parses out of another's output

Three, now — it used to be one, and this row used to say so.

| Format | Written by | Read by |
|---|---|---|
| `**Dropped as:** …` | `develop.py` → `write_job_md()` | `archive.py` → `job_row()` |
| `**Shoot:** \`path\`` | `develop.py` → `write_job_md()` | `archive.py` → `shoot_of()`, for `originais/` |
| `gate.txt` | the gate pages' copy button | `gate.parse()` |

Change the wording in a writer and the reader silently falls back to a dash.

## Naming convention (`AMBIENTE_NN_NNNN.jpg` + `_edit` / `_final` / `_log.md`)

| | |
|---|---|
| Defined in | `CLAUDE.md` → "Naming convention" |
| Vocabulary | `_config/Seletor/AMBIENTES.md` |
| Implemented in | `ambientes.py` → `NAME_RE`, `parse_name()`, `format_name()`, `number_rooms()`; `cull.py` → `group_rooms()`; `develop.py` → `assign_names()` |
| Assumed by | `stage.py` → `photos_in()`, `strip_result()`, `result_of()`, `photo_count()`; both `review.py` → `parts()`; `enhance.py` and `marca.py` derive every output name from the stem and assume nothing about its shape |
| Slug and suffix cannot collide | Slugs are uppercase, the suffixes are lowercase. That is what makes `"_final" in stem` a safe test |
| Deliberately lossy | The photographer's original filenames survive in `job.md` and in `originais.md` |
| Breaks if | A folder is renamed out of the `Job_NNNN` pattern, or a shoot's `ambientes.md` is deleted before `develop.py` runs |

## Live bugs this restructure fixed

Worth keeping, because four of them were silent and would come back the same way.

| Where | What it did |
|---|---|
| `read_rework` / `read_picks` | `Path("SALA_01_0001  # muito escura").stem` returned the whole string, so a line with a comment landed in `unknown` and **the photo was silently not reworked**. The same one-line bug in a second file made a single note on the contact sheet abort the entire hand-off |
| `approve()` | Deleted `review.html` and `rework.txt` **before** archiving, destroying the rejection history at the moment it became permanent |
| `cull.py`'s clipboard | No rejection branch. A blocked clipboard did nothing and said nothing |
| `parse_name` | Stripped `_edit` only, so a `_final` stem returned `None` |
| `add_to_index` | Inserted a row without checking the header |
| `develop.py --force` | `rmtree` on a folder that now holds paid results |

## Known loose ends

- `logs/error.log`, `logs/combined.log` — **not ours.** An unrelated
  `mcp-zapsign-server` writes them because its cwd happens to be this folder.
  Gitignored. That is also why the stage logs are `ledger.md` inside each stage
  and not a project-root `logs/`.
- `3 - completed/Test/` — everything processed before the job structure existed
  (2026-07-25/26). Flat `{id}_enhanced.jpg` naming, no `job.md`, logs citing
  paths that no longer exist. Read-only history; the scripts ignore it.
- `1 - edit/_archive/dry_run.py` — the `--dry-run` code pulled out on
  2026-07-27, kept verbatim. Nothing imports it.
- `1 - edit/PROMPT_backup_*.md` — two earlier revisions, kept for the length
  comparison recorded in `CONTEXT.md`.
- `_config/logos/` holds the `empilhado` lockup and four SVGs that nothing
  reads. Kept because they are the brand's, not because anything needs them.
