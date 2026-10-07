#!/usr/bin/env python3
"""Ask a vision model what a room is, whether two of them are one, and which
photographs of it are best.

Called by `cull.py`. Standalone, it runs the ranking for one room so a prompt
change can be judged for a few cents instead of a whole delivery:

    ./_config/.venv/bin/python "0 - selection/vision.py" "0 - selection/Cobertura" --room Cozinha

**Three questions, and the unit of a call is different for each**, because what
has to be in view to answer differs:

- `choose()` — *which of these is best?* **One call per room.** Choosing the best
  three of twenty-one kitchen shots is a comparison, and a comparison cannot be
  made one photograph at a time: score them individually and you get twenty-one
  opinions with no way to enforce "at most three".
- `split_rooms()` — *which of these are the same physical room?* **One call per
  ambiente**, every photograph of it in view at once. Compare a photograph against
  only half the set and it can be filed as a new room because its real room was in
  the other half.
- `classify()` — *what room is this?* One call per room when there is a label to
  confirm, and **one call per photograph when there is not**. With no label there
  is no set to compare against and nothing to defend, so batching buys nothing and
  costs everything: the answer array truncated at `MAX_TOKENS` and each missing
  photograph inherited the batch's majority vote. That is how photographs of a bed
  were delivered as `COZINHA`.

The model judges what a measurement cannot see: what the room is for, whether it
looks cared for, whether the set hangs together, and the strategy document's
rejections that need eyes — an open toilet, an unmade bed, cables on a counter.

Levelness and lens geometry go the other way. Those are measured by `ingest.py`
and sent as **verdicts, not numbers** — "level", "verticals splay badly" — because
a number without its scale is worse than no number at all. Handed `lean 0.9°` the
model called it "inclinação acentuada"; 0.9° is better than this photographer's
median. The thresholds live in `RULES.md`, which the model never sees, so the
comparison happens here and only the conclusion travels.

Blur is left to the model on purpose. The Laplacian score `ingest.py` computes is
only meaningful *relative to the same subject* — a sharp photograph of a plain
wall scores below a soft one of a bookcase — so it ranks frames within one angle
and is never quoted as a quality.

The ranking instructions live in `../_config/Seletor/RULES.md` between its
`===== VISION PROMPT` markers, alongside the quota they have to respect. The
three naming instructions live in `AMBIENTES.md`, one block per question. Nothing
about what makes a good photograph, or about what makes a room, is hard-coded
here.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path

from PIL import Image

import ambientes

SELECTION_DIR = Path(__file__).resolve().parent
ROOT = SELECTION_DIR.parent

# The one name this file needs from the vocabulary, and it must be *the* one: an
# unknown that does not match `AMBIENTES.md`'s row is not a valid answer anywhere
# downstream.
UNKNOWN_SLUG = ambientes.UNKNOWN

VISION_ENDPOINT = "fal-ai/any-llm/vision"

VISION_MODEL = "google/gemini-2.5-flash-lite"

# Naming a room is a separate question from ranking photographs, and a more
# expensive one to get wrong: the answer becomes the filename a client receives,
# where a bad pick is only a photograph nobody would have chosen. Split out so the
# two can be priced apart — raise this one alone when the room names look careless.
CLASSIFY_MODEL = VISION_MODEL

# Images per call. A room with fifty angles cannot go in one request — too many
# tokens, and the model's attention thins out across them — so large rooms run a
# tournament instead.
BATCH_MAX_IMAGES = 12

# Telling one bedroom from a second bedroom means holding every bedroom in view at
# once, so this question cannot be split into heats the way ranking can — a
# photograph compared only against half the set can be filed as a new room because
# its real room was in the other half. Above this count the split is skipped and
# says so, which leaves the rooms merged and correctable by hand; inventing a
# QUARTO_02 out of a partial view is the worse error.
SPLIT_MAX_IMAGES = 12

# Sent at this long edge, downscaled from the 1600px proxy. Images dominate the
# token bill, and a 1024px frame is plenty to see clutter, a rumpled duvet, or a
# toilet in shot.
VISION_LONG_EDGE = 1024
VISION_JPEG_QUALITY = 85

# Low, because this is a judgement against fixed criteria, not a creative task —
# and because two runs over the same delivery should mostly agree.
TEMPERATURE = 0.2

# Zero for the two naming questions, which are not judgements at all. "Is there a
# bed in this picture" and "is this the same bedroom as that one" have answers,
# and the sampling that gives a ranking pass its useful variety only makes these
# unstable. Measured on `WC-00284` at 0.2: one run in three split the veranda into
# two rooms over four photographs of one hammock, and a wrong `VARANDA_02` is a
# wrong filename. Which run you got decided the delivery.
CLASSIFY_TEMPERATURE = 0.0

MAX_TOKENS = 2000

# The model is told to answer in JSON, but the endpoint has no structured-output
# mode, so the answer is free text that usually *is* JSON. One retry with a
# blunter instruction, then give up on that room rather than the delivery.
PARSE_ATTEMPTS = 2


class VisionError(Exception):
    """This room could not be judged. Never fatal to the delivery."""


@dataclass
class Verdict:
    """One room's answer, already matched back to real files."""
    room: str
    picks: "list[dict]" = field(default_factory=list)     # file, rank, reason, ...
    rejected: "list[dict]" = field(default_factory=list)  # file, why
    # Photographs the model says are not of this room at all. A different claim
    # from `rejected`, which is about a photograph being *bad*, and the only place
    # in the run where the ranking pass can push back on the name it was handed.
    not_room: "list[dict]" = field(default_factory=list)  # scene, why
    calls: int = 0
    seconds: float = 0.0
    model: str = ""
    unmatched: "list[str]" = field(default_factory=list)
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


