# Selection rules

_Last updated: 2026-07-31_

The one tuning surface for `0 - selection/cull.py`, the way `PROMPT.md` is the one
tuning surface for the enhance stage. Read fresh on every run, so an edit lands on
the next run without restarting anything.

**When the selection makes the same mistake twice, change this file** — not the
picks. A wrong pick fixed by hand is wrong again on the next property; a rule
fixed here is fixed for every property after it.

Distilled from `Short-Term Rental Photo Culling and Selection Strategy.md`, which
sits beside this file as the source. That document is 187 lines of argument; this
is the part a script can act on.

---

## Quota

How many photos the gallery should hold, and how they are spread.

    base per room:      3
    gallery target:     40-60

**Three per room is the floor, not the cap.** It comes from the process this
project's own team was already running by hand, and it is a good floor because it
forces every room to be *shown* rather than merely mentioned. The gallery target
is what the whole set has to land in; rooms get extra slots to reach it.

    1. base   = min(base per room, distinct angles that room actually has)
    2. under  -> expand, highest priority category first
    3. over   -> trim, lowest priority first
    4. floor  -> a room with any photo delivered never ends at zero

Expansion and trimming both stop at distinct angles available. Neither invents a
photograph, and neither drops a room entirely.

### Expansion priority

Which rooms get the extra slots.

**Since 2026-07-31 the category arrives from `AMBIENTES.md`**, which gives every
canonical ambiente one of the twelve categories below; this table is then read for
**category → priority**. So a room's category is now decided by a name that was
checked against the picture, rather than by matching keywords against whatever the
photographer typed.

The keyword column is still live and still matters. It is the fallback for a room
with no ambiente yet — which is every room during the provisional pass, before the
naming has run — so an unmatched room still falls to `default` priority and is
listed in the run's report, never silently absorbed.

**To change which rooms get the spare slots, edit the priority numbers here. To
change what a room is called, edit `AMBIENTES.md`.** Matching in both files uses
the same rule: case- and accent-insensitive, and the keyword nearest the *start* of
the label wins, not the longest one.

| Priority | Category | Keywords |
|---|---|---|
| 1 | hero_outdoor | cobertura, terraço, terraco, piscina, jardim, quintal, deck, churrasqueira, gourmet externo, vista |
| 2 | social | sala, living, estar, jantar, home theater, tv |
| 3 | kitchen | cozinha, gourmet |
| 4 | master | suíte 1, suite 1, suíte master, suite master, suíte principal, suite principal |
| 5 | bedroom | quarto, suíte, suite, dormitório, dormitorio |
| 6 | common | condomínio, condominio, portaria, academia, salão, salao, playground, piscina comum, lazer |
| 7 | bathroom | banheiro, wc, banho, toalete |
| 8 | outdoor_small | sacada, varanda, balcão, balcao, terracinha |
| 9 | secondary | copa, despensa, closet, escritório, escritorio, adega, garagem, vaga |
| 10 | service | área de serviço, area de servico, lavanderia, serviço, servico |
| 11 | passage | escada, corredor, hall, entrada, porta, lavabo, circulação, circulacao |
| 99 | default | *(anything unmatched)* |

### Volume by typology

The gallery target above is a default that suits a mid-to-large property. The
source document scales volume with floor area, and padding a small property to a
big gallery backfires — it "realça a falta de área útil", it advertises how little
there is. When the room count suggests a small property, the run says so.

| Typology | Rooms, roughly | Target |
|---|---|---|
| T0-T1 | up to 5 | 15-25 |
| T2-T3 | 6 to 10 | 25-35 |
| T4+ | 11 or more | 40-50 |

### Interior / exterior ratio

Reported, not enforced — enforcing it would fight the quota. The document's
heuristic:

| Setting | Interior | Exterior |
|---|---|---|
| urban | 85% | 15% |
| suburban | 70% | 30% |
| leisure | 50% | 50% |

---

## Geometry thresholds

Measured from pixels by `0 - selection/ingest.py`, not read from EXIF, so these
work on files whose metadata was stripped.

    roll warn:           3.0
    roll flag:           5.0
    convergence warn:   12.0
    convergence flag:   20.0
    focal flag:           16
    focal warn:           20

Calibrated against a real 307-photo delivery from one of this project's own
photographers, after the measurement itself was made trustworthy:

| | p50 | p75 | p90 | p95 |
|---|---|---|---|---|
| roll | 0.47° | 1.24° | 3.73° | 7.05° |
| convergence | 1.69° | 4.87° | 13.51° | 23.98° |

So `flag` sits around p93–p95 — genuinely unusual **for that photographer**, which
is the only comparison that means anything. **Re-measure when a new photographer
starts sending work.** A tripod-and-shift shooter and a run-and-gun shooter do not
share a baseline, and a threshold carried over from the wrong one is worse than no
threshold.

`focal` is in 35mm-equivalent millimetres and only applies when that is actually
knowable. The 307-photo delivery above carried **no EXIF at all**, so it never
fired once. Focal length cannot be recovered from pixels; when this rule matters,
ask the photographer to export with metadata intact.

