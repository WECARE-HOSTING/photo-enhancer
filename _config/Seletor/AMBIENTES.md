# Ambientes

_Last updated: 2026-07-30_

The canonical vocabulary for room names. Every photo that leaves
`0 - selection/` is named after one of the slugs in the table below —
`QUARTO_02_0001.jpg` — and keeps that name through `1 - edit/`,
`2 - marca dagua/` and `3 - completed/`. Nothing renames it again.

Read fresh on every run of `0 - selection/cull.py`, the way `RULES.md` is, so an
edit here lands on the next run.

**When a photographer's word maps to the wrong ambiente twice, add it to the
Synonyms column** — not to the catalogue of a single shoot. A synonym fixed here
is fixed for every property after it.

---

## The vocabulary

The `Ambiente` column is the slug that becomes the filename: **UPPERCASE, A-Z and
`_` only, no accents, no digits.** Digits are what tell the name apart from the
numbers that follow it, so a slug must never contain one.

The `Categoria` column is one of the twelve categories `RULES.md` already
defines, and it is the *only* thing the quota reads. Slots and expansion priority
stay `RULES.md`'s decision — this file decides what a room is *called*, not how
many photos it gets.

`Sinônimos` is what the photographer might write. Matched case- and
accent-insensitively, and **by where the word appears in the label, not by how
long it is** — the same rule `RULES.md` uses, for the same reason: room names put
the noun first and the qualifier after, so `Sala Cobertura` is a living room *in*
the penthouse (`SALA`), not a roof terrace.

| Ambiente | Categoria | Sinônimos |
|---|---|---|
| FACHADA | hero_outdoor | fachada, frente, frontal, entrada externa, exterior, prédio, predio |
| VISTA | hero_outdoor | vista, panorâmica, panoramica, paisagem, skyline, mirante |
| PISCINA | hero_outdoor | piscina, deck, solário, solario, borda infinita |
| TERRACO | hero_outdoor | terraço, terraco, cobertura, rooftop, laje |
| JARDIM | hero_outdoor | jardim, quintal, gramado, pátio, patio, horta |
| CHURRASQUEIRA | hero_outdoor | churrasqueira, gourmet externo, espaço gourmet, espaco gourmet, varanda gourmet |
| SALA | social | sala, living, estar, sala de tv, home theater, tv, convivência, convivencia |
| JANTAR | social | jantar, sala de jantar, copa, mesa de jantar |
| COZINHA | kitchen | cozinha, gourmet, cozinha americana, cooktop |
| SUITE | master | suíte master, suite master, suíte principal, suite principal, suíte 1, suite 1, master |
| QUARTO | bedroom | quarto, dormitório, dormitorio, suíte, suite, cama |
| BANHEIRO | bathroom | banheiro, banho, wc, toalete, box, chuveiro |
| LAVABO | passage | lavabo |
| VARANDA | outdoor_small | varanda, sacada, balcão, balcao, terracinha |
| ESCRITORIO | secondary | escritório, escritorio, home office, estúdio, estudio, biblioteca |
| CLOSET | secondary | closet, vestiário, vestiario, guarda-roupa |
| GARAGEM | secondary | garagem, vaga, estacionamento, box carro |
| DESPENSA | secondary | despensa, adega, depósito, deposito, storage |
| AREA_SERVICO | service | área de serviço, area de servico, lavanderia, serviço, servico, tanque |
| HALL | passage | hall, entrada, recepção interna, antessala, circulação, circulacao, corredor, porta |
| ESCADA | passage | escada, escadaria, degraus |
| ACADEMIA | common | academia, fitness, musculação, musculacao |
| SALAO_FESTAS | common | salão de festas, salao de festas, salão, salao, festas, brinquedoteca |
| PLAYGROUND | common | playground, parquinho, quadra |
| PORTARIA | common | portaria, lobby, recepção, recepcao, guarita |
| DETALHE | default | detalhe, decoração, decoracao, objeto, acabamento |
| NAO_IDENTIFICADO | default | *(nothing matched, and no model confirmed one)* |

`SUITE` before `QUARTO` is deliberate and it is the one pair the keyword rule
cannot separate on its own: every suite is also a bedroom, so the qualifier —
`master`, `principal`, `1` — is what distinguishes them, and it sits *after* the
noun. When the label is bare `Suíte 2` the position rule lands on `QUARTO`, which
is right: only the master gets `SUITE`.

`porta` under `HALL` is safe next to `PORTARIA` only because ties on position are
broken by the longer keyword: both match `Portaria` at position 0, and `portaria`
is longer. Adding a synonym that is a *prefix* of another one is fine for that
reason; adding one that is a prefix and *earlier in the label* is not.

**`condomínio` is deliberately not a synonym of anything.** A folder named
`3_Condomínio/` holds the gym, the lobby, the party room and the pool deck all at
once, so mapping the folder's name to one ambiente would confidently mislabel most
of it. With no keyword to match it falls to `NAO_IDENTIFICADO` and the vision pass
names each photo on its own — which is the whole point of having one. Resist the
urge to add it.

## Property codes — words that look like rooms and are not

A delivery arrives inside a folder named after the property, and that name is not
evidence of a room. When the filenames carry no room of their own, `cull.py` falls
back to the folder — so a property code that happens to contain a room word gets
read as the room, for every photograph in the delivery at once.

The codes below are stripped out of a label before any synonym is matched.

| Código | O que é |
|---|---|
| `WC-N` | WeCare property reference — **`WC` is WeCare**, not *water closet* |

`N` means *one or more digits*, so `WC-N` matches `WC-00660` and also `WC-660`.
Deliberately not pinned to five digits: a shorter legacy reference would slip
through a stricter pattern and be read as a bathroom, which is the exact failure
this table exists to stop.