# ---------------------------------------------------------------- name matching

def fold(name: str) -> str:
    """Compare filenames the way `fetch.py` does, for the same reason.

    The model echoes back a filename it read in our prompt. Our prompt carried
    whatever form the filesystem gave us — macOS stores `Área` decomposed — and
    the model may well answer with it composed. They are the same file and
    compare unequal, so every pick would be dropped as unrecognised.
    """
    import unicodedata
    return unicodedata.normalize("NFC", name).casefold().strip()


def match_file(claimed: str, candidates: "dict[str, object]") -> "str | None":
    """Resolve a filename the model returned to one we actually offered.

    Forgiving on purpose, because a rejected pick is a wasted call: exact match
    first, then basename, then a unique prefix. Anything still ambiguous is
    reported rather than guessed — silently picking the wrong photograph is worse
    than admitting the answer was unusable.
    """
    want = fold(claimed)
    if want in candidates:
        return want
    base = fold(Path(claimed).name)
    if base in candidates:
        return base
    stem = fold(Path(claimed).stem)
    hits = [k for k in candidates if fold(Path(k).stem) == stem]
    if len(hits) == 1:
        return hits[0]
    hits = [k for k in candidates if k.startswith(base[:max(8, len(base) - 4)])]
    return hits[0] if len(hits) == 1 else None


# ------------------------------------------------------------------- uploading

def ascii_name(name: str) -> str:
    """An ASCII-only upload name. `Suíte` -> `Suite`, `Área` -> `Area`.

    fal's storage rejects a `file_name` carrying non-ASCII characters, and does it
    with `Invalid storage type` — an error that says nothing about the cause.
    Measured on a real delivery: 7 of 19 rooms failed, and every failure had an
    accent in its filename while every success did not.

    Safe to mangle, because this name is never used to identify anything. The
    model is shown the *real* filename in the prompt text and answers with that;
    the CDN name only has to be unique enough to upload.
    """
    import unicodedata
    stripped = "".join(c for c in unicodedata.normalize("NFKD", name)
                       if not unicodedata.combining(c))
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", stripped)
    return cleaned or "image.jpg"


def upload_for_vision(proxy: Path, cache: dict) -> str:
    """Put a vision-sized copy of one proxy on fal's CDN, once.

    Cached by path because a tournament shows the same photograph in more than
    one round, and re-uploading it each time would triple the slow part of the
    run for no benefit.
    """
    key = str(proxy)
    if key in cache:
        return cache[key]

    import fal_client

    with Image.open(proxy) as im:
        small = im.convert("RGB")
        small.thumbnail((VISION_LONG_EDGE, VISION_LONG_EDGE), Image.LANCZOS)
        buf = BytesIO()
        small.save(buf, "JPEG", quality=VISION_JPEG_QUALITY)

    last = None
    for attempt in range(1, 4):
        try:
            url = fal_client.upload(buf.getvalue(), "image/jpeg",
                                    file_name=ascii_name(proxy.name))
            cache[key] = url
            return url
        except Exception as e:                   # noqa: BLE001 — retry any transport failure
            last = e
            if attempt < 3:
                time.sleep(2 * attempt)
    raise VisionError(f"could not upload {proxy.name}: {type(last).__name__}: {last}")


# --------------------------------------------------------------------- the ask

