# Dependencies — what breaks what

_Last updated: 2026-07-31_

Small project, short file. One map, at the root, for the whole system. Before
changing any file below, read its "Depended on by" row. After changing it, run:

```bash
grep -rn "CHANGED_NAME" . --include="*.md" --include="*.py" --exclude-dir=.venv --exclude-dir="3 - completed"
```

Every hit is a file that may now embed a stale assumption. `3 - completed/` is
excluded because it is an archive: its logs record what was true when they were
written and are never updated.

---

## `0 - selection/` — the upstream stage (added 2026-07-30)

Sits **before** `1 - input/` and is optional: a delivery that is already a
selection skips it entirely. It has a different lifecycle from the other three
folders, and that difference is the thing most likely to be "fixed" by mistake.

| | |
|---|---|
| Receives and keeps | The other stage folders consume and empty. A shoot folder here holds its 3–15 GB `source/` indefinitely, because that is the only thing a re-pick needs. **No script ever deletes `source/`** — `develop.py --prune` clears `_proxies/` only |
| Has a human gate | `cull.py` stops at `contact.html` and waits. This is the one place in the system that does **not** run straight through, and `CLAUDE.md` → "Running it" is still true because it describes a job already in the pipeline |
| Claims no job number | Nothing here creates a `Job_NNNN`. `organize.py`'s `next_job_id()` therefore does **not** need to scan this folder, and adding it to that scan would be a change with no purpose |
| Owns the naming convention (since 2026-07-31) | Every filename in the system is decided here, as `AMBIENTE_NN_NNNN.jpg`, and nothing downstream renames it. This moved out of `organize.py`, which used to overwrite it with `Photo_NNNN` |
| Hands off by | Writing an ordinary folder into `1 - input/<shoot>/` with the final names already on the files |
| Load-bearing detail | `ambientes.md` in the shoot folder. `develop.py` reads it to name the outputs and **refuses to run** without it, because guessing would put an unverified room name on a file that goes to a client |
| What was given up | The zero-padded `NN_` prefix, which used to make `organize.py`'s text sort equal the gallery order. Names now sort by ambiente; the walkthrough order lives in `selection.md` and `job.md`'s `#` column. Do not "restore" the prefix — it would fight the ambiente grouping the whole stage now produces |
| Free to test | All of it except the two vision passes. Proxies, profiling, quota, keyword naming (`--no-classify`) and the sheet cost nothing and can be re-run at will |

### Unicode in filenames — bitten three times

Portuguese filenames broke three different things, each in a way that looked like
a different bug. Any new comparison of filenames in this project needs the same
treatment.

| Where | What happened | Fix |
|---|---|---|
| `fetch.py` → `compare_to_list()` | macOS stores `Área` decomposed (NFD); Drive's API and browsers give it composed (NFC). 78 of 307 names carried an accent, so a complete delivery reported a quarter of itself missing | `same_name()` normalises to NFC and casefolds |
| `vision.py` → `upload_for_vision()` | `fal_client.upload()` rejects a non-ASCII `file_name` and reports `Invalid storage type`, which names nothing. 7 of 19 rooms failed and **every failure had an accent** | `ascii_name()` transliterates. Safe — the CDN name identifies nothing; the model is shown the real name in the prompt |
| `develop.py` → `resolve()` | `picks.txt` comes back through a browser and a clipboard, either of which may recompose accents | `fold_name()`, same normalisation |

**Two folds, one owner each, and mixing them is the next version of this bug.**
`ambientes.fold()` strips accents entirely and is for **keywords**, where losing
the accent is the point (`Terraço` must match `terraco`). `ambientes.fold_name()`
composes to NFC and casefolds and is for **filenames**, where `Suíte` and `Suite`
could be two real files and must stay distinct. `cull.py` imports both; `vision.py`
and `develop.py` use the filename one. A catalogue lookup keyed with the keyword
fold silently half-works — it matches, until two files differ only by an accent.

## `_config/Seletor/AMBIENTES.md`

**The file you will edit to change what rooms are called** — what `RULES.md` is to
which photos get chosen, and `PROMPT.md` is to how they come out.