---

## Narrative order

The gallery sequence, from the source document's closing section. When the
photographer numbers their own files, **their numbering wins** — they walked the
property once and numbered as they went, which is better evidence of the route
than anything inferred.

1. **Hero five** — cover (highest-value view of the property), main living space,
   kitchen, master suite, one lifestyle detail
2. Entrance, hall, approach
3. Social spaces
4. Kitchen and dining
5. Bedrooms, **each followed immediately by its own ensuite**
6. Remaining bathrooms
7. Exterior, then neighbourhood
8. Logistics details last — thermostat, lock, parking, storage

---

===== VISION PROMPT — everything below IS sent to the model =====

You are curating photographs for a short-term rental listing. You will be shown
several photographs of ONE room of ONE property, and you must choose the best few.

Choose on these grounds, in this order of importance:

1. **Purpose of the room.** Does the photograph make the room's function
   immediately obvious — comfort in a bedroom, workability in a kitchen, space to
   gather in a living room, leisure outdoors? A photograph that could be any room
   is worth less than one that could only be this one.

2. **Spatial legibility.** Can a guest work out the shape and size of the room
   from it? A frame showing the meeting of two or three walls, floor to ceiling,
   tells them where they are. A tight corner crop does not, however pretty.

3. **Staging and order.** Do the furniture, objects and the chosen angle make the
   room read as spacious and cared for? Clutter is the enemy: cables trailing
   across a counter, bottles and cleaning products on display, dish cloths,
   toiletries, anything dropped on the floor.

4. **Contribution to the tour.** Prefer a set that shows the room from
   *complementary* angles over several near-repeats of the strongest one. Three
   photographs that each add something beat three excellent versions of one view.

Reject outright, no matter how attractive the photograph is otherwise:

- An open or prominent toilet. Bathroom photographs should lead with the vanity,
  the shower or the bath; the toilet belongs cropped out or lidded and marginal.
- A bed that reads as unmade — creased duvet, slack sheets, pillows at different
  heights, textiles rumpled.
- Visible clutter that no amount of editing removes, per point 3.
- Verticals that visibly fall backwards or splay — walls and door frames leaning
  as if the building were collapsing inward.
- A view so wide that near objects are grotesquely stretched at the frame edges.
- A photograph too blurred to be usable.

Levelness and lens geometry are measured from the pixels for you and supplied
with each photograph as a plain verdict — `level`, `verticals splay badly`,
`FAULT: ...`. **Take those as given.** They are more reliable than an impression
of a photograph you are seeing at reduced size, and anything marked `FAULT` breaks
one of the rejections above.

Everything else is yours to judge by looking, blur included. Do not invent
measurements or quote degrees back: if a photograph is unusable, say what is wrong
with it in words.

Answer with a single JSON object and nothing else — no prose before or after, no
markdown fence:

{"picks": [{"file": "<exact filename>", "rank": 1, "purpose": 0-10,
            "staging": 0-10, "reason": "<one short sentence>"}],
 "rejected": [{"file": "<exact filename>", "why": "<short reason>"}]}

Rules for the answer:

- `picks` holds at most the number of slots you are told this room has, ordered
  best first. Return fewer if fewer deserve it — an empty slot is better than a
  bad photograph, and you will be told if a room ends up short.
- `file` must be copied exactly from the filename given with each image. Do not
  abbreviate, translate or re-number it.
- `reason` and `why` must be written **in Brazilian Portuguese**, because they are
  read by the person reviewing the selection and are shown to their client. Say
  what the photograph does or fails to do, concretely: "mostra o triângulo de
  trabalho inteiro com a bancada limpa", not "boa foto".
- `rejected` is for photographs that hit one of the outright rejections above.
  You do not need to list everything you simply did not pick.

===== END OF RULES — everything below is NOT used by any script =====

## How this file is read

`0 - selection/cull.py` reads it fresh on every run and takes:

- the `key: value` lines under **Quota** and **Geometry thresholds** (indented
  four spaces, one per line)
- the **Expansion priority** table, both ways: as category → priority (the way it
  is used now) and as keyword → category → priority (the fallback)
- the **Volume by typology** table
- everything between the `===== VISION PROMPT` and `===== END OF RULES` markers,
  verbatim, as the instruction sent to the vision model when it ranks a room's
  photographs

The *other* vision prompt — the one that decides what a room is called — lives in
`AMBIENTES.md`, not here. Two files, two questions: this one is about which
photographs are good, that one is about what they are of.

The two `=====` marker lines must stay exactly as they are. `cull.py` refuses to
run without them rather than risk sending this documentation to the model as part
of the prompt — the same guard `enhance.py` puts on `PROMPT.md`.

## What depends on this file

See the `0 - selection/` section of `_dependencies.md` at the project root.
Changing the quota changes how many photos every future gallery holds; changing
the vision prompt changes which ones. Neither is retroactive — a delivery already
sitting in `0 - selection/` keeps its `selection.md` until you re-run `cull.py`
on it.