**The `wc → BANHEIRO` row in the vocabulary above is correct and must stay.** In
Portuguese a WC *is* a bathroom, and a photographer who names a folder `WC 2`
means one. The two readings genuinely collide, and the collision is resolved by
shape, not by deleting one of them: `WC` followed by a hyphen and digits is a
property reference, `wc` anywhere else is a bathroom. Measured on 2026-07-31:
a 48-photo house arrived as one `BANHEIRO` because its folder was
`WC-00660 - Casa MAD Alter`.

Add a row here when a new client's reference format contains a room word. A code
that contains none — `AP-1204`, `IMOVEL_88` — needs no row, because nothing in the
vocabulary matches it anyway.

---

===== CLASSIFY PROMPT — everything below IS sent to the model =====

You are looking at photographs of ONE room of ONE property, and your job is to
say which room it is, choosing from a fixed list of names you will be given.

The photographer usually names their own files, and their label will be shown to
you. **They are right most of the time, so agree unless you can see that they are
wrong.** You are the check on their labelling, not a second opinion for its own
sake — changing a correct label is worse than leaving it alone, because the name
you return becomes the filename delivered to a client.

Change it when the pictures plainly show something else. The things that actually
get mislabelled:

- A `Lavabo` (guest cloakroom — a basin and a toilet, no shower and no bath) that
  turns out to have a shower box or a bath, which makes it a `BANHEIRO`.
- A bedroom that is really the master suite. `SUITE` is for **one** room in a
  property and one only: the master. If the photographer's label carries a number
  and that number is not 1, the answer is `QUARTO` — however well appointed the
  room is, however many built-in wardrobes it has, however good the view from its
  balcony. `Suíte 3` is the third bedroom, not a second master. Do not promote it.
- A `Sala` that is really a dining room (`JANTAR`), or a dining area photographed
  from the living room and labelled as one.
- A `Varanda` (small balcony off a room) that is really a `TERRACO` (a large open
  roof area) or has a grill in it (`CHURRASQUEIRA`).
- Anything shot in the building's common areas — gym, lobby, party room, pool
  deck — filed under the apartment's own rooms, or the reverse.
- A `Quarto` with a desk that is actually an `ESCRITORIO`, when there is no bed.

Judge by what the room is *for* and what is fixed in it — plumbing, cabinetry, a
bed, a cooktop — not by the decor or how nice it looks.

You will be shown several photographs that are believed to be the same room. If
one of them is plainly a different room from the others, list it separately
instead of letting it change the answer for the whole set. That happens when a
photographer's folder holds one stray file.

If the pictures do not let you tell — too dark, too tight a crop, an empty white
wall — say so by returning `NAO_IDENTIFICADO` rather than guessing. An honest
unknown is fixed by a person in a few seconds; a confident wrong answer is not.

Answer with a single JSON object and nothing else — no prose before or after, no
markdown fence. **Which shape you answer with is stated in the request**, and it is
one of these two.

**Confirming one room** — the usual case, when a label exists:

{"ambiente": "<a name from the list>",
 "corrigido": true|false,
 "porque": "<one short sentence, only when corrigido is true>",
 "estranhos": [{"file": "<exact filename>", "ambiente": "<a name from the list>",
                "why": "<short reason>"}]}

- `ambiente` must be copied exactly from the list of names you are given. Do not
  invent one, translate it, or change its spelling or case.
- `corrigido` is `true` only when your answer differs from the name the
  photographer's label was mapped to. Leave `porque` out when it is `false`.
- `estranhos` is only for images that show a *different room* from the rest of the
  set. It is not for images you think are badly shot — that is a different
  question, asked elsewhere. Return an empty list when they all belong together.

**Naming every image** — when the request says the photographs are *not* known to
be one room. Then there is no label to confirm and no premise to defend: name each
one on its own, and expect the set to hold several different places.

{"ambiente": "<the name that fits most of them>",
 "ambientes": [{"file": "<exact filename>", "ambiente": "<a name from the list>",
                "why": "<short reason>"}]}

- `ambientes` must have **one entry per image shown**, in the order they were
  listed, with the filename copied exactly.
- `ambiente` is still required: make it whichever name covers the largest number
  of them. It is used only as a fallback for an image you failed to name.
- Do not force them to agree. A folder of a building's common areas holds a gym, a
  lobby, a pool deck and a party room, and calling all four the same thing is the
  mistake this shape exists to avoid.

In both shapes, `porque` and `why` must be written **in Brazilian Portuguese**,
because they are read by the person reviewing the shoot. Say what you saw: "tem box
com chuveiro, então é banheiro completo", not "classificação corrigida".

===== END OF AMBIENTES — everything below is NOT used by any script =====

## How this file is read

`0 - selection/ambientes.py` reads it fresh on every run and takes:

- the **vocabulary** table, as ambiente → categoria + synonyms
- everything between the `===== CLASSIFY PROMPT` and `===== END OF AMBIENTES`
  markers, verbatim, as the system prompt for the classification pass

The two `=====` marker lines must stay exactly as they are. `ambientes.py`
refuses to run without them, rather than risk sending this documentation to the
model as part of the prompt — the same guard `cull.py` puts on `RULES.md` and
`enhance.py` puts on `PROMPT.md`.

The list of valid names is **not** written into the prompt above. It is built
from the table and supplied with each call, so adding a row here is all it takes
for the model to be allowed to return it.

## What depends on this file

See the `0 - selection/` section of `_dependencies.md` at the project root.

Renaming a slug here changes the filename of every photo delivered after the
change, and it is not retroactive: a job already in `1 - edit/` or
`3 - completed/` keeps the names it was given. Adding a synonym or fixing a
categoria is safe at any time.