def describe_candidate(n: int, scene, rules) -> str:
    """One line of measured context per image — as a verdict, never a raw number.

    Handing the model raw measurements was a mistake, and a costly one. Told
    `sharpness 1/30` — meaning *rank* 1, the sharpest in the room — it wrote
    "nitidez muito baixa (1/10)" and rejected the sharpest frame. Told
    `lean 0.9°` it wrote "inclinação acentuada", when 0.9° is better than this
    photographer's median.

    A number means nothing without the scale it sits on, and the scale lives in
    `RULES.md` where the model cannot see it. So the thresholds are applied here
    and only the conclusion is sent. Nothing to misread.
    """
    f = scene.lead
    bits = []

    if f.roll_deg is None:
        bits.append("levelness not measurable")
    elif abs(f.roll_deg) >= rules.roll_flag:
        bits.append(f"FAULT: leaning {abs(f.roll_deg):.0f} degrees off level")
    elif abs(f.roll_deg) >= rules.roll_warn:
        bits.append("slightly off level")
    else:
        bits.append("level")

    if f.convergence_deg is None:
        bits.append("too few verticals in frame to check them")
    elif f.convergence_deg >= rules.convergence_flag:
        bits.append("FAULT: verticals splay badly (three-point perspective)")
    elif f.convergence_deg >= rules.convergence_warn:
        bits.append("verticals splay a little")
    else:
        bits.append("verticals straight")

    if f.highlight_clip >= 8:
        bits.append("large blown-out areas")
    elif f.highlight_clip >= 3:
        bits.append("some blown highlights")
    if f.shadow_clip >= 12:
        bits.append("crushed blacks")

    if f.focal_35mm and f.focal_35mm < rules.focal_flag:
        bits.append(f"FAULT: {f.focal_35mm:.0f}mm equivalent, stretches the edges")
    if scene.is_bracket:
        bits.append(f"exposure bracket of {len(scene.frames)}, will be merged")

    return f"Image {n} — {scene.lead.path.name}: {'; '.join(bits)}."


def build_prompt(room: str, slots: int, scenes: "list", rules) -> str:
    """The user turn: which room, how many slots, and what was measured."""
    lines = [
        f'Room: "{room}".',
        f"Slots available: {slots}. Return at most {slots} picks.",
        f"You are shown {len(scenes)} photographs of this room, in the order "
        "listed below.",
        "",
        "Levelness and lens geometry were measured from the pixels; the verdicts "
        "are below. Take them as given — they are more reliable than an "
        "impression. Anything marked FAULT breaks a rule you were told to reject "
        "on. Everything else about the photographs is yours to judge by looking, "
        "including whether one is too blurred to use.",
    ]
    lines += [describe_candidate(i + 1, s, rules) for i, s in enumerate(scenes)]
    lines += ["",
              "Choose the photographs that best show this room, following your "
              "instructions. Answer with the JSON object only."]
    return "\n".join(lines)


def extract_json(text: str) -> dict:
    """Pull the JSON object out of a free-text answer.

    The endpoint has no structured-output mode, so this has to cope with a model
    that wraps its JSON in a markdown fence or introduces it with a sentence.
    """
    if not text or not text.strip():
        raise VisionError("empty answer")
    body = text.strip()
    body = re.sub(r"^```(?:json)?\s*", "", body)
    body = re.sub(r"\s*```$", "", body)
    start, end = body.find("{"), body.rfind("}")
    if start < 0 or end <= start:
        raise VisionError(f"no JSON object in the answer: {text[:160]!r}")
    try:
        data = json.loads(body[start:end + 1])
    except json.JSONDecodeError as e:
        raise VisionError(f"answer is not valid JSON ({e}): {body[start:start + 160]!r}")
    if not isinstance(data, dict):
        raise VisionError(f"answer is not a JSON object: {body[start:start + 160]!r}")
    return data


def parse_answer(text: str) -> dict:
    """The ranking answer: a JSON object carrying a `picks` list."""
    data = extract_json(text)
    if "picks" not in data:
        raise VisionError(f"answer has no 'picks' key: {list(data)[:6]}")
    if not isinstance(data["picks"], list):
        raise VisionError("'picks' is not a list")
    return data


def parse_classification(text: str) -> dict:
    """The classification answer: a JSON object carrying an `ambiente` string."""
    data = extract_json(text)
    if not isinstance(data.get("ambiente"), str) or not data["ambiente"].strip():
        raise VisionError(f"answer has no 'ambiente' string: {list(data)[:6]}")
    return data


def ask(prompt: str, system_prompt: str, urls: "list[str]",
        model: str = VISION_MODEL, parse=parse_answer,
        temperature: float = TEMPERATURE) -> "tuple[dict, str]":
    """One call. Returns (parsed, raw). Retries once on an unparseable answer.

    `parse` is what decides whether the answer is usable, so the retry — which is
    the only reason this loop exists — covers the shape of the answer and not just
    its syntax. Both askers in this file share it.
    """
    import fal_client

    last = None
    for attempt in range(1, PARSE_ATTEMPTS + 1):
        ask_text = prompt if attempt == 1 else (
            prompt + "\n\nYour previous answer could not be parsed. Reply with "
            "ONLY the JSON object — no explanation, no markdown fence, nothing "
            "before the opening brace or after the closing brace.")
        try:
            result = fal_client.subscribe(VISION_ENDPOINT, arguments={
                "prompt": ask_text,
                "system_prompt": system_prompt,
                "image_urls": urls,
                "model": model,
                "temperature": temperature,
                "max_tokens": MAX_TOKENS,
                "priority": "throughput",
            }, with_logs=False)
        except Exception as e:                   # noqa: BLE001 — transport, quota, anything
            raise VisionError(f"{type(e).__name__}: {e}")
        raw = (result or {}).get("output") or ""
        try:
            return parse(raw), raw
        except VisionError as e:
            last = e
    raise VisionError(f"unparseable after {PARSE_ATTEMPTS} attempts: {last}")


