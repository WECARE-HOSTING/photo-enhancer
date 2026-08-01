#!/usr/bin/env python3
"""The canonical room vocabulary, and the filename built out of it.

    ./_config/.venv/bin/python "0 - selection/ambientes.py"          # show the list
    ./_config/.venv/bin/python "0 - selection/ambientes.py" "Sala Cobertura"

This module owns one thing: **what a photo is called.** The vocabulary lives in
`../_config/Seletor/AMBIENTES.md`, read fresh on every run; this file turns a
photographer's free text into a slug from that list, numbers the rooms, and reads
and writes the per-shoot catalogue `ambientes.md`.

The name it produces travels untouched from here to `3 - completed/`:

    AMBIENTE _ NN _ NNNN .jpg           QUARTO_02_0001.jpg
    AMBIENTE _ NN _ NNNN _edit .jpg     QUARTO_02_0001_edit.jpg

    AMBIENTE  a slug from AMBIENTES.md — uppercase, no digits
    NN        which physical room of that kind, in walkthrough order
    NNNN      the photo within that room, assigned once the picks are known

Nothing downstream renames it. `1 - edicao/enhance.py` only appends `_edit` and
`2 - marca dagua/marca.py` only `_final`.
"""

from __future__ import annotations

import hashlib
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

SELECTION_DIR = Path(__file__).resolve().parent
ROOT = SELECTION_DIR.parent
AMBIENTES_PATH = ROOT / "_config" / "Seletor" / "AMBIENTES.md"

PROMPT_START = "===== CLASSIFY PROMPT"
PROMPT_END = "===== END OF AMBIENTES"

# A slug is uppercase letters and underscores, never a digit — the digits are what
# separate the name from the numbers that follow it. `[A-Z][A-Z_]*` greedily eats
# `AREA_SERVICO` and stops at the first digit group, which is why the two numeric
# fields can be anchored at the end without ambiguity.
SLUG_RE = re.compile(r"^[A-Z][A-Z_]*$")
NAME_RE = re.compile(r"^(?P<ambiente>[A-Z][A-Z_]*)_(?P<sala>\d{2})_(?P<n>\d{4})$")

# This is the only NAME_RE in the project. There used to be three — copies in
# `organize.py` and `review.py`, justified by "a sibling folder whose name has
# spaces cannot be imported", which was never true: every stage already inserts
# a path and imports across. Keeping it that way is a one-line grep:
#     grep -rn "NAME_RE" --include=*.py .

UNKNOWN = "NAO_IDENTIFICADO"
CATALOG_NAME = "ambientes.md"

# Suffixes a result carries, longest first so `_edit_1` is tried before `_edit`.
# Kept in step with `_config/stage.py`'s RESULT_MARKERS: a stem this fails to
# strip returns None from parse_name, and every such photo collapses into one
# unnamed section on the gate page.
RESULT_SUFFIX_RE = re.compile(r"(_edit|_final|_enhanced)(_\d+)?$")

# A property-code row in AMBIENTES.md, written the way a person describes the
# format rather than as a regex: `WC-N`, where `N` stands for the digits. Two
# cells, so the vocabulary loop above — which wants three — skips these rows and
# this one skips the vocabulary's.
CODE_ROW_RE = re.compile(r"^`(?P<prefix>[A-Za-z][A-Za-z_]{0,7})(?P<sep>[-_ ]?)N+`$")


class AmbientesError(Exception):
    """AMBIENTES.md is missing or unusable. Fatal — there is no safe default."""


def fold(s: str) -> str:
    """Lowercase and strip accents, so `Terraço` matches the keyword `terraco`.

    For **keywords**, where losing the accent is the point. Also the key used by
    `Rules.category()` in `cull.py`, which imports it from here so there is one copy.
    Never use it on a filename — that is `fold_name`.
    """
    return "".join(c for c in unicodedata.normalize("NFD", s.lower())
                   if unicodedata.category(c) != "Mn")