| | |
|---|---|
| Depended on by | `ambientes.py` (`load()`, fresh every run), `cull.py` (categories, headings, the catalogue), `vision.py` (its prompt is the classification `system_prompt`, its table is the list of legal answers), `CLAUDE.md` → "Naming convention", `0 - selection/CONTEXT.md`, every `ambientes.md` (records its fingerprint) |
| Must not change | The `===== CLASSIFY PROMPT` and `===== END OF AMBIENTES` marker lines. `ambientes.py` hard-fails without them rather than send the documentation below them to the model as prompt — the same guard `cull.py` puts on `RULES.md` |
| Parsed, so format matters | The vocabulary table, as `SLUG` → categoria → synonyms. A row is recognised by its slug being **all caps**, which is how the header row is told from data. Prose around the table is free |
| Slug shape is a contract | Uppercase letters and `_` only, **never a digit** — the digits are what let `AREA_SERVICO_01_0003` be parsed back apart. A slug with a number in it breaks `NAME_RE` everywhere |
| `NAO_IDENTIFICADO` must exist | It is what an unnameable room falls back to. `load()` refuses to run without that row |
| Categoria must exist in `RULES.md` | The categoria column names one of `RULES.md`'s twelve categories, and `RULES.md` still owns which category gets the spare slots. A categoria with no priority row there falls to 99 and the run says so |
| Synonym gotcha | Matched by **where** the word appears, not how long it is. A synonym that is a *prefix* of another is safe (`porta` next to `portaria` — the tie breaks on the longer word); one that is a prefix **and appears earlier** in a real label is not |
| `condomínio` is deliberately absent | A folder of that name holds a gym, a lobby, a pool deck and a party room. Mapping it to one ambiente confidently mislabels most of it; with nothing matching, the per-photo pass names each one. Adding it would undo that |
| Property codes are stripped before matching | The `Property codes` table (`WC-N` → WeCare) is parsed by `CODE_ROW_RE` and applied in `Vocabulary.strip_codes()`, which `slug_for()` calls first. **`WC` is WeCare, not water closet** — and `wc → BANHEIRO` is still correct and must stay, because in Portuguese a WC *is* a bathroom. The collision is resolved by shape: a room word followed by `-` and digits is a reference. Measured 2026-07-31: a 48-photo house arrived as one `BANHEIRO` from the folder `WC-00660 - Casa MAD Alter`. Same class of trap as `condomínio` above |
| Changing a slug is not retroactive | Jobs already in `2 - in progress/` or `3 - completed/` keep the names they were given. Only deliveries named after the change use the new one |

## `_config/Seletor/RULES.md`

**The file you will edit to change what gets chosen** — what `PROMPT.md` is to
how photos come out.

| | |
|---|---|
| Depended on by | `cull.py` (`load_rules()`, fresh every run), `vision.py` (its prompt is the `system_prompt`), `0 - selection/CONTEXT.md` → "Editing the rules", every `selection.md` (records its fingerprint) |
| Must not change | The `===== VISION PROMPT` and `===== END OF RULES` marker lines. `cull.py` hard-fails without them rather than risk sending the documentation below them to the model as prompt — the same guard `enhance.py` puts on `PROMPT.md` |
| Parsed, so format matters | The `key: value` lines indented four spaces; the expansion-priority table (priority / category / keywords); the volume-by-typology table. Prose around them is free |
| Category now arrives from `AMBIENTES.md` | Since 2026-07-31 a room's category is its canonical ambiente's `categoria`, and this table is read for **category → priority**. Its keyword column is the fallback for a room with no ambiente yet, and still what `Rules.category()` matches — do not delete it |
| Volume table gotcha | The rooms column is read for its **last** number: `up to 5` → 5, `6 to 10` → 10, `11 or more` → no ceiling. Reading the first number put an 8-room property in the wrong band |
| No duplicate copies | Thresholds live here **only**. `cull.py` deliberately holds none of them — two copies of a threshold is one copy that goes stale, and the stale one is always the one being read |
| Calibrated against one photographer | The percentiles quoted in it come from a single 307-photo delivery. **Re-measure when a new photographer starts sending work**; an inherited threshold is worse than none |
| Changing it is not retroactive | A delivery already sitting in `0 - selection/` keeps its `selection.md` until `cull.py` runs on it again |