# --------------------------------------------------------------- classification
# A separate, cheaper question from the ranking below: not "which of these is
# best" but "what room is this". Asked first, because the answer decides the
# filename every picked photograph is delivered under, and because the quota reads
# the room's category — a bathroom filed as a terrace gets a terrace's slots.
#
# The photographer's own filename is still the primary source and it is very good:
# one measured delivery labelled 277 of 307 files itself. This pass exists to
# catch the ones they got wrong, and to name the ones they never labelled at all —
# the `3_Condomínio/` folder of camera filenames that `cull.py` used to give up on.

@dataclass
class Classification:
    """What room a group of photographs is of, and where that answer came from."""
    label: str = ""                  # the photographer's words, verbatim
    mapped: "str | None" = None      # what the keyword pass made of them
    ambiente: str = ""               # the answer for the group as a whole
    corrigido: bool = False
    porque: str = ""
    # folded filename -> (slug, why). In per-image mode this is every photograph
    # that got an answer; otherwise only the ones that turned out to be of
    # somewhere else.
    named: "dict[str, tuple[str, str]]" = field(default_factory=dict)
    # folded filename -> what went wrong. Per-image mode only, and deliberately
    # separate from `named`: a photograph the model *looked at* and could not place
    # was checked and came back unknown, while one whose call failed was never
    # checked at all. Both end at NAO_IDENTIFICADO and the catalogue's `Origem`
    # column is where the difference shows — `vision` against `none`.
    failed: "dict[str, str]" = field(default_factory=dict)
    per_image: bool = False
    calls: int = 0
    seconds: float = 0.0
    model: str = ""
    note: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


def build_confirm_prompt(label: "str | None", mapped: str, scenes: "list",
                         vocab) -> str:
    """The user half of a *confirm* call: a labelled room, all of it at once."""
    lines = [f'The photographer\'s label for this room: "{label}".',
             f"That label was read as `{mapped}`. Confirm it, or correct it if the "
             "photographs show otherwise.",
             "",
             "The names you may return, and the only ones:",
             vocab.list_for_prompt(),
             "",
             f"You are shown {len(scenes)} photograph(s) of what is believed to be "
             "one room, in the order listed below."]
    lines += [f"Image {i + 1} — {s.lead.path.name}" for i, s in enumerate(scenes)]
    lines += ["", "Answer with the JSON object only."]
    return "\n".join(lines)


def build_name_prompt(scene, vocab) -> str:
    """The user half of a *name* call: one photograph, no label, no premise."""
    return "\n".join([
        "The names you may return, and the only ones:",
        vocab.list_for_prompt(),
        "",
        f"The one photograph you are shown is `{scene.lead.path.name}`. Nothing is "
        "known about it beyond the picture itself.",
        "",
        "List what you can see first, then name the room. Answer with the JSON "
        "object only.",
    ])


def _valid_slug(claimed: str, vocab) -> "str | None":
    """Resolve what the model wrote to a slug we actually offered, or None.

    Forgiving in the same spirit as `match_file`: a model that answers `Quarto` or
    `area_servico` meant the right room, and throwing the call away over its
    shift key would be waste. Anything that is not one of ours is still refused.
    """
    claimed = (claimed or "").strip().strip("`")
    if vocab.is_valid(claimed):
        return claimed
    squashed = re.sub(r"[^A-Za-z]+", "_", claimed).strip("_").upper()
    if vocab.is_valid(squashed):
        return squashed
    want = fold(claimed).replace(" ", "_")
    for slug in vocab.order:
        if fold(slug) == want:
            return slug
    return None


def classify(label: "str | None", mapped: "str | None", scenes: "list", vocab,
             cache: dict, model: str = CLASSIFY_MODEL,
             workers: int = 4) -> Classification:
    """Name one room, or name each photograph. Never raises — failures are recorded.

    **The two cases are different questions and are asked differently**, which is
    the whole shape of this function. With a label, the room is the unit: all of
    its photographs go in together, the model confirms or corrects one name, and
    seeing them side by side is what finds the stray file that is of somewhere
    else. With no label there is no room to confirm — a group only exists because
    something put those files together, and when that something is a folder named
    `3_Condomínio/` or a property reference, it is not evidence of anything.

    So an unlabelled group is asked **one photograph at a time**, and the grouping
    that follows splits the answers apart.
    """
    per_image = not mapped
    out = Classification(label=label or "", mapped=mapped, model=model,
                         per_image=per_image)
    t0 = time.time()
    if not scenes:
        out.error = "no scenes"
        return out
    (_name_each if per_image else _confirm_one)(out, label, mapped, scenes, vocab,
                                                cache, model, workers)
    out.seconds = time.time() - t0
    return out


