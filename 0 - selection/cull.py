#!/usr/bin/env python3
"""Turn a delivery into a shortlist you can actually look at.

    ./_config/.venv/bin/python "0 - selection/cull.py" "0 - selection/Cobertura"
    ./_config/.venv/bin/python "0 - selection/cull.py" "0 - selection/Cobertura" --workers 8

Reads every file in the shoot's `source/`, writes a proxy for each, groups them
into scenes, measures what the pixels say, and lays the result out as
`review-selection.html` — a clickable contact sheet grouped by room, ranked within each
room, that writes `picks.txt` for you.

Then it stops. **Choosing is yours** — this stage's whole job is to make 307
files reviewable in ten minutes instead of two hours, not to decide for you.
`develop.py` picks up from `picks.txt`.

Three reductions happen here, in this order, and they are different things:

1. **Bracket** — one scene shot at several exposures, to be merged later into a
   single frame. Detected from EXIF timestamps and exposure bias. Five files,
   one photo.
2. **Cluster** — the same corner shot repeatedly while the tripod crept. Found
   with a perceptual hash. Thirty-two kitchen files, six real angles.
3. **Geometry** — what the strategy document rejects outright: verticals that
   splay, frames that lean, focal lengths that stretch the edges.

Nothing is deleted and nothing is hidden. A frame this script ranks last is
still on the sheet, because a rule that is right nine times out of ten is still
wrong once, and the tenth photo might be the only one showing the sofa bed.

Rules and thresholds: `../_config/Seletor/RULES.md`. Per-file measurement:
`ingest.py`. Stage contract: `CONTEXT.md`.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_config"))
import ambientes  # noqa: E402
import gate  # noqa: E402
import ingest  # noqa: E402
from ambientes import fold  # noqa: E402 — one owner for accent-insensitive keys

SELECTION_DIR = Path(__file__).resolve().parent
ROOT = SELECTION_DIR.parent

PHOTO_EXTS = ingest.RAW_EXTS | {
    ".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".heic", ".heif"}

# Files are read in parallel. The work is mostly inside numpy/OpenCV/Pillow,
# which drop the GIL, so threads do get real concurrency here — and they keep
# the shape identical to `batch.py`, which does the same thing for API calls.
WORKERS = 8

# --- bracket detection -------------------------------------------------------
# Frames of one bracket are fired by the camera back-to-back. Two seconds is
# loose enough for a slow interior exposure sequence and tight enough that two
# deliberate compositions never merge.
BRACKET_GAP_SECONDS = 2.0
# A bracket must actually vary its exposure. Without this, a burst of identical
# frames — or a photographer who shoots three of everything at one setting —
# reads as a bracket and gets silently merged into one photo later.
BRACKET_MIN_EV_SPREAD = 0.5
MAX_BRACKET_SIZE = 9

# --- near-duplicate clustering -----------------------------------------------
# Hamming distance between 64-bit perceptual hashes. Two frames of the same
# corner from a tripod nudged 10cm land within ~10; genuinely different angles
# of one room sit well above it. Needs calibrating per photographer — the run
# prints the cluster-size spread so the effect of changing it is visible.
PHASH_MAX_DISTANCE = 12

# Geometry thresholds, the room quota, and the vision prompt all live in
# `../_config/Seletor/RULES.md` — see `load_rules()`. Nothing is duplicated here
# on purpose: two copies of a threshold is one copy that goes stale, and the copy
# that goes stale is always the one someone is reading.


HIGHLIGHT_CLIP_WARN = 8.0     # % of frame blown out
SHADOW_CLIP_WARN = 12.0

# --- room labels -------------------------------------------------------------
# The cheapest, most accurate room classifier is the photographer's own
# filename. One delivery measured here named 277 of 307 files
# `NN_Ambiente_N.JPG` — free, exact, and better than any model.
#
# Patterns are tried in order against the file stem. **Add your photographers'
# schemes here**; anything unmatched falls back to the containing folder, and
# only then to nothing (which is what the vision scorer is for).
ROOM_PATTERNS = [
    # "8_Cozinha_1", "1_Cobertura_11b" — ordered room, then shot number
    re.compile(r"^(?P<order>\d{1,2})_(?P<room>.+?)_(?P<shot>\d{1,3}[a-z]?)$"),
    # "Cozinha_1", "Sala 2"
    re.compile(r"^(?P<room>[^\d_][^_]*?)[ _-](?P<shot>\d{1,3}[a-z]?)$"),
]
# Folder names often carry the same thing: "1_Imóvel", "3_Condomínio". Matched
# by pattern wherever it sits in the path, never by position — a downloader may
# wrap the delivery in an extra folder named after the property.
NUMBERED_FOLDER_RE = re.compile(r"^(?P<order>\d{1,2})_(?P<name>.+)$")


# --- the rules file ----------------------------------------------------------
# The one tuning surface, read fresh every run so an edit lands immediately —
# exactly what `enhance.py` does with `PROMPT.md`. Nothing below is duplicated in
# code: if the file is missing or malformed the run stops, rather than quietly
# falling back to constants that would then disagree with the documentation.
RULES_PATH = ROOT / "_config" / "Seletor" / "RULES.md"
PROMPT_START = "===== VISION PROMPT"
PROMPT_END = "===== END OF RULES"

SETTING_RE = re.compile(r"^ {4,}([a-z][a-z /]*?):\s*(\S.*?)\s*$", re.M)
TABLE_ROW_RE = re.compile(r"^\|\s*(?P<a>[^|]+?)\s*\|\s*(?P<b>[^|]+?)\s*\|"
                          r"\s*(?P<c>[^|]+?)\s*\|\s*$", re.M)


class RulesError(Exception):
    """RULES.md is missing or unusable. Fatal — there is no safe default."""


@dataclass
class Rules:
    base_per_room: int = 3
    target_min: int = 40
    target_max: int = 60
    roll_warn: float = 3.0
    roll_flag: float = 5.0
    convergence_warn: float = 12.0
    convergence_flag: float = 20.0
    focal_warn: float = 20.0
    focal_flag: float = 16.0
    keywords: "list[tuple[str, int, str]]" = field(default_factory=list)
    priorities: "dict[str, int]" = field(default_factory=dict)
    typology: "list[tuple[int, str, int, int]]" = field(default_factory=list)
    vision_prompt: str = ""
    fingerprint: str = ""

    def priority_for(self, category: str) -> int:
        """Expansion priority for a category name.

        The way in, now that the room's category comes from the canonical ambiente
        in `AMBIENTES.md` rather than from matching this file's keywords against
        free text. Which rooms get the spare slots is still decided here — this
        file stays the one tuning surface for the quota.
        """
        return self.priorities.get(category, 99)

    def category(self, room: "str | None") -> "tuple[int, str]":
        """Priority and category for a room name. Accent- and case-insensitive.

        Matched by **where** the keyword appears, not by how long it is. Room names
        put the noun first and the qualifier after — `Sala Cobertura` is a living
        room *in* the penthouse, `Banheiro Suíte 1` is a bathroom *of* suite 1 —
        so the keyword nearest the start describes what the room actually is.

        Preferring the longest keyword instead, which is the obvious first
        instinct, filed `Sala Cobertura` and `Lavabo Cobertura` as roof terraces
        because `cobertura` is longer than `sala`. Length ties are broken by the
        longer keyword, which is what lets `suíte 1` beat `suíte` and keeps the
        master suite out of the spare-bedroom pile.
        """
        if not room:
            return 99, "default"
        needle = fold(room)
        best = None
        for kw, priority, cat in self.keywords:
            at = needle.find(kw)
            if at < 0:
                continue
            rank = (at, -len(kw))
            if best is None or rank < best[0]:
                best = (rank, priority, cat)
        return (best[1], best[2]) if best else (99, "default")

    def target_for(self, n_rooms: int) -> "tuple[int, int, str | None]":
        """The gallery target, plus a warning when the default looks wrong here.

        The configured target is honoured — it is the operator's decision — but a
        6-room property padded to 40 photos is the failure the source document
        names outright, so the mismatch is surfaced rather than silently obeyed.
        """
        for max_rooms, label, lo, hi in self.typology:
            if n_rooms <= max_rooms:
                if not (lo <= self.target_min and self.target_max <= hi + 15):
                    return (self.target_min, self.target_max,
                            f"{n_rooms} rooms reads as {label}, which the strategy "
                            f"document puts at {lo}-{hi} photos — not "
                            f"{self.target_min}-{self.target_max}. Padding a small "
                            "property advertises how little there is. Override with "
                            "--target if you meant it.")
                break
        return self.target_min, self.target_max, None


def load_rules(path: "Path | None" = None) -> Rules:
    """Parse RULES.md. Raises RulesError with something actionable in it."""
    path = path or RULES_PATH
    if not path.exists():
        raise RulesError(f"no rules file at {rel(path)} — the quota, the thresholds "
                         "and the vision prompt all live there")
    raw = path.read_text(encoding="utf-8")

    if PROMPT_START not in raw or PROMPT_END not in raw:
        raise RulesError(
            f"{rel(path)} is missing its `{PROMPT_START}` / `{PROMPT_END}` marker "
            "lines. Without them the documentation below them would be sent to the "
            "vision model as part of the prompt. Put them back before running.")
    # Everything strictly between the two marker *lines*, dropping the remainder
    # of the start marker's own line.
    after = raw.split(PROMPT_START, 1)[1]
    prompt = after.split("\n", 1)[1].split(PROMPT_END, 1)[0].strip()
    if len(prompt) < 200:
        raise RulesError(f"{rel(path)} has only {len(prompt)} characters of vision "
                         "prompt between the markers — that looks like a bad edit, "
                         "not a prompt")

    r = Rules(vision_prompt=prompt,
              fingerprint=hashlib.sha256(raw.encode()).hexdigest()[:8])

    settings = {k.strip(): v for k, v in SETTING_RE.findall(raw)}
    r.base_per_room = int(_need(settings, "base per room", path))
    target = _need(settings, "gallery target", path)
    if m := re.match(r"(\d+)\s*[-–]\s*(\d+)$", target):
        r.target_min, r.target_max = int(m.group(1)), int(m.group(2))
    else:
        raise RulesError(f"`gallery target: {target}` in {rel(path)} should be a "
                         "range like `40-60`")
    for key, attr in (("roll warn", "roll_warn"), ("roll flag", "roll_flag"),
                      ("convergence warn", "convergence_warn"),
                      ("convergence flag", "convergence_flag"),
                      ("focal warn", "focal_warn"), ("focal flag", "focal_flag")):
        setattr(r, attr, float(_need(settings, key, path)))

    # Expansion priority table: | 1 | hero_outdoor | cobertura, terraço, ... |
    for a, b, c in TABLE_ROW_RE.findall(raw):
        if not a.strip().isdigit():
            continue
        priority, category = int(a.strip()), b.strip()
        r.priorities[category] = priority
        if category == "default":
            continue
        for kw in c.split(","):
            kw = fold(kw.strip().strip("*_()"))
            if kw and "anything unmatched" not in kw:
                r.keywords.append((kw, priority, category))
    # Longest first, so a specific keyword beats the general one it contains.
    r.keywords.sort(key=lambda t: -len(t[0]))
    if not r.keywords:
        raise RulesError(f"{rel(path)} has no expansion-priority keywords — the "
                         "quota cannot decide which rooms get extra slots")

    # Volume by typology: | T0-T1 | up to 5 | 15-25 |
    for a, b, c in TABLE_ROW_RE.findall(raw):
        label = a.strip()
        if not re.match(r"^T\d", label):
            continue
        # "up to 5" -> 5 · "6 to 10" -> 10 · "11 or more" -> no ceiling.
        # The *last* number is the upper bound; taking the first read "6 to 10"
        # as a ceiling of 6, so an 8-room property skipped its own band.
        numbers = re.findall(r"\d+", b)
        span = re.match(r"(\d+)\s*[-–]\s*(\d+)$", c.strip())
        if numbers and span:
            cap = 10**6 if "more" in b.lower() else int(numbers[-1])
            r.typology.append((cap, label, int(span.group(1)), int(span.group(2))))
    r.typology.sort()

    return r


def _need(settings: dict, key: str, path: Path) -> str:
    if key not in settings:
        raise RulesError(f"{rel(path)} is missing the line `    {key}: ...` "
                         "(indented four spaces)")
    return settings[key]


# --- delivery profiling ------------------------------------------------------
# Deliveries are not one problem. Four photographers send four different things,
# and treating them alike gets three of them wrong. The type is decided from the
# EXIF header and the filenames alone — a second of work — and printed before the
# expensive pass, so a misread delivery is caught before the CPU is spent.
DELIVERY_TYPES = {
    "A": "already culled — hand it straight on, do not curate",
    "B": "JPEG, rooms named in the filenames",
    "C": "JPEG, camera filenames — the room has to be recognised",
    "D": "RAW with exposure brackets — merge before anything else",
    "E": "RAW, single frames — develop, then curate",
}

# A delivery this small, holding about three frames per room, has already been
# chosen by someone. Curating it again would cut photos that were picked on
# purpose.
ALREADY_CULLED_MAX_FILES = 60
ALREADY_CULLED_MAX_PER_ROOM = 3.0

RAW_SHARE_FOR_RAW_PATH = 0.5      # over half the files are negatives
BRACKET_SHARE_FOR_MERGE = 0.2     # brackets cover enough of them to matter
LABELLED_SHARE_FOR_NAMES = 0.6    # the filenames can be trusted for rooms
LABELLED_SHARE_FOR_VISION = 0.3   # below this, the room needs recognising


@dataclass
class Profile:
    """What kind of delivery this is, and the evidence for saying so."""
    kind: str = "B"
    files: int = 0
    raw_share: float = 0.0
    labelled_share: float = 0.0
    exif_share: float = 0.0
    bracket_share: float = 0.0
    rooms: "dict[str, int]" = field(default_factory=dict)
    median_per_room: float = 0.0
    why: "list[str]" = field(default_factory=list)
    caveats: "list[str]" = field(default_factory=list)

    @property
    def label(self) -> str:
        return DELIVERY_TYPES.get(self.kind, "unknown")

    @property
    def needs_bracket_merge(self) -> bool:
        return self.kind == "D"

    @property
    def needs_room_recognition(self) -> bool:
        return self.kind == "C"

    @property
    def curate(self) -> bool:
        """Type A is already someone's selection; re-cutting it is destructive."""
        return self.kind != "A"