## `0 - selection/ingest.py`

| | |
|---|---|
| Depended on by | `cull.py` (`read()` per file, `probe()` for profiling, `MIN_LINES_FOR_FIT`, `RAW_EXTS`), `vision.py` indirectly through the `Facts` it produces |
| Owns | Proxy size (1600 px), the geometry measurement, the perceptual hash, and `CROP_FACTORS` |
| HEIC needs `pillow_heif`, registered at import (added 2026-07-31) | Pillow has no HEIF decoder of its own and reports a phone's `.heic` as *unidentifiable*. `.heic` was already in every extension list in `fetch.py`, `cull.py` and `develop.py`, so the format looked supported and was not: a 48-photo delivery silently curated the 2 JPEGs in it. `register_heif_opener()` runs at import here **and in `develop.py`**, which does not import this module — two copies, and the reason is stated in both. Must happen before the first `Image.open()` in the process |
| Not recorded anywhere but the venv | There is no requirements file in this project. `pillow-heif` is installed into `_config/.venv` and nothing declares it; a rebuilt venv loses HEIC support and fails the same silent way |
| `CROP_FACTORS` is a stub by design | It maps body model → crop factor for the handful of cameras seen so far. **Add bodies as they appear.** An unknown body reports the 35mm equivalent as unknown rather than guessing — a wrong crop factor either discards good photos or waves distorted ones through |
| `VERTICAL_TOLERANCE_DEG` is the load-bearing constant | At 32° it measured ceiling drying racks instead of walls. 15° was chosen by sweeping against 46 real photos. Changing it invalidates every threshold in `RULES.md` |
| OpenCV version sensitivity | `HoughLinesP` returns `(N,1,4)` in OpenCV 4 and `(N,4)` in 5. `vertical_geometry()` reshapes to cope with both rather than betting on the installed version |

## `0 - selection/ambientes.py`

| | |
|---|---|
| Depends on | `AMBIENTES.md` only. Imports nothing from this project, which is what lets both `cull.py` and `develop.py` import **it** without a cycle |
| Depended on by | `cull.py` (which also takes its `fold`, so there is one copy), `develop.py`, `_config/Seletor/AMBIENTES.md` → "How this file is read" |
| Owns | `NAME_RE` (the shape of every filename), `fold` / `fold_name`, the label → slug matching, the room numbering, and the read/write of each shoot's `ambientes.md` |
| The catalogue has two answer columns | `Ambiente` is the answer in force and the one a person edits; `Visto` is what the last run's check saw. A run always writes `Visto` to what it just computed, so a difference is **proof of a human edit** rather than proof that two runs disagreed. One column cannot tell those apart, and per-photo classification is not deterministic — the drift would have been recorded as somebody's decision |
| `Sala` is input too (since 2026-07-31) | Was output-only, and the note here said so. It is now read back by `cull.py`'s `group_rooms()` and is **the only way to say that two rooms of the same kind are two rooms** — a flat folder of camera filenames gives the grouping nothing else to split on, so two bedrooms arrive as one. Normally set from `contact.html` rather than by hand |
| `Sala` needs no `Visto` twin, and that is not an oversight | The pair exists because a *model* recomputes `Ambiente` every run and its drift would otherwise read as a human decision. Nothing recomputes `Sala` but the grouping, so feeding it back is stable — same numbers in, same numbers out. Adding a second column would be machinery guarding against a failure that cannot happen |
| Two traps in `sala_hint()`, both hit during development | (1) A discarded hint must fall back to **1, never 0** — "no opinion" and "explicitly the first room" as different keys split one room in two, which is the failure the discard was protecting against. (2) The test for "you changed the ambiente by hand" must be `row.edited`; comparing the row's ambiente to the *scene's* is vacuous under `--no-classify`, because the catalogue has already been applied to the scene and the value is compared with itself |
| Free to test | Entirely. `ambientes.py` with no arguments prints the vocabulary; with a label it prints what that label maps to and why |

## `0 - selection/cull.py` and `vision.py`