def _name_each(out: Classification, label, mapped, scenes: "list", vocab,
               cache: dict, model: str, workers: int) -> None:
    """One photograph, one call, one answer. No photograph inherits another's.

    This used to send twelve photographs per call and ask for an array of twelve
    answers, then fall back to the batch's majority vote for any photograph the
    model left out. Both halves of that were wrong and they compounded:

    - An array of twelve verbose Portuguese entries runs into `MAX_TOKENS`, so the
      tail of it is silently truncated. Truncation was the expected case, not the
      rare one.
    - The fallback then filed those photographs under whatever the rest of the
      batch happened to be. Measured on `WC-00284`: three photographs of a bed
      were delivered as `COZINHA`, because they sat in a five-image tail batch that
      voted kitchen. Nothing in the output said a guess had been substituted.

    A photograph now gets its own answer or an honest `NAO_IDENTIFICADO`. That
    costs one call per photograph — cents on this model — and it is the correct
    price for the field that becomes a client's filename.
    """
    def name_one(scene) -> "tuple[str, str | None, str]":
        key = fold(scene.lead.path.name)
        try:
            url = upload_for_vision(scene.lead.proxy, cache)
            data, _ = ask(build_name_prompt(scene, vocab), vocab.name_prompt,
                          [url], model=model, parse=parse_classification,
                          temperature=CLASSIFY_TEMPERATURE)
        except VisionError as e:
            return key, None, str(e)
        slug = _valid_slug(data["ambiente"], vocab)
        if slug is None:
            return key, None, (f"model answered `{str(data['ambiente'])[:24]}`, "
                               "which is not in AMBIENTES.md")
        # `why` ties the evidence to the name and is what the contact sheet shows;
        # `vejo` is the bare list of fixtures, and stands in when the model skipped
        # the sentence. Between them the reviewer can see *why* a photograph was
        # filed where it was, which is how a wrong answer becomes visible.
        why = str(data.get("why", "") or "").strip()
        return key, slug, why or str(data.get("vejo", "") or "").strip()

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for key, slug, text in pool.map(name_one, scenes):
            out.calls += 1
            if slug is None:
                out.failed[key] = text
            else:
                out.named[key] = (slug, text)

    counts: "dict[str, int]" = {}
    for slug, _ in out.named.values():
        counts[slug] = counts.get(slug, 0) + 1
    # Reported, never applied. This is the group's rough shape for the terminal
    # line; no photograph is ever filed under it. That substitution is the bug this
    # function was rewritten to remove, so there is deliberately no code path here
    # that could reintroduce it.
    out.ambiente = max(counts, key=lambda s: (counts[s], s), default=UNKNOWN_SLUG)
    if not out.named:
        out.error = "no photograph could be named"
        return
    found = ", ".join(f"{s}×{n}" for s, n in
                      sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))
    out.note = f"named {len(out.named)} photo(s) one by one: {found}"
    if out.failed:
        out.note += (f"; {len(out.failed)} could not be named and are "
                     f"{UNKNOWN_SLUG} for you to settle")


def _confirm_one(out: Classification, label, mapped: str, scenes: "list", vocab,
                 cache: dict, model: str, workers: int) -> None:
    """A labelled room, judged as a room. All of it at once, in batches if large.

    Every one of the room's cluster leads is shown rather than a sample. Sampling
    would be cheaper and would answer the main question just as well, but it cannot
    find the stray file — the one photograph in the folder that is of somewhere
    else — and that is half of what this pass is for.
    """
    batches = [scenes[i:i + BATCH_MAX_IMAGES]
               for i in range(0, len(scenes), BATCH_MAX_IMAGES)]
    votes: "list[str]" = []
    reasons: "dict[str, str]" = {}
    for batch in batches:
        candidates = {fold(s.lead.path.name): s for s in batch}
        try:
            urls = [upload_for_vision(s.lead.proxy, cache) for s in batch]
            data, _ = ask(build_confirm_prompt(label, mapped, batch, vocab),
                          vocab.confirm_prompt, urls, model=model,
                          parse=parse_classification,
                          temperature=CLASSIFY_TEMPERATURE)
        except VisionError as e:
            out.error = str(e)
            break
        out.calls += 1

        slug = _valid_slug(data["ambiente"], vocab)
        if slug is None:
            out.note = (f"model answered `{str(data['ambiente'])[:24]}`, which is not "
                        "in AMBIENTES.md — ignored")
            continue
        votes.append(slug)
        # Kept per slug, not per call, so the sentence that survives is the one
        # that argued for the answer that won rather than whichever batch was last.
        reasons.setdefault(slug, str(data.get("porque", "") or "").strip())

        listed = data.get("estranhos")
        listed = listed if isinstance(listed, list) else []
        keep: "dict[str, tuple[str, str]]" = {}
        for item in listed:
            if not isinstance(item, dict):
                continue
            key = match_file(str(item.get("file", "")), candidates)
            item_slug = _valid_slug(str(item.get("ambiente", "")), vocab)
            if not key or not item_slug:
                continue
            # Only the ones that disagree with the room are news — a model that
            # helpfully lists all twelve images as the room they are in has said
            # nothing.
            if item_slug != slug:
                keep[key] = (item_slug, str(item.get("why", "")).strip())

        # A stray is one image out of step with its neighbours. When most of a
        # batch disagrees, the model has not found strays — it has disagreed with
        # the premise, and its own `ambiente` already said so. Acting on it would
        # shatter one room into several of one photograph. Counted after filtering,
        # because before it the number is inflated by entries that turn out to
        # agree with the room after all.
        if len(keep) > len(batch) / 2:
            out.note = (f"{len(keep)} of {len(batch)} images disagreed with the "
                        "label — too many to be strays, so they were left alone")
            continue
        out.named.update(keep)

    if not votes:
        out.ambiente = mapped or ""
        if not out.error:
            out.error = out.note or "no usable answer"
        return

    # The room's identity is the majority answer; the first batch breaks a tie,
    # because it is the one with no history behind it.
    ranked = sorted(set(votes), key=lambda s: (-votes.count(s), votes.index(s)))
    out.ambiente = ranked[0]
    out.corrigido = out.ambiente != mapped
    out.porque = reasons.get(out.ambiente, "") if out.corrigido else ""
    if len(ranked) > 1:
        # The premise was that this is one room, so a disagreement between batches
        # is evidence the premise is wrong.
        out.note = ("batches disagreed (" +
                    ", ".join(f"{s}×{votes.count(s)}" for s in ranked) +
                    ") — the folder may hold more than one room")