@dataclass
class Scene:
    """One photo-to-be: a single frame, or a bracket that becomes one frame."""
    frames: "list[ingest.Facts]"
    room: "str | None" = None
    room_order: "int | None" = None
    shot: "str | None" = None
    area: "str | None" = None          # top folder: "Imóvel", "Condomínio"
    area_order: "int | None" = None
    cluster: int = -1
    flags: "list[str]" = field(default_factory=list)
    warns: "list[str]" = field(default_factory=list)

    # The canonical room name, from `AMBIENTES.md` — this is what the delivered
    # filename is built from, so it is the one field here that a client ever sees.
    # `room` above stays the photographer's own words, kept for the catalogue and
    # for the sheet's headings; it is evidence, not the answer.
    ambiente: "str | None" = None
    ambiente_visto: "str | None" = None   # what this run's check saw, before your edits
    ambiente_source: str = ""          # keyword | filename | vision | manual
    ambiente_note: str = ""

    # Filled by the vision pass, when it runs. `chosen` is what pre-ticks the
    # tile; `reason` is the sentence that justifies it, in Portuguese, and travels
    # into `selection.md`.
    chosen: bool = False
    reason: str = ""
    rejected_why: str = ""
    purpose: "int | None" = None
    staging: "int | None" = None

    @property
    def lead(self) -> "ingest.Facts":
        """The frame that represents the scene.

        For a bracket that is the middle exposure — the one whose tones are
        closest to what the camera metered — because it is the most honest
        preview of what the merge will produce.
        """
        if len(self.frames) == 1:
            return self.frames[0]
        with_ev = [f for f in self.frames if f.exposure_bias is not None]
        if with_ev:
            return min(with_ev, key=lambda f: abs(f.exposure_bias))
        return self.frames[len(self.frames) // 2]

    @property
    def key(self) -> str:
        return self.lead.path.name

    @property
    def is_bracket(self) -> bool:
        return len(self.frames) > 1

    @property
    def ev_span(self) -> str:
        evs = [f.exposure_bias for f in self.frames if f.exposure_bias is not None]
        return f"{min(evs):+.1f}…{max(evs):+.1f} EV" if len(evs) > 1 else ""


def rel(p: Path) -> str:
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)


# --------------------------------------------------------------- room parsing

def parse_labels(photo: Path, source_dir: Path,
                 vocab: "ambientes.Vocabulary | None" = None) -> "tuple[str|None, int|None, str|None, str|None, int|None]":
    """Pull (room, room_order, shot, area, area_order) out of the path.

    Free and exact when the photographer numbers their files, which is common
    and worth exploiting before paying a model to look at pixels.

    `vocab` is only consulted to recognise a property reference, which is never a
    room — in the filename here, and in the innermost folder at the bottom.
    """
    room = order = shot = None
    # `WC-660.jpg` splits into room `WC` + shot `660` under the second pattern,
    # and `WC` maps to BANHEIRO. The check has to sit here, on the whole stem,
    # rather than on `room` afterwards: by then the digits that identify it as a
    # reference have already been taken away as the shot number.
    if not (vocab and vocab.has_code(photo.stem)):
        for pattern in ROOM_PATTERNS:
            if m := pattern.match(photo.stem):
                g = m.groupdict()
                room = g["room"].strip().replace("_", " ")
                order = int(g["order"]) if g.get("order") else None
                shot = g.get("shot")
                break

    try:
        parts = photo.relative_to(source_dir).parts[:-1]
    except ValueError:
        parts = ()

    # The area is a *numbered* folder ("1_Imóvel", "3_Condomínio"), found by
    # pattern rather than by position: a downloader may wrap the whole delivery
    # in one more folder named after the property, and indexing from the left
    # would grab that instead.
    area = area_order = None
    for part in parts:
        if m := NUMBERED_FOLDER_RE.match(part):
            area, area_order = m.group("name").strip(), int(m.group("order"))
            break

    # No room in the filename? The innermost folder is the next best thing — a
    # delivery that sorts photos into per-room folders is saying the same thing.
    #
    # Unless that folder carries the property's reference, in which case it is the
    # wrapper the whole delivery arrived in and says nothing about a room. Taking
    # it anyway is how 48 photographs of a house became one `BANHEIRO`: the folder
    # was `WC-00660 - Casa MAD Alter` and `wc` is a synonym of bathroom. Leaving
    # `room` as None is the honest answer — it makes the profiler say the rooms
    # are not in the filenames, which is true, and routes the delivery to the
    # per-photograph naming pass that can actually answer the question.
    if room is None and parts:
        innermost = parts[-1]
        if innermost != area and not (vocab and vocab.has_code(innermost)):
            m = NUMBERED_FOLDER_RE.match(innermost)
            room = (m.group("name") if m else innermost).strip()
            if m:
                order = int(m.group("order"))
    return room, order, shot, area, area_order


# ------------------------------------------------------------------ profiling

def profile_delivery(photos: "list[Path]", source: Path,
                     workers: int = WORKERS,
                     vocab: "ambientes.Vocabulary | None" = None) -> Profile:
    """Decide what kind of delivery this is, from headers and names only.

    Order matters. Format wins first — a folder of negatives has to be developed
    whatever else is true of it. Then "has someone already chosen these?", because
    answering that wrong is the only failure here that *destroys* work rather
    than merely doing it clumsily.
    """
    p = Profile(files=len(photos))

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        probed = list(pool.map(_probe_quietly, photos))
    facts = [f for f in probed if f is not None]

    p.raw_share = sum(1 for f in facts if f.is_raw) / max(1, len(facts))
    p.exif_share = sum(1 for f in facts if f.shot_at) / max(1, len(facts))

    labelled = 0
    for f in facts:
        room, order, shot, area, area_order = parse_labels(f.path, source, vocab)
        if room:
            labelled += 1
            p.rooms[room] = p.rooms.get(room, 0) + 1
    p.labelled_share = labelled / max(1, len(facts))

    if p.rooms:
        counts = sorted(p.rooms.values())
        mid = len(counts) // 2
        p.median_per_room = (counts[mid] if len(counts) % 2
                             else (counts[mid - 1] + counts[mid]) / 2)

    # Bracket coverage, from the same grouping the real pass will use, so the
    # profile cannot promise a merge the pass then declines to do.
    scenes = group_brackets(facts)
    in_brackets = sum(len(s.frames) for s in scenes if s.is_bracket)
    p.bracket_share = in_brackets / max(1, len(facts))

    if p.raw_share >= RAW_SHARE_FOR_RAW_PATH:
        if p.bracket_share >= BRACKET_SHARE_FOR_MERGE:
            p.kind = "D"
            p.why.append(f"{p.raw_share:.0%} of the files are raw and brackets cover "
                         f"{p.bracket_share:.0%} of them")
        else:
            p.kind = "E"
            p.why.append(f"{p.raw_share:.0%} of the files are raw, with no bracket "
                         "pattern in the timestamps and exposure bias")
            if p.exif_share < 0.5:
                p.caveats.append(
                    f"only {p.exif_share:.0%} carry a timestamp, so a bracket set "
                    "could be here and be invisible. If this shoot was bracketed, "
                    "force it with --type D.")
    elif (p.files <= ALREADY_CULLED_MAX_FILES and p.rooms
            and p.median_per_room <= ALREADY_CULLED_MAX_PER_ROOM):
        p.kind = "A"
        p.why.append(f"{p.files} photos across {len(p.rooms)} rooms, median "
                     f"{p.median_per_room:.0f} per room — that spread is what a "
                     "finished selection looks like, not a shoot")
    elif p.files <= ALREADY_CULLED_MAX_FILES and not p.rooms:
        # Small and unlabelled is genuinely ambiguous, and the honest thing is to
        # say so rather than dress a guess up as a finding. Absence of room names
        # is not evidence of curation — it is absence of evidence either way.
        # Erring towards A is the safe error: treating a finished selection as a
        # shoot would cut photos somebody chose on purpose.
        p.kind = "A"
        p.why.append(f"{p.files} photos with no room names — small enough to be a "
                     "finished selection, so it is treated as one")
        p.caveats.append(
            "this could equally be a small raw dump; nothing in the filenames "
            "settles it. The near-duplicate count from the next pass will tell you "
            "— lots of near-duplicates means a dump. If it is one, re-run with "
            "`--type C`.")
    elif p.labelled_share >= LABELLED_SHARE_FOR_NAMES and len(p.rooms) == 1:
        # One label over the whole delivery is not a room name, it is the
        # delivery's name — read off the wrapping folder because the filenames
        # had nothing to offer. It reaches 100% labelled precisely because it
        # distinguishes nothing. `WC-00660 - Casa MAD Alter` typed a whole house
        # as a bathroom this way, on the strength of `WC-`.
        #
        # A photographer really can send one room, but type A above has already
        # claimed the small deliveries; getting here means many photographs under
        # a single word. Treating a genuine one-room shoot as C costs one vision
        # pass and arrives at the same name — the other error names every
        # photograph in the house after a room it is not in.
        p.kind = "C"
        p.why.append(f"every file carries the same label, `{next(iter(p.rooms))}` — "
                     "one word over the whole delivery names the delivery, not a "
                     "room, so the rooms are recognised from the pictures")
    elif p.labelled_share >= LABELLED_SHARE_FOR_NAMES:
        p.kind = "B"
        p.why.append(f"{p.labelled_share:.0%} of the filenames name their room "
                     f"({len(p.rooms)} rooms found)")
    else:
        p.kind = "C"
        p.why.append(f"only {p.labelled_share:.0%} of the filenames name a room, so "
                     "the rooms have to be recognised from the pictures")

    if p.exif_share == 0:
        p.caveats.append("no EXIF anywhere — no focal length, so the wide-angle "
                         "rule cannot be checked, and no timestamps, so nothing "
                         "can be grouped into a bracket")
    return p


def _probe_quietly(path: Path) -> "ingest.Facts | None":
    try:
        return ingest.probe(path)
    except Exception:                            # noqa: BLE001 — a bad header must not stop profiling
        return None