| | |
|---|---|
| `cull.py` depends on | `ingest.py`, `ambientes.py`, `vision.py`, `RULES.md`, `AMBIENTES.md`, and `parse_labels()`'s `ROOM_PATTERNS` |
| `ROOM_PATTERNS` | How a room label is read out of a filename. **Add a photographer's scheme here**; an unmatched name falls back to the folder, then to nothing, and is always reported |
| `group_rooms()` runs **twice**, and the calls mean different things | The first is provisional — `ambiente` is still empty, so it buckets by the photographer's label purely to gather each room into one cheap batch for the classifier. The second runs after, with `ambiente` **and the catalogue's `Sala`** in the bucket key, and is authoritative: that is what makes a stray photograph split into its own room instead of being flagged inside the wrong one, and what lets you split one room into two. Collapsing them back into one call silently removes the splitting |
| The catalogue is read in `main()`, not in `classify_rooms()` (moved 2026-07-31) | It used to live inside that function, which `--no-classify` skips whole — so the catalogue went unread with it, and a type-C delivery then had **no source of an ambiente at all** and produced a sheet of blank rooms. Which meant there was no cheap re-run: a correction could only be applied by the pass you were trying to avoid paying for. `apply_catalog(only_edited=)` is the split — `False` for `--no-classify` (the catalogue is the only source), `True` inside the classifying path (everything else is re-verified, or the check freezes) |
| `--type C` was inert until 2026-07-31 | `Profile.needs_room_recognition` was defined and read nowhere, so the flag only changed a printed note. It now withholds the label-derived ambiente, which is what routes a delivery to the per-photograph naming pass |
| Type A is re-checked twice, and the second check acts | Near-duplicates at profiling time (warns only), then **photos per room once the rooms are named** — same `ALREADY_CULLED_MAX_PER_ROOM` the labelled path uses, applied to rooms the pictures produced. That one switches to C and curates, because the quota decides what arrives *pre-ticked*, never what appears on the page. `--type` set by hand suppresses it |
| Room-name matching rule | The ambiente is decided by **where** a synonym appears, not how long it is. Room names put the noun first — `Sala Cobertura` is a living room in the penthouse. Preferring the longest keyword filed it as a roof terrace |
| Category comes from the slug now | `vocab.category(slug)` → `rules.priority_for(category)`. `Rules.category()`'s keyword path is the fallback for a room with no ambiente, and is still used by the provisional pass |
| Two prompts, two shapes, one endpoint | `vision.classify()` asks *what room is this*; `vision.choose()` asks *which of these is best*. `classify()` itself has two answer shapes: confirm one room when there is a label, and name every photograph when there is not. An unlabelled folder is not evidence of a room — measured, 28 files of a building's common areas came back as one imaginary room until this split |
| `results` is keyed by `id(g)` | Not by `g.name`, which is a property over `g.ambiente` and therefore changes the instant an answer is applied. Keying on it made every corrected room read as unverified afterwards |
| Type A is protective, not cosmetic | A delivery profiled as already-culled gets **no quota and no cuts**. Loosening that would let the system re-cut somebody's finished selection |
| `vision.py` never kills a run | It returns a `Verdict` or a `Classification` carrying an error instead of raising. A failed room keeps the filename's word and says so in the sheet's header and the catalogue |
| No structured output on the endpoint | `fal-ai/any-llm/vision` returns free text. The JSON contract is instructed in the prompt and validated here — `ask(parse=...)` takes the validator so the retry covers the *shape* of the answer, not just its syntax |
| Tournament reconciliation | A frame dismissed in a heat can win the final and end up in both lists. The final call saw the real competition, so `choose()` filters the rejection list against the picks |
| Free to test | `cull.py --no-classify` (and without `--vision`), `--profile-only`, `ambientes.py` on a label, and `vision.py --room X` for one room |

## `0 - selection/develop.py`