# ------------------------------------------------------- one room or two rooms
# A third question, and the only one that can answer it is the one looking at the
# pixels. Everything upstream derives a *physical* room from filename and folder
# tokens, so a photographer who hands over a flat folder of camera filenames
# delivers two bedrooms as one room — there is no token to tell them apart, and a
# perceptual hash cannot help either: two views of one room hash further apart than
# two similarly furnished rooms do.

@dataclass
class Split:
    """How the photographs of one ambiente divide into physical rooms."""
    ambiente: str = ""
    rooms: "list[list]" = field(default_factory=list)   # scenes, in room order
    porque: str = ""
    calls: int = 0
    seconds: float = 0.0
    model: str = ""
    note: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


def build_split_prompt(ambiente: str, scenes: "list") -> str:
    lines = [f"Every photograph below has been identified as `{ambiente}`.",
             f"You are shown {len(scenes)} of them, in the order listed here.",
             "",
             "Say which are the same physical room. Answer with the JSON object "
             "only."]
    lines[3:3] = [f"Image {i + 1} — {s.lead.path.name}"
                  for i, s in enumerate(scenes)]
    return "\n".join(lines)


def parse_split(text: str) -> dict:
    """The split answer: a JSON object carrying a `comodos` list of lists."""
    data = extract_json(text)
    rooms = data.get("comodos")
    if not isinstance(rooms, list) or not rooms:
        raise VisionError(f"answer has no 'comodos' list: {list(data)[:6]}")
    if not all(isinstance(r, list) for r in rooms):
        raise VisionError("'comodos' is not a list of lists")
    return data


def split_rooms(ambiente: str, scenes: "list", cache: dict, split_prompt: str,
                model: str = CLASSIFY_MODEL) -> Split:
    """Divide one ambiente's photographs into physical rooms. Never raises.

    One call, every photograph in it, because this comparison cannot be run in
    heats — see `SPLIT_MAX_IMAGES`.

    **Every failure mode here resolves to "one room".** A missing file, a repeated
    file, an unparseable answer, too many photographs to show at once: all of them
    leave the ambiente merged, which is the state a person fixes with one click on
    the contact sheet. The opposite error invents a `QUARTO_02` that does not
    exist and writes it into a filename that reaches a client, and no click undoes
    that once the job has moved on.
    """
    out = Split(ambiente=ambiente, model=model, rooms=[list(scenes)])
    t0 = time.time()
    if len(scenes) < 2:
        return out
    if len(scenes) > SPLIT_MAX_IMAGES:
        out.note = (f"{len(scenes)} photos is more than the {SPLIT_MAX_IMAGES} that "
                    "can be compared in one look — left as one room")
        return out

    by_name = {fold(s.lead.path.name): s for s in scenes}
    try:
        urls = [upload_for_vision(s.lead.proxy, cache) for s in scenes]
        data, _ = ask(build_split_prompt(ambiente, scenes), split_prompt, urls,
                      model=model, parse=parse_split,
                      temperature=CLASSIFY_TEMPERATURE)
    except VisionError as e:
        out.error = str(e)
        out.seconds = time.time() - t0
        return out
    out.calls = 1

    rooms: "list[list]" = []
    claimed: set = set()
    for group in data["comodos"]:
        room = []
        for claim in group:
            key = match_file(str(claim), by_name)
            if key is None or key in claimed:
                continue                 # invented or repeated — see the docstring
            claimed.add(key)
            room.append(by_name[key])
        if room:
            rooms.append(room)

    missing = [s for s in scenes if fold(s.lead.path.name) not in claimed]
    if not rooms or missing:
        # A partial answer is not a split. Filing the photographs it did name into
        # rooms and the ones it forgot into a leftover room would manufacture a
        # room out of the model's inattention, which is exactly the error this
        # function refuses to make.
        out.error = (f"{len(missing)} of {len(scenes)} photo(s) missing from the "
                     "answer" if missing else "no usable groups in the answer")
        out.rooms = [list(scenes)]
        out.seconds = time.time() - t0
        return out

    # Largest first: the room the property leads with is the one it has most
    # photographs of, and it should be the `_01`.
    rooms.sort(key=lambda r: (-len(r), min(s.lead.path.name for s in r)))
    out.rooms = rooms
    out.porque = str(data.get("porque", "") or "").strip() if len(rooms) > 1 else ""
    if len(rooms) > 1:
        out.note = (f"{len(rooms)} rooms: "
                    + " · ".join(f"{len(r)} photo(s)" for r in out.rooms))
    out.seconds = time.time() - t0
    return out