def fold_name(name: str) -> str:
    """Compare **filenames**: compose the accents, ignore case and stray space.

    A different job from `fold` above and deliberately weaker: it keeps `Suíte`
    distinct from `Suite`, because those could be two real files, and only fixes
    the one difference that is never meaningful — macOS stores `í` decomposed while
    a browser, a clipboard or a person types it composed. `_dependencies.md` records
    three separate bugs from getting this wrong, so the project has one answer to it
    and this is it: `vision.py` and `develop.py` fold filenames the same way.
    """
    return unicodedata.normalize("NFC", name).casefold().strip()


def parse_name(stem: str) -> "tuple[str, int, int] | None":
    """`QUARTO_02_0001` -> `("QUARTO", 2, 1)`. None when it is not one of ours.

    Tolerates any result suffix, so a caller can ask what ambiente an enhanced or
    watermarked file belongs to without stripping it first. This used to know
    about `_edit` only; a `_final.jpg` returned None and the gate page put every
    photo in one section headed `—`.
    """
    stem = RESULT_SUFFIX_RE.sub("", stem)
    if m := NAME_RE.match(stem):
        return m.group("ambiente"), int(m.group("sala")), int(m.group("n"))
    return None


def format_name(ambiente: str, sala: int, n: int) -> str:
    """`("QUARTO", 2, 1)` -> `QUARTO_02_0001`. No extension."""
    return f"{ambiente}_{sala:02d}_{n:04d}"


# ------------------------------------------------------------- the vocabulary

@dataclass
class Vocabulary:
    """AMBIENTES.md, parsed. `synonyms` is (folded keyword, slug), longest first."""
    order: "list[str]" = field(default_factory=list)
    categories: "dict[str, str]" = field(default_factory=dict)
    synonyms: "list[tuple[str, str]]" = field(default_factory=list)
    codes: "list[re.Pattern]" = field(default_factory=list)
    prompt: str = ""
    fingerprint: str = ""

    def is_valid(self, slug: "str | None") -> bool:
        return bool(slug) and slug in self.categories

    def category(self, slug: "str | None") -> str:
        return self.categories.get(slug or "", "default")

    def strip_codes(self, label: "str | None") -> str:
        """Remove every property reference from a label. Folded, ready to match.

        A property code is not a room, but it can look exactly like one: WeCare
        writes `WC-00660`, and `wc` is a perfectly good synonym of `BANHEIRO`. The
        collision is resolved by shape — a room word followed by a hyphen and
        digits is a reference — and it is resolved *here*, once, so that every
        caller that turns a label into an ambiente is protected rather than only
        the one that was being debugged.
        """
        out = fold(label or "")
        for rx in self.codes:
            out = rx.sub(" ", out)
        return out.strip(" -_")

    def has_code(self, label: "str | None") -> bool:
        """True when a property reference appears anywhere in the label.

        Which makes it the delivery's own wrapper folder — `WC-00660 - Casa MAD
        Alter` — and not a room. The rest of that name is the property's name,
        which is no more a room than the code is. A photographer does not put the
        reference on a bedroom folder; it sits on the one folder wrapping
        everything, which is precisely the one `parse_labels` would otherwise
        mistake for a room when the filenames offer none.
        """
        folded = fold(label or "")
        return any(rx.search(folded) for rx in self.codes)

    def slug_for(self, label: "str | None") -> "tuple[str | None, str | None]":
        """Free text -> (slug, the keyword that matched). (None, None) if nothing.

        Matched by **where** the keyword appears, not by how long it is, and this
        is load-bearing rather than incidental. Room labels put the noun first and
        the qualifier after — `Sala Cobertura` is a living room *in* the penthouse,
        `Lavabo Cobertura` is a cloakroom *in* it — so the keyword nearest the
        start is the one that says what the room actually is. Preferring the
        longest keyword, which is the obvious first instinct, files both of those
        as roof terraces because `cobertura` is longer than `sala` and `lavabo`.

        Ties on position are broken by the longer keyword, which is what lets
        `suíte 1` beat `suíte` and keeps the master suite out of the spare-bedroom
        pile. Same rule, same reasoning, as `Rules.category()` in `cull.py`.

        Property references are removed first — see `strip_codes`. Positions are
        measured on what is left, which is the point: `wc` in `WC-00660` must not
        beat a real room word later in the same label.
        """
        if not label:
            return None, None
        needle = self.strip_codes(label)
        best = None
        for kw, slug in self.synonyms:
            at = needle.find(kw)
            if at < 0:
                continue
            rank = (at, -len(kw))
            if best is None or rank < best[0]:
                best = (rank, slug, kw)
        return (best[1], best[2]) if best else (None, None)

    def list_for_prompt(self) -> str:
        """The valid answers, as the model sees them. Built from the table, never
        written into the prompt by hand, so adding a row is all it takes."""
        return "\n".join(f"- {slug}" for slug in self.order)