| | |
|---|---|
| Depends on | `picks.txt` (one scene per line, `+` joining a bracket), `ambientes.md` for every name it writes, `source/`, and `1 - input/` existing |
| Depended on by | Nothing. It is the end of this stage |
| Refuses to run without `ambientes.md` | The names come from there and are not re-derived. Guessing would put a room name nobody verified onto a file that goes to a client, so a missing catalogue or an uncatalogued pick stops the run before anything is written |
| Assigns the photo number, and nothing else about the name | The ambiente and the room were settled by `cull.py`. The number restarts per room and follows `picks.txt` order — it cannot be assigned earlier, because only here is it known which photos survived, and numbering before that leaves gaps where the unpicked ones were |
| Deliberately does not | Re-apply the quota, skip a flagged frame, or reconsider a pick. **The human's list is final.** Adding a filter here would silently overrule the gate this whole stage exists to provide |
| Output size | 2400 px long edge, because `enhance.py` downscales its upload to 2048 anyway. Carrying 6000 px through a stage that discards the pixels buys nothing |
| Refuses to | Fuse frames of different sizes — that means a `+` joined two unrelated photographs, not a bracket. Or write anything at all if a `picks.txt` line names a missing file |

## The three stage folders (`1 - input`, `2 - in progress`, `3 - completed`)

The folder names are load-bearing — they are hardcoded in both scripts.

| | |
|---|---|
| Named in code | `organize.py` (`IN_PROGRESS_DIR`, `COMPLETED_DIR`), `batch.py` (`COMPLETED_DIR`); each script derives its *own* folder from `__file__`, so `1 - input/` and `2 - in progress/` can only be renamed together with the constant that points at them |
| Breaks if renamed | Both scripts, silently — `next_job_id()` stops seeing existing jobs (numbers get reused) and the hand-off/archive moves fail. Rename a folder → grep for the old name → fix both scripts and every `CONTEXT.md` |
| Spaces in the names | Every command in every doc quotes its paths. An unquoted path fails with a confusing "no such file" — keep the quotes when you copy an example |
| Stage boundary | A job's folder location **is** its status. Nothing else records it. Moving a `Job_NNNN/` folder by hand changes what the system thinks is done |

## `1 - input/organize.py`

| | |
|---|---|
| Owns | `Job_NNNN` and `job.md`. **It no longer owns photo names** — that moved to `0 - selection/` on 2026-07-31, and this script now keeps whatever name a photo arrives with, lowercasing only the extension |
| Depended on by | `batch.py` (expects a `job.md` to append to, and the `**Dropped as:**` line to index), `CLAUDE.md` → "Naming convention", `1 - input/CONTEXT.md`, `2 - in progress/CONTEXT.md` → "Input" |
| Format that is parsed | `write_job_md()` emits `**Dropped as:** \`label\`` as its own line. `batch.py`'s `DROPPED_RE` matches that exact shape — change the wording in one and the index silently falls back to `—`. **The only text one script parses out of another's output in this whole system.** The mapping table below it is for humans; nothing parses it |
| Counter | `next_job_id()` scans `1 - input/`, `_originais/` and both later stages for `Job_(\d+)`. `_originais/` is in that list because it keeps a folder per job after the job has left — without it a number could be handed out twice. A job folder renamed out of the pattern becomes invisible and its number gets reused |
| Copies, and preserves the drop | `_originais/Job_NNNN/` holds the delivery as it arrived; the job folder gets copies. The originals **move** there first, so the drop zone is empty even if the copy dies half way — otherwise a re-run would build a second job from the same photos |
| `_originais/` is skipped by name | Not by its underscore. Skipping every `_`-prefixed folder is tidier and silently swallows a drop named one, and a drop this script ignores is a delivery nobody notices is missing |
| Hard-stops on a name collision | Two dropped files wanting the same name. Renaming one out of the way would break the promise that a name survives the pipeline, so it lists them and exits having moved nothing |
| Contract `batch.py` relies on | Source photos are the only images in the folder whose stem contains neither `_edit` nor `_enhanced`. A source named `..._edit.jpg` would be read as a result and never run. Canonical slugs are uppercase and `_edit` is lowercase, so they cannot collide by accident |
| Tolerant of | A missing `job.md` — `batch.py` appends with `"a"`, which creates it. The mapping table is lost, not the run |
| Free to test | Nothing — it always moves the drop. `_originais/` is what makes that recoverable |

## `2 - in progress/PROMPT.md`