# ------------------------------------------------------------------ tournament

def seed_batches(scenes: "list", size: int) -> "list[list]":
    """Split into batches by dealing, not by slicing.

    Slicing in file order puts the whole strong stretch of a room in one batch
    and the weak stretch in another, so a good photograph loses its slot to a
    weaker one purely for having strong neighbours. Dealing the ranked list round
    robin gives every batch a comparable spread.
    """
    ranked = sorted(scenes, key=lambda s: (len(s.flags), -s.lead.sharpness))
    n_batches = (len(ranked) + size - 1) // size
    batches = [[] for _ in range(n_batches)]
    for i, s in enumerate(ranked):
        batches[i % n_batches].append(s)
    return batches


def choose(room: str, scenes: "list", slots: int, rules,
           url_cache: dict, model: str = VISION_MODEL) -> Verdict:
    """Pick the best `slots` photographs of one room. Never raises."""
    v = Verdict(room=room, model=model)
    t0 = time.time()
    if not scenes or slots <= 0:
        v.error = "nothing to choose from"
        return v

    try:
        finalists = list(scenes)
        round_no = 0
        while len(finalists) > BATCH_MAX_IMAGES:
            round_no += 1
            survivors = []
            for batch in seed_batches(finalists, BATCH_MAX_IMAGES):
                # Each heat returns its own quota's worth, so a strong room keeps
                # enough contenders for the final to be a real comparison.
                picked, calls = _one_call(room, batch, min(slots, len(batch)),
                                          rules, url_cache, model, v)
                v.calls += calls
                survivors.extend(picked)
            if not survivors or len(survivors) >= len(finalists):
                break                            # no progress; judge what we have
            finalists = survivors

        picked, calls = _one_call(room, finalists[:BATCH_MAX_IMAGES], slots,
                                  rules, url_cache, model, v)
        v.calls += calls
        v.picks = [p for p in v.picks if p["scene"] in picked][:slots]
        # Rank in the order the final call returned them.
        for rank, scene in enumerate(picked[:slots], 1):
            for p in v.picks:
                if p["scene"] is scene:
                    p["rank"] = rank
        v.picks.sort(key=lambda p: p["rank"])

        # A tournament can contradict itself: a frame dismissed in its heat can
        # win the final, and then it sits in both lists. The final call is the
        # one that saw the real competition, so it wins.
        chosen_scenes = {id(p["scene"]) for p in v.picks}
        v.rejected = [r for r in v.rejected if id(r["scene"]) not in chosen_scenes]

        # And a frame can be dismissed in more than one round. Keep the first
        # comment for each, so each list is one line per photograph.
        def once(entries: "list[dict]") -> "list[dict]":
            seen: set = set()
            out = []
            for e in entries:
                if id(e["scene"]) not in seen:
                    seen.add(id(e["scene"]))
                    out.append(e)
            return out

        v.rejected = once(v.rejected)
        # Not filtered against the picks the way `rejected` is: a photograph the
        # model both picked and called foreign to the room is the most useful thing
        # this list can report, and dropping it would hide the contradiction that
        # makes a misclassification visible.
        v.not_room = once(v.not_room)
    except VisionError as e:
        v.error = str(e)
    v.seconds = time.time() - t0
    return v