def load(path: "Path | None" = None) -> Vocabulary:
    """Parse AMBIENTES.md. Raises AmbientesError with something actionable in it."""
    path = path or AMBIENTES_PATH
    if not path.exists():
        raise AmbientesError(
            f"no vocabulary file at {_rel(path)} — the canonical room names and the "
            "classification prompt both live there")
    raw = path.read_text(encoding="utf-8")

    if PROMPT_START not in raw or PROMPT_END not in raw:
        raise AmbientesError(
            f"{_rel(path)} is missing its `{PROMPT_START}` / `{PROMPT_END}` marker "
            "lines. Without them the documentation below them would be sent to the "
            "model as part of the prompt. Put them back before running.")
    after = raw.split(PROMPT_START, 1)[1]
    prompt = after.split("\n", 1)[1].split(PROMPT_END, 1)[0].strip()
    if len(prompt) < 200:
        raise AmbientesError(
            f"{_rel(path)} has only {len(prompt)} characters of prompt between the "
            "markers — that looks like a bad edit, not a prompt")

    v = Vocabulary(prompt=prompt,
                   fingerprint=hashlib.sha256(raw.encode()).hexdigest()[:8])

    for cells in _table_rows(raw):
        # `WC-N` -> `wc-\d+`. Written with `N` for the digits because this row is
        # edited by whoever knows the client's reference format, not by whoever
        # knows regex. One or more digits, never a fixed width: a shorter legacy
        # reference slipping past a strict pattern is read as a room, which is the
        # failure the table exists to stop.
        if len(cells) == 2 and (m := CODE_ROW_RE.match(cells[0])):
            v.codes.append(re.compile(
                re.escape(fold(m.group("prefix") + m.group("sep"))) + r"\d+"))
            continue
        if len(cells) != 3:
            continue
        slug, category, synonyms = cells
        # The header row says "Ambiente", which is not all-caps, so the shape of a
        # slug is enough to tell data from decoration.
        if not SLUG_RE.match(slug):
            continue
        if slug in v.categories:
            raise AmbientesError(f"{_rel(path)} lists `{slug}` twice — one row per "
                                 "ambiente, or the categoria is ambiguous")
        v.order.append(slug)
        v.categories[slug] = category
        for kw in synonyms.split(","):
            kw = fold(kw.strip().strip("*_()"))
            if kw and "nothing matched" not in kw:
                v.synonyms.append((kw, slug))

    if not v.order:
        raise AmbientesError(
            f"{_rel(path)} has no ambiente rows — the vocabulary table needs "
            "`| SLUG | categoria | synonyms |` lines with the slug in caps")
    if UNKNOWN not in v.categories:
        raise AmbientesError(f"{_rel(path)} has no `{UNKNOWN}` row — it is what an "
                             "unrecognised room falls back to, so it has to exist")
    # Longest first, so a specific keyword is reached before the general one it
    # contains when the positions tie.
    v.synonyms.sort(key=lambda t: -len(t[0]))
    return v


def _table_rows(raw: str) -> "list[list[str]]":
    """Every markdown table row in the text, as stripped cells. Skips separators."""
    out = []
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("|") or not line.endswith("|"):
            continue
        cells = [c.strip() for c in line[1:-1].split("|")]
        if all(set(c) <= set("-: ") for c in cells):
            continue
        out.append(cells)
    return out


# ---------------------------------------------------------------- numbering