**The file you will edit most.** Deliberately so — it is the only surface that
changes how photos come out.

| | |
|---|---|
| Depended on by | `enhance.py` (`load_prompt()` reads it fresh per photo), every `<name>_log.md` in every job (records its text + fingerprint), `2 - in progress/CONTEXT.md` → "Editing PROMPT.md" |
| The fingerprint is now the only trail | A re-run overwrites the `_edit` rather than writing a second fingerprint-tagged file (changed 2026-07-31). The `#xxxxxxxx` in each log is what still answers *which wording produced this image* — do not stop recording it |
| Safe to change freely | All prose **above** the `===== END OF PROMPT` marker. No code parses its structure — headings, bullets, and wording are yours |
| Must not change | The `===== END OF PROMPT` marker line itself. `enhance.py` splits on that exact string and hard-fails without it |
| Changes that need a doc update | Loosening the "add nothing to the room" rule, or the camera-geometry latitude → update the matching bullets in `CONTEXT.md` → "Editing PROMPT.md", which describe both as current policy |
| Changes that need nothing | Rewording, reordering, tightening, adding a correction. Take effect on the next photo — no restart, valid mid-job |
| Guard against self-contradiction | `enhance.py --check` — run after EVERY edit. Free, instant, needs no photo. Lists objects named in both a remove and a keep instruction |
| How to tell what a photo got | The `#xxxxxxxx` fingerprint in its log. Same fingerprint = byte-identical prompt |
| Known hazard: conflicts | An absolute-sounding rule earlier in the file silently outranks a permission later in it. Before making an ignored instruction louder, grep the prompt for what forbids it. Two worked examples in `CONTEXT.md` → "When an instruction is being ignored" |
| Known hazard: example lists | Naming object categories near a staging permission reads as a menu and gets them *added* to the room. Describe what to keep by reference to the photo, never by example |
| Verified 2026-07-26 | Prompt reaches the model in full — API `maxLength` is 32000, ours ~2.0K (rewritten 2026-07-26; 10.5K original at `PROMPT_backup_2026-07-26_v1.md`, 2.6K intermediate at `..._v2_5915027c.md`), and a grayscale sentinel on the last line was obeyed. A missed instruction is never a delivery problem |
| Known hazard: cutting length | Removing a concrete noun in favor of a general principle silently drops the behavior — measured across four revisions, see `CONTEXT.md` → "What actually controls quality is nouns, not length". Cut prose, keep nouns |

The settings table **below** the marker is hand-maintained documentation of
`enhance.py`'s constants. Nothing reads it. If you change a constant, change it
there too, or it lies.

## `2 - in progress/enhance.py`

| | |
|---|---|
| Depended on by | `batch.py` (imports `run`, `ROOT`, `DEFAULT_MODEL`; catches any `Exception` per photo) |
| Where results go | `run(..., out_dir=None)` defaults to the **photo's own folder**. That default is what keeps a job self-contained; pass `out_dir` only to send results somewhere else deliberately |
| Constants documented in two places | `CONTEXT.md` → "Config" table **and** `PROMPT.md`'s settings table. Change a constant → update both |
| Timings quoted in docs | `CONTEXT.md` → "Speed" table cites measured numbers from `006.jpg`. If `UPLOAD_LONG_EDGE` or `QUALITY` changes, those numbers no longer describe reality |
| Cost quoted in docs | `CLAUDE.md` → "Running it" says ~$0.06/image. True only at `QUALITY = "medium"` and ~2K. Change either → fix that line |
| Contract `batch.py` relies on | `run()` accepts `emit=` and raises `EnhanceError` instead of exiting. Both are what let one bad photo not kill a job |
| Stays standalone | It never renames, moves, or archives. Runs against any path, including a photo in `3 - completed/` or outside the project |

## `2 - in progress/batch.py`