def write_profile(job: Path, p: Profile) -> Path:
    """Write `profile.md` — the delivery's own description of itself."""
    L = [f"# {job.name} — delivery profile", "",
         f"_Written by `0 - selection/cull.py`. Override with `--type`._", "",
         f"## Type {p.kind} — {p.label}", ""]
    L += [f"- {w}" for w in p.why]
    L += ["", "## Measured", "",
          "| | |", "|---|---|",
          f"| Photos | {p.files} |",
          f"| Raw | {p.raw_share:.0%} |",
          f"| With a timestamp | {p.exif_share:.0%} |",
          f"| Room named in the filename | {p.labelled_share:.0%} |",
          f"| Covered by a bracket | {p.bracket_share:.0%} |",
          f"| Rooms | {len(p.rooms)} |",
          f"| Median photos per room | {p.median_per_room:.0f} |", ""]

    if p.rooms:
        L += ["## Rooms as the photographer named them", "",
              "| Room | Photos |", "|---|---|"]
        L += [f"| {r} | {n} |" for r, n in sorted(p.rooms.items(),
                                                  key=lambda kv: -kv[1])]
        L.append("")

    if p.caveats:
        L += ["## Worth knowing", ""]
        L += [f"- ⚠️ {c}" for c in p.caveats]
        L.append("")

    if not p.curate:
        L += ["---", "",
              "**Nothing here will be cut.** A delivery this shape has already been "
              "chosen by someone, and curating it again would drop photos that were "
              "picked on purpose. It gets proxies and a contact sheet so you can look "
              "at it, and every frame is pre-ticked.", ""]

    (job / "profile.md").write_text("\n".join(L), encoding="utf-8")
    return job / "profile.md"


# ------------------------------------------------------------------- grouping

def group_brackets(facts: "list[ingest.Facts]") -> "list[Scene]":
    """Collapse exposure brackets into single scenes.

    Needs a timestamp *and* a varying exposure bias to commit. Anything short of
    both stays a standalone scene, because a wrong merge is expensive and
    invisible: five separate compositions would silently become one photo, and
    four of them would vanish from the shortlist without ever being rejected.
    """
    datable = [f for f in facts if f.shot_at is not None]
    undatable = [f for f in facts if f.shot_at is None]

    datable.sort(key=lambda f: (f.shot_at, f.subsec, f.path.name))
    scenes: "list[Scene]" = []
    run: "list[ingest.Facts]" = []

    def flush() -> None:
        if not run:
            return
        evs = [f.exposure_bias for f in run if f.exposure_bias is not None]
        spread = (max(evs) - min(evs)) if len(evs) == len(run) and evs else 0.0
        if len(run) > 1 and spread >= BRACKET_MIN_EV_SPREAD:
            scenes.append(Scene(frames=list(run)))
        else:
            scenes.extend(Scene(frames=[f]) for f in run)
        run.clear()

    for f in datable:
        if not run:
            run.append(f)
            continue
        prev = run[-1]
        gap = (f.shot_at - prev.shot_at).total_seconds() + (f.subsec - prev.subsec) / 1000
        same_burst = 0 <= gap <= BRACKET_GAP_SECONDS
        # An exposure bias that repeats means a new bracket started, even when
        # the shutter never paused.
        repeats = (f.exposure_bias is not None
                   and f.exposure_bias in [x.exposure_bias for x in run])
        if same_burst and not repeats and len(run) < MAX_BRACKET_SIZE:
            run.append(f)
        else:
            flush()
            run.append(f)
    flush()

    scenes.extend(Scene(frames=[f]) for f in undatable)
    return scenes