def _one_call(room: str, scenes: "list", slots: int, rules,
              url_cache: dict, model: str, v: Verdict) -> "tuple[list, int]":
    """Run one comparison and return (chosen scenes, calls made)."""
    by_name = {fold(s.lead.path.name): s for s in scenes}
    urls = [upload_for_vision(s.lead.proxy, url_cache) for s in scenes]
    data, _raw = ask(build_prompt(room, slots, scenes, rules),
                     rules.vision_prompt, urls, model)

    chosen = []
    for entry in data.get("picks", []):
        if not isinstance(entry, dict):
            continue
        key = match_file(str(entry.get("file", "")), by_name)
        if key is None:
            v.unmatched.append(str(entry.get("file", ""))[:60])
            continue
        scene = by_name[key]
        if scene in chosen:
            continue
        chosen.append(scene)
        v.picks.append({
            "scene": scene, "rank": len(chosen),
            "reason": str(entry.get("reason", "")).strip(),
            "purpose": _score(entry.get("purpose")),
            "staging": _score(entry.get("staging")),
        })

    for entry in data.get("rejected", []) or []:
        if not isinstance(entry, dict):
            continue
        key = match_file(str(entry.get("file", "")), by_name)
        if key is not None:
            v.rejected.append({"scene": by_name[key],
                               "why": str(entry.get("why", "")).strip()})

    # The ranking pass is handed the room name as a premise — `Room: "COZINHA_01"`
    # — and until this list existed it had no way to say the premise was wrong. It
    # simply wrote a kitchen-flavoured reason for whatever it was shown, so a
    # misclassified photograph arrived on the contact sheet with a confident
    # caption agreeing with the mistake. Measured on `WC-00284`: a terrace filed
    # under COZINHA was praised for "destacando a geladeira".
    for entry in data.get("nao_pertence", []) or []:
        if not isinstance(entry, dict):
            continue
        key = match_file(str(entry.get("file", "")), by_name)
        if key is not None:
            v.not_room.append({"scene": by_name[key],
                               "why": str(entry.get("why", "")).strip()})
    return chosen[:slots], 1


def _score(x) -> "int | None":
    try:
        return max(0, min(10, int(float(x))))
    except (TypeError, ValueError):
        return None


# ----------------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("shoot", help="the shoot folder, e.g. '0 - selection/Cobertura'")
    ap.add_argument("--room", required=True,
                    help="which room to judge, as named on the contact sheet")
    ap.add_argument("--slots", type=int,
                    help="how many to pick (default: the quota from RULES.md)")
    ap.add_argument("--model", default=VISION_MODEL)
    args = ap.parse_args()

    sys.path.insert(0, str(SELECTION_DIR))
    import cull                                  # noqa: E402 — needs sys.path first

    rules = cull.load_rules()
    job = cull.find_shoot(args.shoot)
    source, proxies = job / "source", job / "_proxies"

    photos = sorted(p for p in source.rglob("*")
                    if p.is_file() and p.suffix.lower() in cull.PHOTO_EXTS)
    facts = []
    for p in photos:
        try:
            facts.append(cull.ingest.read(p, proxies))
        except Exception:                        # noqa: BLE001
            pass
    scenes = cull.group_brackets(facts)
    for s in scenes:
        s.room, s.room_order, s.shot, s.area, s.area_order = \
            cull.parse_labels(s.lead.path, source)
    cull.cluster_scenes(scenes)
    for s in scenes:
        cull.assess(s, rules)

    groups = cull.group_rooms(scenes, rules)
    cull.allocate(groups, rules)
    match = [g for g in groups if cull.fold(g.room) == cull.fold(args.room)]
    if not match:
        sys.exit(f"error: no room called {args.room!r}. Rooms here: "
                 + ", ".join(g.room for g in groups))
    g = match[0]

    leads = [c[0] for c in g.clusters]           # one contender per angle
    slots = args.slots or g.slots
    print(f"room        {g.room}  ({g.category}, priority {g.priority})")
    print(f"candidates  {len(leads)} distinct angle(s) out of {g.scenes} photo(s)")
    print(f"slots       {slots}")
    print(f"model       {args.model}")

    from dotenv import load_dotenv
    load_dotenv(ROOT / "_config" / ".env")
    import os
    if not os.environ.get("FAL_KEY"):
        sys.exit("error: FAL_KEY is not set. Put it in _config/.env.")

    v = choose(g.room, leads, slots, rules, {}, args.model)

    if not v.ok:
        sys.exit(f"\nfailed      {v.error}")
    print(f"\ncalls       {v.calls}   {v.seconds:.0f}s")
    if v.unmatched:
        print(f"unmatched   {len(v.unmatched)} filename(s) the model invented: "
              f"{', '.join(v.unmatched[:3])}")
    print(f"\npicked {len(v.picks)} of {slots}:")
    for p in v.picks:
        scores = " ".join(f"{k} {p[k]}" for k in ("purpose", "staging")
                          if p[k] is not None)
        print(f"  {p['rank']}. {p['scene'].lead.path.name}   {scores}")
        print(f"     {p['reason']}")
    if v.rejected:
        print(f"\nrejected outright:")
        for r in v.rejected:
            print(f"  {r['scene'].lead.path.name} — {r['why']}")
    if v.not_room:
        print(f"\nsays these are not {g.room} at all:")
        for r in v.not_room:
            print(f"  {r['scene'].lead.path.name} — {r['why']}")


if __name__ == "__main__":
    main()