| | |
|---|---|
| Depends on | `enhance.py`'s `run(photo, model, emit)` signature; `review.py`'s `write()`, `REVIEW_NAME`, `REWORK_NAME`; `organize.py`'s `Job_NNNN` folder naming |
| Depended on by | `CLAUDE.md` → "Running it", both `CONTEXT.md` files (all quote its flags) |
| Owns | Job selection (`--job`, else lowest-numbered), the skip-if-an-`_edit`-exists rule, the run entry appended to `job.md`, `--rework`, `--approve`, the move to `3 - completed/`, `3 - completed/index.md`, `WORKERS` |
| **Does not archive on its own** (since 2026-07-31) | A finished run writes `review.html` and stops. "The API answered" and "this is good enough to send a client" are different questions and a script can only answer the first. Only `--approve` moves a job |
| The archive rule | `--approve` refuses unless every photo has an `_edit`. Not to second-guess the person approving, but because a photo with no edit has nothing to show and so never appears on the review page — archiving that job would put it beyond the stage that can fill the hole |
| `--rework` has no machinery | It deletes the rejected `_edit.jpg` files, and deleting one is what makes the ordinary skip rule run that photo again. No retry list, no state file, nothing that can disagree with disk |
| `RESULT_MARKERS` keeps `_enhanced` for good | The 22 jobs archived before 2026-07-31 used that suffix. Drop it from the tuple and `--reindex` reads their results as sources |
| `photo_count()` ≠ `len(photos_in())` | The index counts photographs by identity — a photo counts if it survives as a source, a result, or both. Several archived jobs had their sources deleted by hand, and counting sources made `--reindex` overwrite an accurate row with a zero |
| Breaks if | A job folder holds a source whose stem contains `_edit` (read as a result, never run), or `3 - completed/Job_NNNN` already exists (refuses rather than merging) |
| Deliberately does not | Grade a result. It builds the page a person grades on and stops there — see "The no-inspection rule" below |

## `2 - in progress/review.py`

| | |
|---|---|
| Depended on by | `batch.py` (imports `write`, `REVIEW_NAME`, `REWORK_NAME`), `2 - in progress/CONTEXT.md` → "The gate", `CLAUDE.md` → routing |
| Owns | `review.html`'s markup, styling and clipboard behaviour, and the name `rework.txt` |
| Why a clipboard and not a file | A browser page cannot write into the folder it sits in, and a download landing in `~/Downloads` would be worse than a copy button. Same constraint, same answer, as `contact.html` |
| Why the images are large | It compares exactly two photographs, not fifty to each other. The contact sheet's 215px thumbnail is right there and wrong here — a subtly wrong edit does not survive a thumbnail |
| Holds a copy of `NAME_RE` | Only to group by ambiente. See "Naming convention" below for every copy |
| Approval is a command, not a file | The page copies the `--approve` command to the clipboard. Nothing on it can archive a job, so no stray click can |
| Free to test | Yes — `batch.py` rewrites the page on every run and on `--rework`, and it costs nothing |

## The no-inspection rule (2026-07-28)

**Results are handed over as-is. Nothing in this system reads an enhanced photo
back against its source** — not the scripts, not the agent. The user judges the
photos on their own screen.

| | |
|---|---|
| Amended 2026-07-31 | The rule is about **who** judges, not about whether anyone does. There is now a formal place for it: the job's `review.html`, which `batch.py` writes and then stops at. What is unchanged is that the scripts and the agent do not grade a photo, and the agent never runs `--approve` on its own initiative |
| Stated in | `CLAUDE.md` → "Running it" (last paragraph) and `2 - in progress/CONTEXT.md` → "The gate". Both must agree |
| Removed to make room for it | `2 - in progress/CONTEXT.md` → the whole "Check before you hand it over" section (the reject list, the side-by-side border read, the settled-policy notes), plus the closing reminders in `batch.py` → `finish()` and `enhance.py` → `main()`. `finish()` lost its `count` parameter with them |
| What survived, and where | The framing-failure evidence → `CONTEXT.md` → "The pull-back is gone"; lawns/planting + people/vehicles as intended behavior, and clipped-stays-clipped, → `CONTEXT.md` → "Editing PROMPT.md" bullets; the switch-models fallback → same file → "Config" |
| Breaks if reintroduced | Any file that tells the agent to open, compare, or grade a result contradicts `CLAUDE.md`. Fix the feedback loop through `PROMPT.md` instead — it applies to every future photo |
| The one live feedback path | The user reports a repeated failure → tighten `PROMPT.md` → `enhance.py --check` → next run |