def number_rooms(groups: "list") -> None:
    """Set `sala_idx` on each group: which physical room of its kind this is.

    Groups arrive in walkthrough order — the photographer numbered their files as
    they walked the property, which beats anything inferred — so the first bedroom
    they entered is `QUARTO_01`. Mutates the groups; returns nothing.
    """
    seen: "dict[str, int]" = {}
    for g in groups:
        slug = g.ambiente or UNKNOWN
        seen[slug] = seen.get(slug, 0) + 1
        g.sala_idx = seen[slug]


# ------------------------------------------------------------- the catalogue

@dataclass
class Row:
    """One photo in a shoot's `ambientes.md`."""
    ambiente: str       # the answer in force — the column you edit
    visto: str          # what the last run's check actually saw
    sala: int
    label: str          # what the photographer called the room, verbatim
    filename: str       # the source file, as it sits in source/
    source: str         # keyword | filename | vision | manual
    note: str = ""

    @property
    def edited(self) -> bool:
        """True when a person changed `Ambiente` away from what the check saw.

        The two columns exist for exactly this question, and one column cannot
        answer it. A run always writes `Visto` to whatever it just computed, so the
        two agree unless a human pulled them apart — which means a difference is
        proof of an edit, and not, as a single column would suggest, merely proof
        that this run disagreed with the last one. Per-photo classification of an
        unlabelled folder is not deterministic and does disagree with itself
        occasionally; without this, that drift would be recorded as your decision.
        """
        return bool(self.visto) and self.ambiente != self.visto


HEADER = """# {shoot} — Ambientes

_Written by `0 - selection/cull.py` on {stamp}. Vocabulary `AMBIENTES.md` \
`#{fingerprint}`._

Which room every photograph in this shoot is of, and where that answer came from.
The name each picked photo is delivered under is built from this: `SALA` + room
`01` becomes `SALA_01_0001.jpg`.

**`Ambiente` and `Sala` are yours to correct.** Edit either, re-run `cull.py`, and
your value wins. Easier than editing this file by hand: change the room under a
photograph in `review-selection.html` and press **Copy ambientes.md**, which hands you this
whole file with the changed cells already rewritten — paste it back over this one.

- `Ambiente` is *what kind of room* it is. Correcting it turns `Origem` to
  `manual`, and that room is then never sent to the model again.
- `Sala` is *which room of that kind* — the `02` in `QUARTO_02_0001.jpg`. Change
  it to split one room into two, which is the only way to say that two bedrooms
  photographing alike are different bedrooms. Each half then gets its own quota.
  A number you do not touch is recomputed from the grouping, and numbering stays
  dense: write `05` into a shoot with two bedrooms and you get `QUARTO_02`.

  Changing `Ambiente` discards that row's `Sala`, because a room number only means
  something inside the ambiente it was handed out in — a photograph moved from
  `QUARTO_02` to `SALA` joins `SALA_01`, rather than inventing a `SALA_02`.

`Visto` is output, not input, and editing it does nothing useful. It is what the
last run's check actually saw, and it is how your `Ambiente` edit is recognised: a
run always writes `Visto` to whatever it just computed, so the two columns agree
unless *you* pulled them apart. Leave it alone and the difference keeps your
correction alive; overwrite it to match `Ambiente` and the next run will treat the
room as unsettled again, which is how you undo a correction.

The photo number is deliberately not here. The ambiente and the room are facts
about the photograph and are settled now; the number can only be handed out once
the picks are known, or it would arrive full of gaps where the unpicked photos
were. `develop.py` assigns it.

| Origem | Meaning |
|---|---|
| `filename` | The photographer's own label, mapped to the vocabulary and confirmed |
| `vision` | The model disagreed with the label, or there was no label to read |
| `manual` | You wrote it in this file |
| `keyword` | Mapped from the label, **not** confirmed — the vision pass did not run |

{summary}
"""