def hamming(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def cluster_scenes(scenes: "list[Scene]") -> int:
    """Group scenes that show the same thing. Returns the cluster count.

    Clustering is confined to one room at a time. A bathroom and a bedroom can
    hash alike — both are small, bright, and mostly wall — and merging them
    would drop one of the two from the shortlist entirely. When the room labels
    are free and exact, refusing to cross them costs nothing.
    """
    buckets: "dict[str, list[Scene]]" = defaultdict(list)
    for s in scenes:
        buckets[f"{s.area or ''}/{s.room or ''}"].append(s)

    next_id = 0
    for group in buckets.values():
        # Shot order first, so the union-find walks the sequence the
        # photographer actually shot and consecutive near-duplicates meet.
        group.sort(key=lambda s: (s.lead.shot_at or datetime.min, s.lead.path.name))
        parent = list(range(len(group)))

        def find(i: int) -> int:
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                hi, hj = group[i].lead.phash, group[j].lead.phash
                if hi and hj and hamming(hi, hj) <= PHASH_MAX_DISTANCE:
                    parent[find(i)] = find(j)

        local: "dict[int, int]" = {}
        for i, scene in enumerate(group):
            root = find(i)
            if root not in local:
                local[root] = next_id
                next_id += 1
            scene.cluster = local[root]
    return next_id


# --------------------------------------------------------------------- flags

def assess(scene: Scene, rules: Rules) -> None:
    """Attach the strategy document's hard rules as flags and warnings.

    Nothing here removes a photo. `flags` means "the document says reject this";
    `warns` means "look closer". Both are shown on the contact sheet and both
    are overridable by a click, because the alternative — trusting an
    uncalibrated threshold — throws away the only picture of something.

    Thresholds come from `RULES.md`, not from constants here, so there is one
    place to change them and no chance of the code and the documentation drifting
    apart.
    """
    f = scene.lead

    if f.roll_deg is not None:
        if abs(f.roll_deg) >= rules.roll_flag:
            scene.flags.append(f"leaning {f.roll_deg:+.1f}°")
        elif abs(f.roll_deg) >= rules.roll_warn:
            scene.warns.append(f"slight lean {f.roll_deg:+.1f}°")

    if f.convergence_deg is not None:
        if f.convergence_deg >= rules.convergence_flag:
            scene.flags.append(f"verticals splay {f.convergence_deg:.0f}° "
                               "(three-point perspective)")
        elif f.convergence_deg >= rules.convergence_warn:
            scene.warns.append(f"verticals splay {f.convergence_deg:.0f}°")
    elif f.lines_found < ingest.MIN_LINES_FOR_FIT:
        # Unknown is not the same as fine, and printing nothing would read as
        # fine. A detail shot legitimately has no architecture in it.
        scene.warns.append(f"geometry unmeasurable ({f.lines_found} verticals found)")

    if f.focal_35mm is not None:
        if f.focal_35mm < rules.focal_flag:
            scene.flags.append(f"{f.focal_35mm:.0f}mm equivalent — edge stretching")
        elif f.focal_35mm < rules.focal_warn:
            scene.warns.append(f"{f.focal_35mm:.0f}mm equivalent, wide")
    elif f.focal_mm is not None:
        scene.warns.append(f"{f.focal_mm:.0f}mm, sensor unknown — "
                           "can't check the wide-angle rule")

    if f.highlight_clip >= HIGHLIGHT_CLIP_WARN:
        scene.warns.append(f"{f.highlight_clip:.0f}% blown out"
                           + (" — a bracket should fix this" if scene.is_bracket else ""))
    if f.shadow_clip >= SHADOW_CLIP_WARN:
        scene.warns.append(f"{f.shadow_clip:.0f}% crushed black")


def rank_within_cluster(scenes: "list[Scene]") -> "dict[int, list[Scene]]":
    """Order each cluster best-first. Returns cluster id -> ordered scenes.

    Sharpness is only ever compared *inside* a cluster, never across the
    delivery: the absolute number depends on how much detail the subject has, so
    a sharp photo of a blank wall scores below a soft photo of a bookcase.

    The tie-break is the strategy document's "cull backwards" observation — the
    photographer arrives, fires a few rough frames, then adjusts the tripod and
    gets it right, so the *later* frame of two similar ones is usually the
    better one.
    """
    by_cluster: "dict[int, list[Scene]]" = defaultdict(list)
    for s in scenes:
        by_cluster[s.cluster].append(s)
    for group in by_cluster.values():
        group.sort(key=lambda s: (
            len(s.flags),
            -s.lead.sharpness,
            -(s.lead.shot_at.timestamp() if s.lead.shot_at else 0),
        ))
    return by_cluster


# ------------------------------------------------------------- contact sheet

@dataclass
class RoomGroup:
    """One physical room's scenes, its clusters, and how many slots it gets."""
    room: str                          # the photographer's words
    area: "str | None"
    priority: int = 99
    category: str = "default"
    clusters: "list[list[Scene]]" = field(default_factory=list)
    slots: int = 0
    base: int = 0

    # One group is one physical room, so the canonical name and its index belong
    # here rather than on every scene inside it.
    ambiente: str = ambientes.UNKNOWN
    sala_idx: int = 1
    ambiente_source: str = ""
    ambiente_note: str = ""

    @property
    def angles(self) -> int:
        return len(self.clusters)

    @property
    def scenes(self) -> int:
        return sum(len(c) for c in self.clusters)

    @property
    def name(self) -> str:
        """`QUARTO_02` — the stem every photo in this room is delivered under.

        Also the group's identity everywhere a room needs a unique key: the
        photographer's label is not one, because two areas of a delivery can both
        hold a `Piscina` and the sheet used to file them under one heading.
        """
        return f"{self.ambiente}_{self.sala_idx:02d}"

    @property
    def heading(self) -> str:
        bits = [self.name]
        if self.room and fold(self.room) != fold(self.ambiente):
            bits.append(self.room)
        if self.area:
            bits.append(self.area)
        return "  ·  ".join(bits)

    @property
    def corrected(self) -> bool:
        return self.ambiente_source in ("vision", "manual")

    @property
    def can_grow(self) -> bool:
        return self.slots < self.angles

    @property
    def can_shrink(self) -> bool:
        return self.slots > 1


def group_rooms(scenes: "list[Scene]", rules: Rules,
                vocab: "ambientes.Vocabulary | None" = None,
                prior: "dict | None" = None) -> "list[RoomGroup]":
    """Group scenes into physical rooms, in walkthrough order, best cluster first.

    The photographer's own numbering is the walkthrough order — they moved
    through the property once and numbered as they went — so it beats anything
    inferred from timestamps.

    Called twice per run, and the two calls mean different things. The first is
    provisional: `ambiente` is still empty on every scene, so it buckets by the
    photographer's label alone, purely to gather each room's photographs into one
    cheap batch for the classification pass. The second runs after that pass, when
    `ambiente` is filled in, and it is the authoritative one — `ambiente` is part
    of the key, so a stray photograph the model found in the wrong folder splits
    off into its own room instead of merely being flagged inside the wrong one.

    `prior` is the catalogue, and its `Sala` column joins the key. That is the
    only way to say *two rooms of the same kind* when nothing in the delivery says
    it for you — a photographer who files bedrooms into `2_Quarto_1/` and
    `3_Quarto_2/` is separated by `room_order` above, but one who hands over a
    flat folder of `IMG_9620.HEIC` is not, and two bedrooms then arrive as one.
    The contact sheet is where that number gets set, because seeing it is what tells
    you the rooms are different.

    Unlike `ambiente`, this needs no `Visto` column to prove a person wrote it.
    `Sala` comes from the grouping and from nothing else — no model recomputes it,
    so there is no drift to mistake for a decision. Feeding it back in is stable:
    the same numbers come out that went in.
    """
    def sala_hint(s: "Scene") -> int:
        """The catalogue's room number for this scene. 1 when it has nothing to say.

        Not 0 — "no opinion" and "explicitly the first room" have to be the *same*
        key or they split one room in two. A photograph whose hint was discarded
        below would otherwise land in a room of its own next to the photographs
        that kept theirs, which is the failure this function exists to prevent,
        arriving through the door marked safety. A photograph with no row at all
        joins the first room of its ambiente, and can be moved on the sheet.

        A room number only means something inside the ambiente it was handed out
        in. Once a photograph leaves that ambiente the number is a leftover, and
        carrying it across conjures a room that never existed — a `SALA_02` of one
        photograph, whose name a client eventually reads. Two ways that happens,
        and they need different tests:

        - **You changed the `Ambiente` by hand.** `row.edited` catches it, and
          nothing else does: by the time this runs the catalogue has already been
          applied to the scene, so comparing the row's ambiente to the scene's
          compares a value with itself and is always true. That vacuous check was
          the first version of this function and it let `SALA_02` through.
        - **The classifier moved it since the catalogue was written.** Then the
          scene's ambiente is the model's fresh answer and the row's is stale, so
          comparing them does work — this is the case it was written for.

        Changing only the `Sala` leaves `Ambiente` and `Visto` agreeing, so
        `edited` stays false and the number is kept. That is the whole feature.
        """
        if not prior:
            return 1
        row = next((prior[k] for k in
                    (ambientes.fold_name(f.path.name) for f in s.frames)
                    if k in prior), None)
        if not row or row.edited:
            return 1
        return row.sala if row.ambiente == s.ambiente else 1

    buckets: "dict[tuple, list[Scene]]" = defaultdict(list)
    for s in scenes:
        buckets[(s.area_order if s.area_order is not None else 99,
                 s.area or "",
                 s.room_order if s.room_order is not None else 99,
                 s.room or "unlabelled",
                 s.ambiente or "",
                 sala_hint(s))].append(s)

    out = []
    for (_, area, _, room, ambiente, _), group in sorted(buckets.items()):
        ranked = rank_within_cluster(group)
        clusters = [ranked[cid] for cid in
                    sorted(ranked, key=lambda c: min(
                        (s.lead.path.name for s in ranked[c])))]
        # The canonical ambiente decides the category once there is one, so
        # `Sala Cobertura` is filed as `SALA`/social by the vocabulary rather than
        # re-derived from free text here. Before the first pass has run there is
        # no ambiente yet, and RULES.md's own keyword matching stands in.
        if ambiente and vocab:
            category = vocab.category(ambiente)
            priority = rules.priority_for(category)
        else:
            priority, category = rules.category(room)
        lead = group[0]
        out.append(RoomGroup(room=room, area=area or None, priority=priority,
                             category=category, clusters=clusters,
                             ambiente=ambiente or ambientes.UNKNOWN,
                             ambiente_source=lead.ambiente_source,
                             ambiente_note=lead.ambiente_note))
    if not vocab:
        return out

    # Numbered on the walkthrough order above — the first bedroom the photographer
    # entered is QUARTO_01 — and only then reordered so every room of one ambiente
    # sits together under one heading.
    ambientes.number_rooms(out)

    # Gathering the ambientes does cost something: the strategy document wants each
    # bedroom followed immediately by its own ensuite, and this separates them. It
    # is the right trade anyway, because the walkthrough order stopped being the
    # delivery order the moment the filename became `BANHEIRO_02_0001.jpg` — those
    # sort together on disk whatever this sheet does. A sheet ordered one way and a
    # folder ordered another is the version of this that helps nobody.
    #
    # Order *between* ambientes is still the walkthrough: an ambiente sits where the
    # photographer first walked into one.
    first_seen: "dict[str, int]" = {}
    for i, g in enumerate(out):
        first_seen.setdefault(g.ambiente, i)
    out.sort(key=lambda g: (first_seen[g.ambiente], g.sala_idx))
    return out


def allocate(groups: "list[RoomGroup]", rules: Rules,
             target: "tuple[int, int] | None" = None) -> dict:
    """Hand out gallery slots. Mutates `slots` on each group; returns the story.

    Three per room is the floor, the gallery target is what the whole set has to
    land in, and the category priority decides who gets the slots in between.

    Nothing is ever allocated beyond the distinct angles a room actually has —
    a room with two photographs gets two slots, not three, because the third
    would have to be a near-duplicate of one of them.
    """
    lo, hi = target or (rules.target_min, rules.target_max)

    for g in groups:
        g.base = g.slots = min(rules.base_per_room, g.angles)

    story = {"base": sum(g.slots for g in groups), "expanded": 0, "trimmed": 0,
             "target": (lo, hi), "grew": [], "cut": []}

    # Growing and shrinking are deliberately not mirror images, because the
    # marginal photograph behaves differently in each direction.
    #
    # **Expanding spreads.** A room's photographs have diminishing returns: the
    # eighth angle on the terrace tells a guest less than the fourth angle in a
    # bathroom does. So every room gets its extra slot in turn, in priority
    # order, rather than the terrace absorbing all of them.
    while sum(g.slots for g in groups) < lo:
        grew_this_pass = False
        for g in sorted(groups, key=lambda g: (g.priority, g.name)):
            if sum(g.slots for g in groups) >= lo:
                break
            if g.can_grow:
                g.slots += 1
                story["expanded"] += 1
                story["grew"].append(g.name)
                grew_this_pass = True
        if not grew_this_pass:
            break                       # every room is at its angle count

    # **Trimming concentrates at the bottom.** Here the rooms are not
    # interchangeable: the third photograph of a staircase is worth less than the
    # third photograph of a bedroom, which has a bed configuration to prove. So
    # the whole lowest-priority band is spent down to one before the band above
    # it loses anything — spreading the cut evenly would leave two pictures of a
    # front door and two of each bedroom, which is the wrong gallery.
    #
    # Within one band it still round-robins, so two bathrooms are not treated
    # differently for no reason other than their names.
    by_priority = sorted({g.priority for g in groups}, reverse=True)
    for priority in by_priority:
        band = sorted((g for g in groups if g.priority == priority),
                      key=lambda g: g.name)
        while sum(g.slots for g in groups) > hi and any(g.can_shrink for g in band):
            for g in band:
                if sum(g.slots for g in groups) <= hi:
                    break
                if g.can_shrink:
                    g.slots -= 1
                    story["trimmed"] += 1
                    story["cut"].append(g.name)
        if sum(g.slots for g in groups) <= hi:
            break

    story["total"] = sum(g.slots for g in groups)
    story["in_range"] = lo <= story["total"] <= hi
    story["capped"] = [g.name for g in groups if g.slots == g.angles
                       and g.angles < rules.base_per_room]
    return story


def write_contact_sheet(job: Path, groups: "list[RoomGroup]", prof: Profile,
                        rules: Rules, story: dict, elapsed: float,
                        note: str = "",
                        vocab: "ambientes.Vocabulary | None" = None) -> Path:
    """One self-contained HTML file: proxies by relative path, click to pick.

    HTML rather than markdown because the work here is comparing and toggling,
    not reading. It writes `picks.txt` through the clipboard rather than to disk
    — a browser page cannot write into the folder, and a download that lands in
    ~/Downloads would be worse than a copy button.

    The same page also corrects a room, for the reason it exists at all: two
    bedrooms that photograph alike are told apart by looking at them side by side,
    which is what this page is. It carries the catalogue `write_catalog` just
    wrote, **verbatim**, and the second copy button edits cells in that text
    rather than composing a document of its own. The markdown format therefore
    still lives only in `ambientes.py`; a JS copy of it would go stale silently
    the first time a column moved.
    """
    total_files = sum(len(s.frames) for g in groups for c in g.clusters for s in c)
    total_scenes = sum(g.scenes for g in groups)
    total_angles = sum(g.angles for g in groups)

    # Grouped by ambiente, then by the physical room inside it. The two levels are
    # different questions and collapsing them loses one: `QUARTO_01` and
    # `QUARTO_02` each need their own quota counter, but you want to see all the
    # bedrooms together while deciding how many bedroom photographs the gallery
    # should hold.
    rows: "list[str]" = []
    open_section = None
    for g in groups:
        if g.ambiente != open_section:
            if open_section is not None:
                rows.append("</section>")
            n_rooms = sum(1 for x in groups if x.ambiente == g.ambiente)
            rows.append(f'<section data-ambiente="{html.escape(g.ambiente)}">')
            rows.append(
                f'<h1 class="amb">{html.escape(g.ambiente)}'
                f'<small>{html.escape(g.category)}'
                + (f" · {n_rooms} rooms" if n_rooms > 1 else "")
                + "</small></h1>")
            open_section = g.ambiente

        capped = " · all it has" if g.angles < rules.base_per_room else ""
        badge = ""
        if g.ambiente_source == "manual":
            badge = '<b class="fix">yours</b>'
        elif g.ambiente_source == "vision":
            badge = ('<b class="fix" title="'
                     + html.escape(g.ambiente_note or "corrected from the pictures")
                     + '">corrected</b>')
        elif g.ambiente_source in ("keyword", "none"):
            badge = '<b class="unv" title="not checked against the pictures">?</b>'
        rows.append(
            f'<h2 data-room="{html.escape(g.name)}">'
            f'<span>{html.escape(g.heading)}{badge}</span>'
            f'<small><b class="count" data-for="{html.escape(g.name)}">0</b>'
            f'/{g.slots} picked{capped} · {g.scenes} photos · {g.angles} angles · '
            f'{html.escape(g.category)}</small></h2>')
        rows.append('<div class="grid">')
        for cluster in g.clusters:
            for i, s in enumerate(cluster):
                rows.append(tile(job, s, g, best=i == 0, siblings=len(cluster) - 1))
        rows.append("</div>")
    if open_section is not None:
        rows.append("</section>")

    lo, hi = story["target"]
    accounting = f'{story["base"]} from the floor of {rules.base_per_room} per room'
    if story["expanded"]:
        accounting += f", +{story['expanded']} expanded"
    if story["trimmed"]:
        accounting += f", −{story['trimmed']} trimmed"

    # `</` is the one sequence that would end the script element early and let the
    # catalogue's own text out into the document. JSON escaping does not cover it.
    catalog_path = job / ambientes.CATALOG_NAME
    payload = json.dumps({
        "catalog": catalog_path.read_text(encoding="utf-8")
                   if catalog_path.exists() else "",
        "slugs": list(vocab.order) if vocab else [],
    }).replace("</", "<\\/")

    dest = job / gate.PAGES["selection"]
    dest.write_text(TEMPLATE.format(
        title=html.escape(job.name),
        stamp=datetime.now().strftime("%Y-%m-%d %H:%M"),
        kind=prof.kind, kind_label=html.escape(prof.label),
        files=total_files, scenes=total_scenes, angles=total_angles,
        rooms=len(groups), elapsed=f"{elapsed:.0f}s",
        quota=story["total"], lo=lo, hi=hi,
        accounting=html.escape(accounting),
        rules_id=rules.fingerprint,
        note=f"<p class=\"note\">{note}</p>" if note else "",
        body="\n".join(rows),
        payload=payload,
        catalog_name=ambientes.CATALOG_NAME,
    ), encoding="utf-8")
    return dest


def tile(job: Path, s: Scene, g: RoomGroup, best: bool, siblings: int) -> str:
    f = s.lead
    proxy = f.proxy.relative_to(job).as_posix() if f.proxy else ""
    names = "+".join(x.path.name for x in s.frames)

    bits = []
    if s.is_bracket:
        bits.append(f'<b>bracket ×{len(s.frames)}</b> {html.escape(s.ev_span)}')
    if f.focal_35mm:
        bits.append(f"{f.focal_35mm:.0f}mm eq")
    elif f.focal_mm:
        bits.append(f"{f.focal_mm:.0f}mm")
    if f.roll_deg is not None:
        bits.append(f"roll {f.roll_deg:+.1f}°")
    if f.convergence_deg is not None:
        bits.append(f"splay {f.convergence_deg:.0f}°")
    if siblings:
        bits.append(f"{siblings} near-dup")

    marks = "".join(f'<span class="flag">{html.escape(x)}</span>' for x in s.flags)
    marks += "".join(f'<span class="warn">{html.escape(x)}</span>' for x in s.warns)
    if s.reason:
        marks += f'<span class="why">{html.escape(s.reason)}</span>'

    # `data-room` is what lets the page enforce the quota per room instead of only
    # counting a grand total: the counter that matters while you are looking at
    # the kitchen is the kitchen's.
    #
    # A `<div>` wrapping a `<label>`, rather than the label being the whole tile,
    # only because of the room `<select>` below it: a form control inside a label
    # activates that label when clicked, so picking a room would also tick the
    # photograph. The CSS reaches all of it by descent either way.
    return (
        f'<div class="tile{" best" if best else ""}{" flagged" if s.flags else ""}'
        f'{" chosen" if s.chosen else ""}">'
        f'<label class="shot">'
        f'<input type="checkbox" data-pick="{html.escape(names)}" '
        f'data-room="{html.escape(g.name)}"{" checked" if s.chosen else ""}>'
        f'<img src="{html.escape(proxy)}" loading="lazy" alt="">'
        f'<span class="cap"><code>{html.escape(f.path.name)}</code>'
        f'<span class="meta">{" · ".join(bits)}</span>{marks}</span>'
        f'</label>'
        # Populated by JS from the room list, so 48 tiles do not each carry a
        # copy of the whole vocabulary.
        f'<select class="rm" data-room="{html.escape(g.name)}" '
        f'data-files="{html.escape(names)}"></select>'
        # A sibling of the label for the same reason the <select> is: a control
        # inside a <label> toggles that label's checkbox when clicked, so typing
        # here would silently pick or unpick the photograph.
        f'<textarea class="note" rows="1" data-note="{html.escape(names)}" '
        f'placeholder="por quê"></textarea>'
        f'</div>')


TEMPLATE = """<title>{title} — contact sheet</title>
<style>
:root {{ color-scheme: light dark; --bg:#fff; --fg:#111; --dim:#666; --line:#e2e2e2;
        --pick:#0a7d3c; --flag:#b3261e; --warnbg:#fff4e5; --warnfg:#8a4b00; }}
@media (prefers-color-scheme: dark) {{ :root {{
  --bg:#141414; --fg:#eee; --dim:#999; --line:#2e2e2e; --pick:#4ade80;
  --flag:#ff6b6b; --warnbg:#3a2a10; --warnfg:#f5c26b; }} }}
* {{ box-sizing:border-box }}
body {{ margin:0; padding:1.2rem 1.4rem 6rem; background:var(--bg); color:var(--fg);
  font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
h1 {{ font-size:1.3rem; margin:0 0 .2rem }}
.sub {{ color:var(--dim); margin:0 0 1.4rem }}
h2 {{ font-size:1rem; margin:2rem 0 .6rem; padding-bottom:.3rem;
  border-bottom:1px solid var(--line); display:flex; justify-content:space-between;
  align-items:baseline; position:sticky; top:2.05rem; background:var(--bg); z-index:2 }}
h2 small {{ color:var(--dim); font-weight:400 }}
/* Two tiers of sticky header, offset so they stack instead of overlapping: the
   ambiente stays put while you scroll through its rooms, and the room heading —
   which carries that room's own quota counter — rides just below it. */
h1.amb {{ font-size:.78rem; letter-spacing:.09em; text-transform:uppercase;
  margin:2.4rem 0 0; padding:.42rem 0 .3rem; display:flex; gap:.6rem;
  align-items:baseline; position:sticky; top:0; z-index:3; background:var(--bg);
  border-bottom:2px solid var(--fg) }}
h1.amb small {{ color:var(--dim); font-weight:400; letter-spacing:0;
  text-transform:none }}
section:first-of-type h1.amb {{ margin-top:1rem }}
.fix, .unv {{ margin-left:.5rem; padding:.05rem .34rem; border-radius:4px;
  font-size:10px; font-weight:700; vertical-align:.1em; letter-spacing:.03em;
  text-transform:uppercase }}
.fix {{ background:color-mix(in srgb, var(--pick) 15%, transparent); color:var(--pick) }}
.unv {{ background:var(--warnbg); color:var(--warnfg) }}
.grid {{ display:grid; gap:.7rem; grid-template-columns:repeat(auto-fill,minmax(215px,1fr)) }}
.tile {{ display:block; border:2px solid transparent; border-radius:8px;
  overflow:hidden; background:var(--bg); position:relative }}
.shot {{ display:block; cursor:pointer }}
/* The room control. Quiet until you touch it — it is a correction surface, not
   part of the picking, and it must not compete with the checkbox for attention. */
.note {{ display:block; width:calc(100% - 2px); margin:0 1px 1px; padding:.25rem .4rem;
  font:inherit; font-size:11px; color:var(--fg); background:transparent;
  border:0; border-top:1px solid var(--line); resize:vertical }}
.note::placeholder {{ color:var(--dim); opacity:.7 }}
.note:focus {{ outline:1px solid var(--dim); outline-offset:-1px }}
.rm {{ display:block; width:100%; border:0; border-top:1px solid var(--line);
  padding:.3rem .5rem; font:11px/1.4 inherit; color:var(--dim);
  background:transparent; cursor:pointer; appearance:none }}
.rm:hover {{ color:var(--fg); background:color-mix(in srgb, var(--fg) 5%, transparent) }}
.rm.moved {{ color:var(--pick); font-weight:700;
  background:color-mix(in srgb, var(--pick) 12%, transparent) }}
.tile img {{ width:100%; aspect-ratio:4/3; object-fit:cover; display:block;
  background:var(--line); opacity:.62; transition:opacity .12s }}
.tile.best img {{ opacity:.85 }}
.tile input {{ position:absolute; top:.45rem; left:.45rem; z-index:1; width:19px; height:19px;
  accent-color:var(--pick); cursor:pointer }}
.tile:has(input:checked) {{ border-color:var(--pick) }}
.tile:has(input:checked) img {{ opacity:1 }}
.tile:hover img {{ opacity:1 }}
.tile.flagged {{ border-color:color-mix(in srgb, var(--flag) 40%, transparent) }}
.cap {{ display:block; padding:.4rem .5rem .55rem }}
.cap code {{ font-size:11px; color:var(--dim) }}
.meta {{ display:block; font-size:11px; color:var(--dim); margin-top:.15rem }}
.flag, .warn, .why {{ display:inline-block; margin:.28rem .28rem 0 0; padding:.1rem .38rem;
  border-radius:4px; font-size:10.5px; line-height:1.5 }}
.flag {{ background:color-mix(in srgb, var(--flag) 16%, transparent); color:var(--flag) }}
.warn {{ background:var(--warnbg); color:var(--warnfg) }}
.why {{ background:color-mix(in srgb, var(--pick) 13%, transparent); color:var(--pick);
  font-style:italic }}
.tile.chosen {{ border-color:var(--pick) }}
.count.past, #over.past {{ color:var(--flag); font-weight:700 }}
.note {{ margin:0 0 1.2rem; padding:.6rem .8rem; border-radius:7px;
  background:var(--warnbg); color:var(--warnfg); font-size:12.5px }}
#bar {{ position:fixed; left:0; right:0; bottom:0; padding:.7rem 1.4rem;
  background:color-mix(in srgb, var(--bg) 92%, transparent);
  backdrop-filter:blur(12px); border-top:1px solid var(--line);
  display:flex; gap:.8rem; align-items:center; z-index:9 }}
button {{ font:inherit; padding:.42rem .85rem; border-radius:7px; cursor:pointer;
  border:1px solid var(--line); background:var(--bg); color:var(--fg) }}
button.go {{ background:var(--pick); border-color:var(--pick); color:#fff; font-weight:600 }}
button.amb {{ background:var(--warnbg); border-color:var(--warnfg); color:var(--warnfg);
  font-weight:600 }}
#n {{ font-variant-numeric:tabular-nums; font-weight:600 }}
#hint {{ color:var(--dim); margin-left:auto; font-size:12px }}
</style>

<h1>{title}</h1>
<p class="sub">Type <b>{kind}</b> — {kind_label}<br>
{files} file(s) → {scenes} scene(s) → <b>{angles} distinct angle(s)</b> across
{rooms} room(s) · read in {elapsed} · rules <code>#{rules_id}</code> · {stamp}<br>
Quota: <b>{quota} slots</b> for a target of {lo}–{hi} — {accounting}. Each room's
counter turns red past its share. Grouped by ambiente, and within it by room, in
the order the photographer numbered them — the order they walked the property.
Each room's heading is the name its photographs are delivered under:
<code>QUARTO_02</code> becomes <code>QUARTO_02_0001.jpg</code>. A green
<b class="fix">corrected</b> means the picture disagreed with the filename and the
picture won; <b class="unv">?</b> means nobody checked. Red badges are the strategy
document's hard rules; amber are worth a second look.<br>
<b>The line under each photograph is the room it will be delivered as</b> — change
it when the picture disagrees, or when one room turns out to be two. Two bedrooms
that photograph alike are only told apart here, by looking at them together, so
<code>+ novo QUARTO</code> gives the second one its own number, its own quota and
its own <code>QUARTO_02_NNNN.jpg</code>. Then copy
<code>{catalog_name}</code>, paste it over the file beside this one, and re-run
<code>cull.py --no-classify</code> — free, and it re-cuts the quota for the rooms
you just created.</p>
{note}

{body}

<div id="bar">
  <span id="n">0</span><span>of <b id="cap">{quota}</b> picked</span>
  <button class="go" onclick="copyPicks()">Copiar picks</button>
  <button onclick="setAll(false)">Clear</button>
  <button onclick="fillQuota()">Fill to quota</button>
  <button class="amb" id="cat" onclick="copyCatalog()" hidden></button>
  <span id="over"></span>
  <span id="hint">Paste into <code>picks.txt</code> beside this file, then run
  <code>develop.py</code></span>
</div>

<script type="application/json" id="payload">{payload}</script>

<script>
const boxes = () => [...document.querySelectorAll('input[data-pick]')];
const slotsFor = {{}};
document.querySelectorAll('h2 .count').forEach(el => {{
  slotsFor[el.dataset.for] = parseInt(el.parentElement.textContent.split('/')[1]);
}});

function tally() {{
  const per = {{}};
  boxes().forEach(b => {{ if (b.checked) per[b.dataset.room] = (per[b.dataset.room] || 0) + 1; }});
  let over = 0;
  document.querySelectorAll('h2 .count').forEach(el => {{
    const room = el.dataset.for, n = per[room] || 0;
    el.textContent = n;
    const past = n > slotsFor[room];
    el.classList.toggle('past', past);
    if (past) over += n - slotsFor[room];
  }});
  const total = boxes().filter(b => b.checked).length;
  document.getElementById('n').textContent = total;
  document.getElementById('over').textContent = over
    ? over + ' over quota' : '';
  document.getElementById('over').className = over ? 'past' : '';
}}
document.addEventListener('change', e => e.target.dataset.pick && tally());

function setAll(v) {{ boxes().forEach(b => b.checked = v); tally(); }}

function fillQuota() {{
  // Top-ranked, unflagged, one per angle, up to each room's share. A starting
  // point from the measurements alone — it has not looked at the pictures.
  const used = {{}};
  const seen = {{}};
  boxes().forEach(b => {{
    const room = b.dataset.room, tile = b.closest('.tile');
    const key = room + '|' + [...tile.parentElement.children].indexOf(tile);
    b.checked = false;
    if (!tile.classList.contains('best')) return;
    if (tile.classList.contains('flagged')) return;
    if ((used[room] || 0) >= slotsFor[room]) return;
    used[room] = (used[room] || 0) + 1;
    b.checked = true;
  }});
  tally();
}}

function copyPicks() {{
  // Order follows the page, which is the walkthrough order the photographer
  // numbered. develop.py keeps it, so this is also the gallery order.
  const lines = boxes().filter(b => b.checked).map(b => {{
    const t = document.querySelector(
      'textarea[data-note="' + CSS.escape(b.dataset.pick) + '"]');
    const note = t ? t.value.replace(/\\s+/g, ' ').trim() : '';
    return note ? b.dataset.pick + '   # ' + note : b.dataset.pick;
  }});
  const text = '# picks.txt — uma cena por linha, na ordem da galeria.\\n'
    + '# Um "+" junta os quadros de um bracket numa foto só.\\n'
    + '# Depois de um "#" é comentário, e vai para o registro do trabalho.\\n'
    + lines.join('\\n') + '\\n';
  copyOut(text, document.querySelector('button.go'),
          lines.length + ' linha(s) copiada(s) \\u2713', 'Copiar picks');
}}

/* One clipboard helper for the whole page, with the failure branch the review
   pages have always had and this one never did: under some browsers, and over
   http rather than file://, writeText rejects — and without a catch the button
   did nothing at all and said nothing. A silent copy button is worse than a
   broken one, because you paste the previous clipboard and never notice. */
function copyOut(text, btn, done, back) {{
  navigator.clipboard.writeText(text).then(
    () => {{
      const was = back || btn.textContent;
      btn.textContent = done;
      setTimeout(() => btn.textContent = was, 1800);
    }},
    () => {{
      btn.textContent = 'Clipboard bloqueado \\u2717';
      alert('O navegador bloqueou a cópia.\\n\\n'
            + 'Abra este arquivo direto do disco (file://), não por http.');
      setTimeout(() => btn.textContent = back, 2500);
    }});
}}

/* ---------------------------------------------------------------- the rooms

   Reassigning a photograph is the one correction that cannot be made anywhere
   else: `ambientes.md` can say a photograph is a QUARTO, but only looking at the
   pictures together tells you *which* QUARTO, and this is the only place they
   are side by side.

   The page cannot write the file, same as picks.txt. What it emits instead is
   the catalogue it was handed, with the changed cells rewritten in place — never
   a document composed here. `ambientes.py` owns that format and a second copy of
   it in JS would go stale the first time a column moved.                      */

const PAY = JSON.parse(document.getElementById('payload').textContent);
const sels = () => [...document.querySelectorAll('select.rm')];
const ORIG = new Map(sels().map(s => [s, s.dataset.room]));

function roomsInPlay() {{
  // Every room heading on the page, plus any invented since load. Ordered, so
  // the list reads the same on every tile.
  const out = [...document.querySelectorAll('h2[data-room]')].map(h => h.dataset.room);
  sels().forEach(s => out.includes(s.dataset.room) || out.push(s.dataset.room));
  return out;
}}

function nextFree(amb) {{
  // The lowest index this ambiente does not already use. Counting from the rooms
  // in play rather than from a counter means two photographs sent to
  // `+ novo QUARTO` land in QUARTO_02 and QUARTO_03 — different rooms, which is
  // what asking for a new one twice means. To put both in the same second
  // bedroom, send the first and then pick QUARTO_02 by name for the rest.
  const used = new Set(roomsInPlay()
    .map(r => r.match(/^(.*)_(\\d{{2}})$/))
    .filter(m => m && m[1] === amb).map(m => parseInt(m[2])));
  let i = 1;
  while (used.has(i)) i++;
  return amb + '_' + String(i).padStart(2, '0');
}}

function paint() {{
  const rooms = roomsInPlay();
  sels().forEach(s => {{
    const here = s.dataset.room;
    s.innerHTML = '';
    const g1 = document.createElement('optgroup');
    g1.label = 'Cômodos desta entrega';
    rooms.forEach(r => {{
      const o = document.createElement('option');
      o.value = r; o.textContent = r; o.selected = r === here;
      g1.appendChild(o);
    }});
    const g2 = document.createElement('optgroup');
    g2.label = 'Novo cômodo';
    PAY.slugs.forEach(a => {{
      const o = document.createElement('option');
      o.value = 'new:' + a; o.textContent = '+ novo ' + a;
      g2.appendChild(o);
    }});
    s.append(g1, g2);
    const moved = here !== ORIG.get(s);
    s.classList.toggle('moved', moved);
    // The checkbox counts against the room the photograph is now in, so the
    // quota counters follow a move without a re-run.
    s.parentElement.querySelector('input').dataset.room = here;
  }});
  const n = sels().filter(s => s.dataset.room !== ORIG.get(s)).length;
  const btn = document.getElementById('cat');
  btn.hidden = !n;
  btn.textContent = 'Copy {catalog_name} (' + n + ')';
  tally();
}}

document.addEventListener('change', e => {{
  const s = e.target;
  if (!s.classList || !s.classList.contains('rm')) return;
  s.dataset.room = s.value.startsWith('new:')
    ? nextFree(s.value.slice(4)) : s.value;
  paint();
}});

function copyCatalog() {{
  // Where each file is going now. Keyed by the name as the catalogue writes it,
  // and a bracket's frames all move together because they are one photograph.
  const want = {{}};
  sels().forEach(s => s.dataset.files.split('+')
    .forEach(f => want[f.trim()] = s.dataset.room));

  let changed = 0;
  const out = PAY.catalog.split('\\n').map(line => {{
    if (!line.startsWith('|') || !line.endsWith('|')) return line;
    const cells = line.slice(1, -1).split('|');
    if (cells.length !== 7) return line;
    if (cells.every(c => /^[-: ]*$/.test(c))) return line;   // separator row
    const file = cells[4].trim().replace(/^`|`$/g, '');
    const to = want[file];
    if (!to) return line;
    const m = to.match(/^(.*)_(\\d{{2}})$/);
    if (!m || (cells[0].trim() === m[1] && cells[2].trim() === m[2])) return line;
    // Cell 1 is `Visto` and is deliberately untouched: it records what the last
    // *check* saw, and this is not a check. Leaving it is what makes the gap
    // between the two columns proof that the change was yours.
    const put = (i, v) =>
      cells[i] = ' ' + v.padEnd(Math.max(cells[i].length - 2, v.length)) + ' ';
    put(0, m[1]); put(2, m[2]); put(5, 'manual');
    changed++;
    return '|' + cells.join('|') + '|';
  }}).join('\\n');

  const b = document.getElementById('cat');
  copyOut(out, b, changed + ' linha(s) \\u2713 — cole por cima de {catalog_name}',
          b.textContent);
}}

paint();
</script>
"""


# ----------------------------------------------------------------------- main

def find_shoot(arg: str) -> Path:
    job = Path(arg)
    if not job.is_absolute():
        job = (ROOT / arg) if (ROOT / arg).exists() else (SELECTION_DIR / arg)
    if not job.is_dir():
        sys.exit(f"error: no such shoot folder: {arg}")
    if not (job / "source").is_dir():
        sys.exit(f"error: {rel(job)} has no source/ — run fetch.py first")
    return job


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("shoot", help="the shoot folder, e.g. '0 - selection/Cobertura'")
    ap.add_argument("--workers", type=int, default=WORKERS,
                    help=f"files read at once (default {WORKERS})")
    ap.add_argument("--redo", action="store_true",
                    help="re-read files that already have a proxy")
    ap.add_argument("--type", choices=sorted(DELIVERY_TYPES),
                    help="force the delivery type instead of detecting it. "
                         + " · ".join(f"{k}={v}" for k, v in DELIVERY_TYPES.items()))
    ap.add_argument("--profile-only", action="store_true",
                    help="say what kind of delivery this is and stop; no proxies, "
                         "no sheet, no cost")
    ap.add_argument("--target", metavar="LO-HI",
                    help="override the gallery target from RULES.md, e.g. 25-35")
    ap.add_argument("--vision", action="store_true",
                    help="have a vision model propose each room's picks, with a "
                         "written reason. Costs cents per delivery; without it the "
                         "sheet still works, just with nothing pre-ticked.")
    ap.add_argument("--no-classify", action="store_true",
                    help="skip checking the room names against the pictures. The "
                         "check runs by default because the name it settles becomes "
                         "the delivered filename; skipping it means trusting the "
                         "photographer's labels unverified.")
    ap.add_argument("--model", help="vision model (default: see vision.py)")
    args = ap.parse_args()

    try:
        rules = load_rules()
    except RulesError as e:
        sys.exit(f"error: {e}")
    try:
        vocab = ambientes.load()
    except ambientes.AmbientesError as e:
        sys.exit(f"error: {e}")

    job = find_shoot(args.shoot)
    source = job / "source"
    proxies = job / "_proxies"

    photos = sorted(p for p in source.rglob("*")
                    if p.is_file() and p.suffix.lower() in PHOTO_EXTS)
    if not photos:
        sys.exit(f"error: no photos under {rel(source)}")

    # Profile first, on headers alone. A second here beats seventeen spent
    # processing a delivery the wrong way.
    t_profile = time.time()
    prof = profile_delivery(photos, source, args.workers, vocab)
    if args.type and args.type != prof.kind:
        print(f"profile     detected type {prof.kind}, overridden to "
              f"{args.type} by --type")
        prof.why.insert(0, f"**forced to type {args.type} with `--type`** — "
                           f"detection said {prof.kind}")
        prof.kind = args.type
    write_profile(job, prof)

    print(f"\n{job.name} · {len(photos)} file(s) · "
          f"profiled in {time.time() - t_profile:.1f}s")
    print(f"type        {prof.kind} — {prof.label}")
    for w in prof.why:
        print(f"            {w.replace('**', '')}")
    print(f"measured    {prof.raw_share:.0%} raw · {prof.exif_share:.0%} timestamped · "
          f"{prof.labelled_share:.0%} room-named · {prof.bracket_share:.0%} bracketed · "
          f"{len(prof.rooms)} room(s)")
    for c in prof.caveats:
        print(f"caveat      {c}")
    print(f"profile     {rel(job / 'profile.md')}")

    if args.profile_only:
        print("\nStopping here (--profile-only). Drop the flag to build the sheet.")
        return

    if prof.needs_room_recognition:
        print("\nnote        the rooms are not in the filenames, so they are "
              "recognised from\n            the pictures instead — that is what the "
              "classification pass is\n            for, and it runs below unless "
              "--no-classify is set.")
    if prof.needs_bracket_merge:
        print(f"\nnote        {prof.bracket_share:.0%} of the files belong to a bracket. "
              "They are shown as one\n            scene each here; the merge happens in "
              "develop.py.")

    todo = photos if args.redo else [
        p for p in photos if not (proxies / f"{p.stem}.jpg").exists()]
    print(f"\nreading     {len(photos)} file(s)"
          f"{f' ({len(photos) - len(todo)} already read)' if len(todo) < len(photos) else ''}"
          f" · {args.workers} at a time")

    t0 = time.time()
    facts: "list[ingest.Facts]" = []
    failed: "list[tuple[Path, str]]" = []

    def read_one(p: Path) -> "tuple[Path, ingest.Facts | None, str]":
        try:
            return p, ingest.read(p, proxies), ""
        except ingest.IngestError as e:
            return p, None, str(e)
        except Exception as e:                  # noqa: BLE001 — one bad file must not stop the shoot
            return p, None, f"{type(e).__name__}: {e}"

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = [pool.submit(read_one, p) for p in todo]
        for n, fut in enumerate(as_completed(futures), 1):
            p, f, err = fut.result()
            if f:
                facts.append(f)
            else:
                failed.append((p, err))
            if n % 25 == 0 or n == len(todo):
                print(f"  read {n}/{len(todo)}  {time.time() - t0:.0f}s", flush=True)

    # Files skipped this run still belong to the shoot — re-read their facts
    # from the proxy so grouping sees the whole delivery, not just the new part.
    if len(todo) < len(photos):
        print("  re-reading facts for already-proxied files ...", flush=True)
        for p in photos:
            if p not in set(todo):
                try:
                    facts.append(ingest.read(p, proxies))
                except Exception:               # noqa: BLE001
                    pass

    if not facts:
        sys.exit("error: nothing could be read")

    for f in facts:
        room, order, shot, area, area_order = parse_labels(f.path, source, vocab)
        f.notes.append(f"__labels__{json.dumps([room, order, shot, area, area_order])}")

    scenes = group_brackets(facts)
    for s in scenes:
        f = s.lead
        tag = next((n for n in f.notes if n.startswith("__labels__")), None)
        if tag:
            s.room, s.room_order, s.shot, s.area, s.area_order = json.loads(tag[10:])
    for f in facts:
        f.notes[:] = [n for n in f.notes if not n.startswith("__labels__")]

    n_clusters = cluster_scenes(scenes)
    for s in scenes:
        assess(s, rules)

    # The profile guessed type A for a small unlabelled delivery without being
    # able to check. The clustering just produced the evidence, so check now:
    # a finished selection is nearly all distinct angles, a dump is not.
    dup_share = 1 - (n_clusters / max(1, len(scenes)))
    if prof.kind == "A" and not prof.rooms and dup_share > 0.25:
        print(f"\n!! The profile called this a finished selection, but "
              f"{dup_share:.0%} of it is near-duplicates\n"
              f"   ({len(scenes)} scenes collapse to {n_clusters} distinct angles). "
              "A finished selection\n"
              "   does not repeat itself like that — this looks like a raw dump.\n"
              "   Re-run with --type C to curate it.")
        prof.caveats.append(
            f"the near-duplicate check contradicted the guess: {dup_share:.0%} of "
            f"these are near-duplicates, which a finished selection would not be. "
            "Consider `--type C`.")
        write_profile(job, prof)

    # --- naming ---------------------------------------------------------------
    # The filename every picked photograph is delivered under is settled here, and
    # only here. Three sources, in order of authority, each overriding the one
    # before it: the photographer's label, the model's look at the pixels, and your
    # own edits in `ambientes.md`.
    # Type C is the case where the label is not evidence: camera filenames, and a
    # folder named after the job rather than the room. Taking it anyway hands the
    # classifier a premise instead of a question — it then verifies one room for
    # the whole delivery and can only confirm or correct that single answer, so
    # the per-photograph pass that would have split the delivery never fires.
    # Measured on `WC-00660`, whose folder starts `WC-`: all 48 photographs of a
    # whole house arrived as one BANHEIRO, corrected to one NAO_IDENTIFICADO.
    # The label stays on the scene for the sheet's headings; only the ambiente it
    # would have claimed is withheld.
    named = 0 if prof.needs_room_recognition else name_rooms(scenes, vocab)

    # Read here rather than inside `classify_rooms`, which is where it used to
    # live. `--no-classify` skips that function whole, so the catalogue went
    # unread with it — and on a type-C delivery, where the filenames name nothing
    # either, the run then had no source of an ambiente at all and produced a
    # sheet with every room blank. Which meant there was no cheap way to re-run
    # after correcting the catalogue: the correction could only be applied by the
    # pass you were trying to avoid paying for.
    prior = ambientes.read_catalog(job)
    if prior:
        print(f"catalogue   {len(prior)} row(s) read from "
              f"{ambientes.CATALOG_NAME} — your edits there win")

    provisional = group_rooms(scenes, rules)        # batches for the classifier
    if args.no_classify:
        kept = apply_catalog(scenes, prior, only_edited=False)
        print("\nambientes   not verified (--no-classify) — "
              + (f"{kept} name(s) kept from {ambientes.CATALOG_NAME}, unchecked "
                 "against\n            the pictures"
                 if kept else
                 "the room names are the filenames'\n            word, unchecked "
                 "against the pictures"))
        verified, ambiente_note = False, (
            "The room names were <b>not verified against the pictures</b> "
            "(<code>--no-classify</code>), so they are "
            + (f"the {kept} answer(s) already in <code>ambientes.md</code>."
               if kept else "whatever the filenames said."))
    else:
        verified, ambiente_note = classify_rooms(job, provisional, vocab,
                                                 args.model, args.workers, prior)
    groups = group_rooms(scenes, rules, vocab, prior)   # authoritative

    # The second half of the check above, and the one with real evidence behind
    # it. A delivery with no labels at all is genuinely ambiguous from filenames —
    # the profile guesses A because erring that way is the safe error — and the
    # near-duplicate count settles it only for a photographer who repeats angles.
    # One who does not leaves the guess standing on nothing.
    #
    # Now the rooms are named, so the *same* question the labelled path answers at
    # profiling time can be asked here with the same constant: a finished selection
    # runs about three photographs to a room. Eight of the living room is a dump.
    #
    # Switching is safe in a way that cutting would not be: the quota decides what
    # arrives pre-ticked and what the counter allows, never what appears on the
    # page. Every photograph is still there to tick. Without this, every delivery
    # whose photographer uses camera filenames needs `--type C` typed by hand,
    # forever.
    per_room = len(scenes) / max(1, len(groups))
    if (prof.kind == "A" and not prof.rooms and not args.type
            and per_room > ALREADY_CULLED_MAX_PER_ROOM):
        print(f"\n!! The profile called this a finished selection, but the rooms "
              f"came back at\n   {per_room:.1f} photos each ({len(scenes)} across "
              f"{len(groups)} rooms). A finished selection runs about\n"
              f"   {ALREADY_CULLED_MAX_PER_ROOM:.0f}. Treating it as a shoot and "
              "applying the quota — every photo is still on the\n"
              "   sheet, so tick anything the quota did not. Force it back with "
              "--type A.")
        prof.kind = "C"
        prof.caveats.append(
            f"profiled as A from the filenames, then contradicted once the rooms "
            f"were named: {per_room:.1f} photos per room against the "
            f"{ALREADY_CULLED_MAX_PER_ROOM:.0f} a finished selection runs. Switched "
            "to C and curated. `--type A` forces the original guess back.")
        write_profile(job, prof)

    catalog = write_catalog(job, groups, vocab, verified)

    # A delivery someone already curated gets no quota at all — every frame is
    # taken, because cutting it would drop photographs that were chosen on
    # purpose. It still gets a sheet, so you can look at what you were sent.
    if prof.curate:
        target = parse_target(args.target) if args.target else None
        story = allocate(groups, rules, target)
        lo, hi = story["target"]
        _, _, size_warning = rules.target_for(len(groups)) if not target else (0, 0, None)
    else:
        for g in groups:
            g.base = g.slots = g.angles
            for cluster in g.clusters:
                for s in cluster:
                    s.chosen = True
        story = {"base": sum(g.slots for g in groups), "expanded": 0, "trimmed": 0,
                 "target": (0, 0), "grew": [], "cut": [],
                 "total": sum(g.slots for g in groups), "in_range": True,
                 "capped": []}
        size_warning = None

    vision_note = ""
    if args.vision and prof.curate:
        vision_note = run_vision(job, groups, rules, args.model, args.workers)

    note = ""
    if not prof.curate:
        note = ("This delivery was already curated by someone, so nothing was cut and "
                "everything is ticked. Untick anything you disagree with.")
    elif vision_note:
        note = vision_note
    elif not args.vision:
        note = ("Nothing is pre-ticked: the quota says how many each room gets, but "
                "not which ones. Re-run with <code>--vision</code> to have a model "
                "propose them with a written reason, or press "
                "<b>Fill to quota</b> to take the top-ranked frame of each angle.")
    if size_warning and note:
        note += "<br>" + size_warning
    elif size_warning:
        note = size_warning
    # The naming note goes first: it is the one thing on the sheet that decides
    # what leaves this stage, so an unverified run has to say so before anything
    # else competes for attention.
    if ambiente_note:
        note = ambiente_note + ("<br>" + note if note else "")

    elapsed = time.time() - t0
    sheet = write_contact_sheet(job, groups, prof, rules, story, elapsed, note,
                                vocab)

    brackets = [s for s in scenes if s.is_bracket]
    flagged = [s for s in scenes if s.flags]
    labelled = sum(1 for s in scenes if s.room)
    sizes = defaultdict(int)
    for s in scenes:
        sizes[s.cluster] += 1

    print(f"\nfiles       {len(facts)} read"
          + (f", {len(failed)} unreadable" if failed else ""))
    for p, err in failed[:8]:
        print(f"  !! {p.name}: {err}")
    print(f"brackets    {len(brackets)} bracket(s) covering "
          f"{sum(len(s.frames) for s in brackets)} file(s)"
          + ("  — none detected; treating every file as its own scene"
             if not brackets else ""))
    print(f"scenes      {len(scenes)}")
    print(f"angles      {n_clusters} distinct  "
          f"(biggest cluster {max(sizes.values()) if sizes else 0} scenes, "
          f"{sum(1 for v in sizes.values() if v == 1)} singletons)")
    print(f"rooms       {labelled}/{len(scenes)} scene(s) labelled from the filename, "
          f"{named} mapped to an ambiente")
    by_ambiente = defaultdict(int)
    for g in groups:
        by_ambiente[g.ambiente] += 1
    print(f"ambientes   {len(by_ambiente)} ambiente(s) over {len(groups)} room(s): "
          + ", ".join(f"{a}×{n}" if n > 1 else a
                      for a, n in sorted(by_ambiente.items()))[:300])
    unknown = [g.name for g in groups if g.ambiente == ambientes.UNKNOWN]
    if unknown:
        print(f"            !! {len(unknown)} room(s) could not be named: "
              f"{', '.join(unknown[:6])}\n"
              f"               name them by hand in {rel(catalog)}, or add the "
              f"photographer's word to\n               {rel(ambientes.AMBIENTES_PATH)}")
    print(f"flagged     {len(flagged)} scene(s) hit a hard rule")
    print(f"rules       #{rules.fingerprint}  {rel(RULES_PATH)}")
    print(f"vocabulary  #{vocab.fingerprint}  {rel(ambientes.AMBIENTES_PATH)}")

    if prof.curate:
        lo, hi = story["target"]
        print(f"quota       {story['total']} slot(s) for a target of {lo}-{hi}"
              f"{'  ok' if story['in_range'] else '  OUT OF RANGE'}")
        print(f"            {story['base']} from the floor of {rules.base_per_room} "
              f"per room"
              + (f", +{story['expanded']} expanded" if story["expanded"] else "")
              + (f", -{story['trimmed']} trimmed" if story["trimmed"] else ""))
        if story["capped"]:
            print(f"            {len(story['capped'])} room(s) took fewer than "
                  f"{rules.base_per_room} because that is all they have: "
                  f"{', '.join(story['capped'][:6])}")
        unmatched = [g.name for g in groups if g.category == "default"]
        if unmatched:
            print(f"            !! {len(unmatched)} room(s) fell to default priority: "
                  f"{', '.join(unmatched[:6])}\n"
                  f"               their categoria in {rel(ambientes.AMBIENTES_PATH)} "
                  f"has no priority row in\n               {rel(RULES_PATH)}")
        if size_warning:
            print(f"            !! {size_warning}")
    else:
        print(f"quota       none — type A, all {story['total']} scenes pre-ticked")

    print(f"proxies     {rel(proxies)}")
    print(f"sheet       {rel(sheet)}   ({elapsed:.0f}s)")
    print(f"\nOpen it:  open \"{sheet}\"")
    print("Then tick, copy picks.txt into the shoot folder, and run:\n"
          f'  ./_config/.venv/bin/python "0 - selection/develop.py" "{rel(job)}"')


def name_rooms(scenes: "list[Scene]", vocab: "ambientes.Vocabulary") -> int:
    """The free pass: the photographer's own label, mapped to the vocabulary.

    Runs before anything is uploaded and gets most of the delivery right on its
    own — one measured shoot labelled 277 of its 307 files, and every label mapped
    to the correct ambiente. Returns how many scenes it could name.
    """
    named = 0
    for s in scenes:
        slug, _ = vocab.slug_for(s.room)
        if slug:
            s.ambiente = s.ambiente_visto = slug
            s.ambiente_source = "keyword"
            named += 1
    return named


def apply_catalog(scenes: "list[Scene]", prior: dict, only_edited: bool) -> int:
    """Put `ambientes.md`'s answers back onto the scenes. Returns how many landed.

    Two callers wanting two different things out of the same file, which is why
    the flag is here rather than two functions:

    - **`--no-classify`** takes every row (`only_edited=False`). The catalogue is
      then the *only* source of an ambiente — the classifier that would otherwise
      supply one is not running — so honouring just the hand-edited rows would
      hand back a delivery with no room names at all. That was the behaviour
      before this function existed, and it made the free re-run useless on any
      delivery whose rooms came from the pictures rather than the filenames.
    - **the classifying path** takes only the rows a person changed. Everything
      else is re-verified, because a catalogue that outranked the check would
      freeze the first answer forever and quietly stop checking.

    `visto` is copied through untouched in both cases. It records what a *check*
    saw, and neither caller here is a check; overwriting it would erase the gap
    that proves an edit was yours.
    """
    landed = 0
    for s in scenes:
        row = next((prior[k] for k in
                    (ambientes.fold_name(f.path.name) for f in s.frames)
                    if k in prior), None)
        if not row or (only_edited and not row.edited):
            continue
        s.ambiente = row.ambiente
        s.ambiente_visto = row.visto
        s.ambiente_source = "manual" if row.edited else row.source
        s.ambiente_note = row.note
        landed += 1
    return landed


def classify_rooms(job: Path, groups: "list[RoomGroup]",
                   vocab: "ambientes.Vocabulary", model: "str | None",
                   workers: int, prior: dict) -> "tuple[bool, str]":
    """Check every room's name against the pictures. Returns (verified, note).

    Never fatal. A room the model could not judge keeps whatever the filename said,
    which is the answer that was right most of the time anyway — this pass is a
    check on the photographer's labelling, not a replacement for it.

    Your own corrections in `ambientes.md` outrank both, and a room already marked
    `manual` there is not sent to the model at all — it was settled by a person, and
    paying to have it second-guessed every run would be waste as well as an
    invitation to undo the fix.

    Everything else is re-verified on every run, including rooms a previous run
    already checked. That is deliberate and it is the difference between a cache and
    a decision: the catalogue cannot tell "the last run wrote this" from "a person
    wrote this" by looking at the ambiente alone, so the run recomputes, compares,
    and only then concludes that a value which no longer matches must have come from
    you. Skipping the recompute would freeze the first answer forever and quietly
    stop checking, which is the one thing this pass exists to do.
    """
    import vision as vision_mod

    from dotenv import load_dotenv
    load_dotenv(ROOT / "_config" / ".env")
    import os

    settled, todo = [], []
    for g in groups:
        frames = [f for c in g.clusters for s in c for f in s.frames]
        rows = [prior.get(ambientes.fold_name(f.path.name)) for f in frames]
        edited = {r.ambiente for r in rows if r and r.edited}
        if len(edited) == 1 and all(r and r.edited for r in rows):
            settled.append((g, rows[0]))
        else:
            todo.append(g)

    # A room you have already corrected keeps your answer *and* the value the check
    # last saw, so the difference that proves it was your decision survives into the
    # next run instead of being erased by the one that honours it.
    for g, row in settled:
        _apply_ambiente(g, row.ambiente, "manual", visto=row.visto)

    if not os.environ.get("FAL_KEY"):
        print("\nambientes   not verified — FAL_KEY is not set (see _config/.env), so "
              "the\n            room names are the filenames' word, unchecked")
        return False, ("The room names were <b>not verified against the pictures</b> — "
                       "<code>FAL_KEY</code> is not set, so they are whatever the "
                       "filenames said.")
    if not todo:
        print(f"\nambientes   all {len(settled)} room(s) already settled in "
              f"{ambientes.CATALOG_NAME} — nothing to verify")
        return True, ""

    model = model or vision_mod.VISION_MODEL
    print(f"\nambientes   verifying {len(todo)} room(s) · {model} · "
          f"{workers} at a time"
          + (f" · {len(settled)} already settled by hand" if settled else ""))

    url_cache: dict = {}
    t0 = time.time()
    # Keyed by identity and not by `g.name`, which is a property over `g.ambiente`
    # and therefore changes the moment the answer is applied below. Keying on it
    # made every corrected room look unverified afterwards.
    results: "dict[int, object]" = {}

    def look(g: RoomGroup):
        leads = [c[0] for c in g.clusters]
        return g, vision_mod.classify(g.room, g.ambiente if g.ambiente_source else None,
                                      leads, vocab, url_cache, model)

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for fut in as_completed([pool.submit(look, g) for g in todo]):
            g, c = fut.result()
            results[id(g)] = c
            if not c.ok:
                print(f"  !! {(g.room or '(unlabelled)'):24s} kept {g.ambiente} "
                      f"— {c.error}")
            elif c.per_image:
                print(f"  ??  {(g.room or '(unlabelled)'):24s} unsorted — named "
                      "each photo")
            elif c.corrigido:
                print(f"  ->  {(g.room or '(unlabelled)'):24s} "
                      f"{g.ambiente or '?'} -> {c.ambiente}"
                      + (f"  ({c.porque})" if c.porque else ""))
            else:
                print(f"  ok  {(g.room or '(unlabelled)'):24s} {c.ambiente}")
            if c.note:
                print(f"      {c.note}")

    corrected = moved = split = 0
    for g in todo:
        c = results.get(id(g))
        if not c or not c.ok:
            continue
        if c.corrigido and not c.per_image:
            corrected += 1
        # `filename` means the label was read *and* the pictures agreed with it,
        # which is a stronger claim than `keyword` — that one is only ever a guess
        # nobody checked. The catalogue's legend leans on the difference.
        _apply_ambiente(g, c.ambiente, "vision" if c.corrigido else "filename",
                        c.porque if c.corrigido else "")
        # Per-photo answers are set on the scene, and the second grouping pass is
        # what actually moves them — a photograph of somewhere else becomes its own
        # room rather than a footnote inside the wrong one.
        #
        # `vision_mod.fold` and not the `fold` in this module: they are different
        # functions with the same name, and these keys were built with that one.
        # This module's folds accents away for keyword matching; vision's composes
        # Unicode for filename matching, which is what these keys are.
        seen_here = set()
        for cluster in g.clusters:
            for s in cluster:
                for f in s.frames:
                    hit = c.named.get(vision_mod.fold(f.path.name))
                    if hit:
                        s.ambiente = s.ambiente_visto = hit[0]
                        s.ambiente_source = "vision"
                        s.ambiente_note = hit[1]
                        seen_here.add(hit[0])
                        moved += 1
                        break
        if c.per_image:
            split += max(0, len(seen_here) - 1)

    # Your corrections are applied last, over everything the model just decided.
    for g in groups:
        for cluster in g.clusters:
            for s in cluster:
                row = next((prior[ambientes.fold_name(f.path.name)]
                            for f in s.frames
                            if ambientes.fold_name(f.path.name) in prior), None)
                if row and row.edited and row.ambiente != s.ambiente:
                    # `ambiente_visto` keeps what the check just saw, so the gap
                    # that marks this as yours is still there on the next run.
                    s.ambiente, s.ambiente_source = row.ambiente, "manual"
                    s.ambiente_note = ""

    calls = sum(c.calls for c in results.values())
    failed = [g.room or "(unlabelled)" for g in todo
              if not (results.get(id(g)) and results[id(g)].ok)]
    labelled = [g for g in todo if results.get(id(g))
                and not results[id(g)].per_image]
    print(f"ambientes   {corrected} of {len(labelled)} label(s) corrected · "
          f"{moved} photo(s) named individually"
          + (f" · {split} extra room(s) found in unsorted folders" if split else "")
          + f" · {calls} call(s) · {time.time() - t0:.0f}s"
          + (f" · {len(failed)} room(s) unverified" if failed else ""))

    note = (f"Room names checked against the pictures by "
            f"<code>{html.escape(model)}</code>. ")
    note += (f"{corrected} differed from the filename and were corrected. "
             if corrected else "Every label agreed with the pictures. ")
    if moved:
        note += (f"{moved} photograph(s) had no usable label and were named one by "
                 "one. ")
    if failed:
        note += ("Could not be checked, so kept the filename's word: "
                 + html.escape(", ".join(failed[:6])) + ". ")
    return True, note.strip()


def _apply_ambiente(g: RoomGroup, slug: str, source: str, note: str = "",
                    visto: "str | None" = None) -> None:
    """Write one room's decided ambiente onto every scene in it.

    `visto` defaults to the answer itself, which is the case for every source but
    `manual`: the check saw what it decided. Only an honoured correction passes a
    different one, because there the two genuinely differ.
    """
    g.ambiente, g.ambiente_source, g.ambiente_note = slug, source, note
    for cluster in g.clusters:
        for s in cluster:
            s.ambiente, s.ambiente_source, s.ambiente_note = slug, source, note
            s.ambiente_visto = slug if visto is None else visto


def run_vision(job: Path, groups: "list[RoomGroup]", rules: Rules,
               model: "str | None", workers: int) -> str:
    """Have a model propose each room's picks. Returns a note for the sheet.

    Never fatal. A room the model could not judge simply arrives with nothing
    pre-ticked and says so — the contact sheet is the deliverable, and it is
    useful with or without an opinion attached to it.
    """
    import vision as vision_mod

    from dotenv import load_dotenv
    load_dotenv(ROOT / "_config" / ".env")
    import os
    if not os.environ.get("FAL_KEY"):
        print("\nvision      skipped — FAL_KEY is not set (see _config/.env)")
        return ("The vision pass was skipped because <code>FAL_KEY</code> is not set, "
                "so nothing is pre-ticked.")

    model = model or vision_mod.VISION_MODEL
    todo = [g for g in groups if g.clusters and g.slots]
    print(f"\nvision      {len(todo)} room(s) · {model} · {workers} at a time")

    url_cache: dict = {}
    t0 = time.time()
    verdicts: "dict[str, object]" = {}

    def judge(g: RoomGroup):
        # One contender per angle: the model should compare distinct views, not
        # spend its attention on two frames of the same corner.
        leads = [c[0] for c in g.clusters]
        return g, vision_mod.choose(g.heading, leads, g.slots, rules, url_cache,
                                    model)

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for n, fut in enumerate(as_completed([pool.submit(judge, g) for g in todo]), 1):
            g, v = fut.result()
            verdicts[g.name] = v
            mark = "ok " if v.ok else "!! "
            print(f"  {mark}{g.name:22s} {len(v.picks)}/{g.slots} in {v.calls} call(s)"
                  + (f"  — {v.error}" if not v.ok else ""))

    failed = [name for name, v in verdicts.items() if not v.ok]
    unmatched = sum(len(v.unmatched) for v in verdicts.values())

    for g in todo:
        v = verdicts.get(g.name)
        if not v or not v.ok:
            continue
        for p in v.picks:
            s = p["scene"]
            s.chosen = True
            s.reason = p["reason"]
            s.purpose, s.staging = p["purpose"], p["staging"]
        for r in v.rejected:
            r["scene"].rejected_why = r["why"]

    picked = sum(1 for g in groups for c in g.clusters for s in c if s.chosen)
    calls = sum(v.calls for v in verdicts.values())
    print(f"vision      {picked} pre-ticked · {calls} call(s) · "
          f"{time.time() - t0:.0f}s"
          + (f" · {len(failed)} room(s) failed" if failed else "")
          + (f" · {unmatched} invented filename(s) dropped" if unmatched else ""))

    write_selection(job, groups, rules, verdicts, model)
    print(f"selection   {rel(job / 'selection.md')}")

    note = (f"Pre-ticked by <code>{html.escape(model)}</code>, with its reason on each "
            "tile. It has never seen this property and does not know what the listing "
            "promises — treat it as a first draft.")
    if failed:
        note += (f" {len(failed)} room(s) could not be judged and are empty: "
                 + html.escape(", ".join(failed)) + ".")
    return note


def write_catalog(job: Path, groups: "list[RoomGroup]",
                  vocab: "ambientes.Vocabulary", verified: bool) -> Path:
    """`ambientes.md` — what room every file is of, and where that answer came from.

    Written in walkthrough order, one row per source file rather than per scene, so
    a bracket's five frames are each accounted for and any one of them can carry a
    correction. It is read back on the next run: this is the stage's edit surface,
    not a report.
    """
    rows = []
    for g in groups:
        for cluster in g.clusters:
            for s in cluster:
                for f in s.frames:
                    rows.append(ambientes.Row(
                        ambiente=s.ambiente or g.ambiente,
                        visto=s.ambiente_visto or "",
                        sala=g.sala_idx,
                        label=s.room or "",
                        filename=f.path.name,
                        source=s.ambiente_source or "none",
                        note=s.ambiente_note))
    dest = ambientes.write_catalog(job, rows, vocab.fingerprint, verified,
                                   datetime.now().strftime("%Y-%m-%d %H:%M"))
    print(f"ambientes   {rel(dest)}")
    return dest


def write_selection(job: Path, groups: "list[RoomGroup]", rules: Rules,
                    verdicts: dict, model: str) -> Path:
    """`selection.md` — the choice, by room, with the reason for each.

    The shape comes from the process this project's team was already running by
    hand, and it is better than a bare list of filenames: a selection you cannot
    justify is one you cannot defend to the client, and one you cannot audit
    later when a listing underperforms.
    """
    total = sum(len(v.picks) for v in verdicts.values() if v.ok)
    L = [f"# {job.name} — selection", "",
         f"_{total} photo(s) proposed by `{model}` against "
         f"`_config/Seletor/RULES.md` `#{rules.fingerprint}`. "
         "Edit freely — this file is a record, not a lock._", "",
         "Rooms are in the order the photographer numbered them, which is the order "
         "they walked the property, and that is the gallery order.", ""]

    for g in groups:
        v = verdicts.get(g.name)
        L.append(f"## {g.heading}")
        L.append("")
        if not v:
            L += ["_Not judged._", ""]
            continue
        if not v.ok:
            L += [f"⚠️ Could not be judged: {v.error}", ""]
            continue
        L.append(f"{len(v.picks)} of {g.slots} slot(s) · {g.scenes} photos · "
                 f"{g.angles} distinct angles · category `{g.category}`")
        L.append("")
        if not v.picks:
            L += ["_The model returned nothing for this room._", ""]
            continue
        L += ["| # | Photo | Why | Purpose | Staging |", "|---|---|---|---|---|"]
        for p in v.picks:
            name = p["scene"].lead.path.name
            L.append(f"| {p['rank']} | `{name}` | {p['reason'] or '—'} | "
                     f"{p['purpose'] if p['purpose'] is not None else '—'} | "
                     f"{p['staging'] if p['staging'] is not None else '—'} |")
        L.append("")
        # Capped and deliberately not called "rejected". The model volunteers a
        # comment on far more frames than it rejects — for one room it listed
        # twenty-two, nine of them with the same sentence — and calling that a
        # rejection list makes the file unreadable and overstates what happened.
        # These are the ones it had something to say about; the frames that
        # actually broke a rule are in the measured section at the end.
        if v.rejected:
            unique = []
            seen_why: set = set()
            for r in v.rejected:
                key = r["why"].lower()[:60]
                if key not in seen_why:
                    seen_why.add(key)
                    unique.append(r)
            L += ["Passed over, in its words:", ""]
            for r in unique[:5]:
                L.append(f"- `{r['scene'].lead.path.name}` — {r['why']}")
            if len(v.rejected) > len(unique[:5]):
                L.append(f"- … and {len(v.rejected) - len(unique[:5])} more it "
                         "commented on")
            L.append("")

    flagged = [(g, s) for g in groups for c in g.clusters for s in c if s.flags]
    if flagged:
        L += ["---", "", "## Failed a measured rule", "",
              "Geometry, not opinion — measured from the pixels, not judged by the "
              "model. Shown for the record; they are still on the contact sheet and "
              "can still be picked.", ""]
        for g, s in flagged[:40]:
            L.append(f"- `{s.lead.path.name}` ({g.name}) — {'; '.join(s.flags)}")
        if len(flagged) > 40:
            L.append(f"- … {len(flagged) - 40} more")
        L.append("")

    (job / "selection.md").write_text("\n".join(L), encoding="utf-8")
    return job / "selection.md"


def parse_target(spec: str) -> "tuple[int, int]":
    if m := re.match(r"^(\d+)\s*[-–]\s*(\d+)$", spec.strip()):
        return int(m.group(1)), int(m.group(2))
    if spec.strip().isdigit():
        n = int(spec)
        return n, n
    sys.exit(f"error: --target wants a range like 40-60, or a single number, not "
             f"{spec!r}")


if __name__ == "__main__":
    main()