## `3 - completed/index.md`

| | |
|---|---|
| Written by | `batch.py` → `add_to_index()` on every archive, `rebuild_index()` on `--reindex`. Nothing else writes it and nothing reads it but a human |
| Depends on | `organize.py`'s `**Dropped as:**` line for the label; the `Job_NNNN` folder name pattern; `batch.py`'s `photo_count()`; each job folder's mtime for the "Finished" date |
| Not the source of truth | The folders are. A row can go stale (job renamed, moved, deleted by hand) and nothing will notice — `--reindex` rebuilds the file from what is actually in the folder |
| Safe to hand-edit | Yes, but `--reindex` overwrites the whole file. Put anything worth keeping in the job's own `job.md` instead |
| Header text lives in code | `INDEX_HEADER` in `batch.py`. Editing the header in the file only lasts until the next `--reindex` |
| Non-job folders | Listed in a footnote under the table (currently `Test/`), because a table of jobs alone would read as a complete picture of the folder when it isn't. `add_to_index()` inserts new rows *above* that footnote — the insert position matters |

## Naming convention (`AMBIENTE_NN_NNNN.jpg` + `_edit.jpg` / `_log.md`)

Rewritten 2026-07-31. Was `Job_NNNN/Photo_NNNN` + `_enhanced.jpg`, decided in
`1 - input/organize.py`; is now decided in `0 - selection/` and never changed again.

| | |
|---|---|
| Defined in | `CLAUDE.md` → "Naming convention" |
| Vocabulary | `_config/Seletor/AMBIENTES.md` — see its own section above |
| Implemented in | `ambientes.py` → `NAME_RE`, `parse_name()`, `format_name()`, `number_rooms()`, the catalogue; `cull.py` → `group_rooms()`, `classify_rooms()`; `develop.py` → `assign_names()` |
| Assumed by | `organize.py` → `target_name()`, `find_collisions()` (and it warns on a name that does not match); `batch.py` → `photos_in()`, `is_done()`, `strip_result()`, `photo_count()`; `review.py` → `group_key()`; `enhance.py` derives every output name from `photo.stem` and assumes nothing at all about its shape |
| **`NAME_RE` exists in three files** | `0 - selection/ambientes.py` is the owner; `1 - input/organize.py` and `2 - in progress/review.py` hold copies, because a sibling folder whose name has spaces in it cannot be imported. **Grep for `NAME_RE` before changing the shape of a name** — that grep is the only thing keeping the three in step |
| Slug and suffix cannot collide | Slugs are uppercase, `_edit` is lowercase. That is what makes `"_edit" in stem` a safe test for "this is a result" |
| Breaks if | A folder is renamed out of the `Job_NNNN` pattern, a job is moved between stages without its `job.md`, or a shoot's `ambientes.md` is deleted before `develop.py` runs (it refuses rather than guessing) |
| Deliberately lossy | Original filenames survive in `job.md` and in `1 - input/_originais/`. Less lossy than it was — the room is now in the name itself — but `job.md` is still the only record of the photographer's own filename, and now also the only record of the walkthrough order |

---

## Known loose ends

Not wired into anything — noted so nobody mistakes them for live parts:

- `logs/error.log`, `logs/combined.log` — nothing in this project writes them.
  Stray, gitignored, safe to delete.
- `3 - completed/Test/` — every photo processed before the job structure existed
  (2026-07-25/26), moved here as-is from the old `output/` folder. Flat
  `{id}_enhanced.jpg` naming, no `job.md`, and its logs cite the old
  `input/` and `output/` paths. Read-only history; the scripts ignore it because
  it does not match `Job_NNNN`.
- Inside it, `sample_sofaview_prompt.md` and `001_enhanced_1.jpg` /
  `002_enhanced_2.jpg` are leftovers from the earlier per-photo-prompt design.
  Harmless; safe to delete.
- `2 - in progress/_archive/dry_run.py` — the `--dry-run` code pulled out of
  `enhance.py` and `batch.py` on 2026-07-27, kept verbatim for reference.
  Nothing imports it; safe to delete once nobody needs to bring the flag back.