def write_catalog(shoot: Path, rows: "list[Row]", fingerprint: str,
                  verified: bool, stamp: str) -> Path:
    """Write `<shoot>/ambientes.md`. Returns the path."""
    counts: "dict[str, int]" = {}
    for r in rows:
        counts[r.source] = counts.get(r.source, 0) + 1
    parts = [f"{n} `{src}`" for src, n in sorted(counts.items(), key=lambda kv: -kv[1])]
    summary = f"{len(rows)} photo(s) — " + " · ".join(parts)
    if not verified:
        summary += ("\n\n> **Not verified.** The vision pass did not run, so every "
                    "ambiente below is a keyword guess from the filename. Re-run "
                    "`cull.py` with a `FAL_KEY` in `_config/.env` to have them "
                    "checked against the pictures.")

    head = ["Ambiente", "Visto", "Sala", "Rótulo do fotógrafo", "Arquivo",
            "Origem", "Nota"]
    body = [[r.ambiente, r.visto or "—", f"{r.sala:02d}", r.label or "—",
             f"`{r.filename}`", r.source, r.note or "—"] for r in rows]
    width = [max(len(c) for c in (h, *(b[i] for b in body)))
             for i, h in enumerate(head)] if body else [len(h) for h in head]

    def line(cells: "list[str]") -> str:
        return "| " + " | ".join(c.ljust(w) for c, w in zip(cells, width)) + " |"

    lines = [HEADER.format(shoot=shoot.name, stamp=stamp,
                           fingerprint=fingerprint, summary=summary), "",
             line(head), "|" + "|".join("-" * (w + 2) for w in width) + "|"]
    lines += [line(b) for b in body]
    lines.append("")

    dest = shoot / CATALOG_NAME
    dest.write_text("\n".join(lines), encoding="utf-8")
    return dest


def read_catalog(shoot: Path) -> "dict[str, Row]":
    """Read `<shoot>/ambientes.md` back, keyed by `fold_name` of the filename.

    Returns `{}` when there is no catalogue yet — the first run has nothing to
    honour. Rows whose `Ambiente` cannot be a slug are dropped with the rest of
    the file's prose rather than failing the run: this file is edited by hand, and
    a typo in it should cost one photo's override, not the whole shoot.
    """
    path = shoot / CATALOG_NAME
    if not path.exists():
        return {}
    out: "dict[str, Row]" = {}
    for cells in _table_rows(path.read_text(encoding="utf-8")):
        if len(cells) != 7:
            continue
        ambiente, visto, sala, label, filename, source, note = cells
        if not SLUG_RE.match(ambiente):
            continue
        filename = filename.strip("`")
        if not filename or filename == "—":
            continue
        out[fold_name(filename)] = Row(
            ambiente=ambiente, visto="" if visto == "—" else visto,
            sala=int(sala) if sala.isdigit() else 1,
            label="" if label == "—" else label, filename=filename,
            source=source, note="" if note == "—" else note)
    return out


def _rel(p: Path) -> str:
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)


# ----------------------------------------------------------------------- main

def main() -> None:
    """Show the vocabulary, or test what a label maps to."""
    try:
        v = load()
    except AmbientesError as e:
        sys.exit(f"error: {e}")

    labels = sys.argv[1:]
    if not labels:
        print(f"{len(v.order)} ambiente(s) · AMBIENTES.md #{v.fingerprint}\n")
        by_cat: "dict[str, list[str]]" = {}
        for slug in v.order:
            by_cat.setdefault(v.category(slug), []).append(slug)
        for cat, slugs in by_cat.items():
            print(f"  {cat:<14} {', '.join(slugs)}")
        print(f"\n{len(v.synonyms)} synonym(s). Try a label:\n"
              '  ./_config/.venv/bin/python "0 - selection/ambientes.py" '
              '"Sala Cobertura" "Lavabo" "IMG_5501"')
        return

    for label in labels:
        slug, kw = v.slug_for(label)
        if slug:
            print(f"  {label:<28} -> {slug:<18} {v.category(slug):<14} "
                  f'(matched "{kw}")')
        else:
            print(f"  {label:<28} -> {UNKNOWN:<18} default        "
                  "(no keyword matched — the vision pass would decide)")


if __name__ == "__main__":
    main()
