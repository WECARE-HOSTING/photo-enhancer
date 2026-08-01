#!/usr/bin/env python3
"""Phase 1 — every photo through fal.ai with the one fixed prompt in PROMPT.md.

    ./_config/.venv/bin/python "1 - edit/1 - edicao/enhance.py" "1 - edit/Job_0023/SALA_01_0001.jpg"

Same prompt, every photo. No per-photo analysis or per-photo prompt file:
the model reads the attached source image itself; PROMPT.md just tells it
what to preserve, fix, remove, and tidy.

**Per-photo instructions are phase 3, not here.** When you send a photo back at
the gate with a comment, `2 - retoque/retoque.py` handles it — and it does not
read this file at all, because the comment exists precisely to override rules
this prompt lays down. A comment that keeps coming back is a `PROMPT.md` edit
waiting to happen: the retouch fixes one photo, this file fixes every future one.

The source's name is kept and `_edit` is appended — `SALA_01_0001.jpg` becomes
`SALA_01_0001_edit.jpg`, alongside `SALA_01_0001_log.md`. Both are written **next
to the source photo**, inside its job folder, so a job stays one self-contained
bundle. Nothing here renames, moves or archives anything; that is `batch.py`'s
job.

A re-run overwrites the previous `_edit` and rewrites the log from scratch: a
fresh phase-1 run is a fresh start. Phase 3 appends to that log instead, so the
first run's header — and the source URL in it — survives every retouch.

PROMPT.md is re-read from disk on every single photo, so editing it mid-batch
takes effect on the very next photo. Each log records the prompt's fingerprint
(a short hash), which is how you tell which wording produced the image you are
looking at.

The journey itself — prepare, upload, submit, download — lives in `_config/fal.py`
and is shared with phase 3. To change model, quality or size, edit the constants
there; to change what the model is asked for, edit PROMPT.md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "_config"))
import fal  # noqa: E402
import paths  # noqa: E402

from PIL import Image  # noqa: E402

PROMPT_PATH = HERE / "PROMPT.md"

# Everything in PROMPT.md from this marker onward is reference documentation
# (the fal.ai request settings table) — not sent to the model as prompt text.
PROMPT_END_MARKER = "===== END OF PROMPT"

# Re-exported so `batch.py` can keep saying `enhance.DEFAULT_MODEL` and
# `enhance.EnhanceError` without knowing where the plumbing moved to.
DEFAULT_MODEL = fal.DEFAULT_MODEL
EnhanceError = fal.EnhanceError
fail = fal.fail

# The line every log carries, and the one thing another script parses out of a
# log: `2 - retoque/retoque.py` reads it to reuse the original's CDN URL instead
# of uploading the photo a second time. Change this wording and the retouch
# silently starts re-uploading — see `_dependencies.md`.
SOURCE_URL_LABEL = "Uploaded source"


def load_prompt() -> "tuple[str, str]":
    """Read PROMPT.md fresh and return (prompt_text, 8-char fingerprint).

    Re-read per photo on purpose: PROMPT.md is the one tuning surface for this
    phase and is expected to keep changing, so an edit lands on the next
    photo without restarting anything. The fingerprint goes into every log,
    which is what makes 'did that prompt change help?' answerable later.
    """
    if not PROMPT_PATH.exists():
        fail(f"no prompt file at {PROMPT_PATH}")
    raw = PROMPT_PATH.read_text(encoding="utf-8")
    if PROMPT_END_MARKER not in raw:
        fail(f"PROMPT.md is missing its '{PROMPT_END_MARKER}' marker line. "
             "Without it the fal.ai settings table would be sent to the model "
             "as prompt text. Put the marker back before running.")
    prompt = raw.split(PROMPT_END_MARKER, 1)[0].strip()
    if len(prompt) < 100:
        fail(f"PROMPT.md has only {len(prompt)} chars of prompt above the "
             "marker — that looks like a bad edit, not a prompt.")
    return prompt, hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:8]


# Grammar and scene-setting words that appear on both sides of almost every
# instruction. Excluding them is what makes --check's output short enough to
# actually read. Object nouns are deliberately NOT in here.
CHECK_IGNORE = frozenset("""
a an and any anything are as at be been before behind below both but by can
cannot clean clear come comes do does doing done down each else every
everything exactly far few first for from go goes going had has have having
here how however if in inside into is it its itself just keep keeps kept leave
leaves leaving left like look looks made make makes many may more most much
must never new no nor not nothing now of off on once one only or other out over
own part place placed places read reads real really removal remove removed
removes removing same see set sets should show shows side simply since so some
something stay stays still such take taken takes than that the their them then
there these they thing things this those through to too two under until up upon
very want was way we well were what when where which while who whole why will
with without would you your
room rooms photo photograph photographs frame framed frames image images model
source scene space property listing surface surfaces
belong belongs blocking cluttered condition correct convincingly completely
erase erased instead layout otherwise proportion rather rendered reads
visible whole follow following gone placed
""".split())


def check_prompt() -> int:
    """Audit PROMPT.md without submitting anything. Returns a shell exit code.

    Exists because the same failure has now bitten five times: a new rule
    silently overrides a working one, and it is invisible in the text — you only
    find it in the generated image, after paying for it. This flags any object
    named in both a removal instruction and a keep instruction, and prints both
    sentences so the conflict can be judged at a glance.

    It is a smoke alarm, not a proof: most pairs it surfaces are deliberate
    distinctions (bathroom towels stay, floor towels go). The job is to make a
    real conflict impossible to miss, not to decide correctness.
    """
    try:
        prompt, prompt_id = load_prompt()
    except EnhanceError as e:
        print(f"FAIL  {e}")
        return 1

    raw = PROMPT_PATH.read_text(encoding="utf-8")
    print(f"prompt      #{prompt_id} · {len(prompt)} chars")
    print(f"api limit   32000 chars — {'ok' if len(prompt) <= 32000 else 'OVER LIMIT'}"
          f" ({len(prompt) / 32000:.0%} used)")
    print(f"marker      present, {len(raw) - len(prompt)} chars of notes excluded")

    sections = re.findall(r"^#{3} (.+)$", prompt, re.M)
    print(f"sections    {len(sections)}: {', '.join(sections)}")

    sentences = [s.strip() for s in re.split(r"(?<=[.!])\s+", prompt) if s.strip()]
    says_remove = re.compile(r"\b(take[sn]? off|remove[sd]?|erase[sd]?|goes|go)\b", re.I)
    # \bleave\b, not "leave" — otherwise the noun "leaves" (foliage) reads as the verb.
    says_keep = re.compile(r"\b(stays?|keeps?|leave|left in place|remain[s]?)\b", re.I)

    # A sentence stating both halves of one rule ("keep it unless X, then erase it")
    # is self-consistent by construction. Counting it on both sides pairs it with
    # itself and buries the real conflicts, so those sentences are set aside.
    removes = [s for s in sentences if says_remove.search(s) and not says_keep.search(s)]
    keeps = [s for s in sentences if says_keep.search(s) and not says_remove.search(s)]
    both = sum(1 for s in sentences if says_remove.search(s) and says_keep.search(s))
    print(f"sentences   {len(sentences)} · {len(removes)} remove-only · "
          f"{len(keeps)} keep-only · {both} self-contained (skipped)")

    def stem(w: str) -> str:
        """Crude singularizer. Without it "remove kettles" and "the kettle stays"
        never match, which is exactly the conflict this check exists to find."""
        if w.endswith("ies") and len(w) > 4:
            return w[:-3] + "y"
        if re.search(r"(s|x|z|ch|sh)es$", w):
            return w[:-2]
        if w.endswith("s") and not w.endswith("ss"):
            return w[:-1]
        return w

    def words(s: str) -> set:
        found = set()
        for w in re.findall(r"[a-z]{4,}", s.lower()):
            if w in CHECK_IGNORE:
                continue
            root = stem(w)
            if root not in CHECK_IGNORE and len(root) >= 3:
                found.add(root)
        return found

    remove_words, keep_words = {}, {}
    for s in removes:
        for w in words(s):
            remove_words.setdefault(w, s)
    for s in keeps:
        for w in words(s):
            keep_words.setdefault(w, s)

    shared = sorted(set(remove_words) & set(keep_words))
    print(f"\n{len(shared)} object(s) named in BOTH a remove and a keep instruction.")
    print("Most are deliberate. Read each pair and confirm you meant it:\n")
    for w in shared:
        print(f"  [{w}]")
        print(f"    REMOVE: {remove_words[w][:150]}")
        print(f"    KEEP:   {keep_words[w][:150]}")
    return 0


def run(photo: Path, model: str = DEFAULT_MODEL,
        emit=print, out_dir: "Path | None" = None) -> Path:
    """Run one photo through phase 1. Returns the saved image path.
    Raises EnhanceError on failure.

    Results land in `out_dir`, which defaults to the photo's own folder — for
    a job that means `Job_NNNN/` gets the source, the enhanced image, and the
    log side by side.

    Used by the CLI below and by `1 - edit/batch.py`. `emit` collects this
    photo's progress lines — batch.py hands it a per-photo buffer so parallel
    runs don't interleave their output.

    There is no per-photo instruction here by design. A photo the human sent
    back with a comment goes to `2 - retoque/retoque.py` instead, which edits
    the result rather than the source and does not read PROMPT.md.
    """
    t_start = time.time()
    if not photo.is_absolute():
        photo = (paths.ROOT / photo).resolve()
    if not photo.exists():
        fail(f"no such photo: {photo}")

    out_dir = out_dir or photo.parent
    stem = photo.stem
    prompt, prompt_id = load_prompt()

    t = time.time()
    upload_bytes, mime_type, src_w, src_h, sent_size = fal.prepare_upload(photo)
    t_prepare = time.time() - t

    emit(f"photo       {photo.name}  {src_w}x{src_h}  "
         f"({photo.stat().st_size / 1e6:.1f} MB)")
    emit(f"prompt      {PROMPT_PATH.name}  {len(prompt)} chars  #{prompt_id}")
    emit(f"model       {model}")
    if sent_size:
        emit(f"uploading   {sent_size[0]}x{sent_size[1]}  "
             f"{len(upload_bytes) / 1e6:.2f} MB  (downscaled in {t_prepare:.1f}s)")
    else:
        emit(f"uploading   {src_w}x{src_h}  {len(upload_bytes) / 1e6:.2f} MB  (as-is)")

    payload, setting_line = fal.payload_for(model, prompt, src_w, src_h)
    emit(setting_line)

    fal.require_key()
    import fal_client

    t = time.time()
    image_url = fal.upload(
        upload_bytes, mime_type,
        file_name=f"photo{'.jpg' if sent_size else photo.suffix or ''}",
    )
    t_upload = time.time() - t
    payload["image_urls"] = [image_url]
    emit(f"uploaded    {t_upload:.1f}s")

    t = time.time()
    try:
        result = fal_client.subscribe(model, arguments=payload, with_logs=False)
    except Exception as e:                  # noqa: BLE001 — the request left; it may have billed
        fail(f"{type(e).__name__}: {e}", phase="after")
    t_generate = time.time() - t
    emit(f"generated   {t_generate:.1f}s")

    images = result.get("images") or []
    if not images:
        fail(f"no image in response: {json.dumps(result)[:500]}", phase="after")

    out_dir.mkdir(parents=True, exist_ok=True)

    # The result is the source's name with `_edit` on the end, and that is the
    # whole rule. A re-run overwrites it: one photo has one current edit, and the
    # folder never fills with variants nobody can tell apart. The prompt that
    # produced the file is recorded in the log below, so which wording made it is
    # still answerable — what is not kept is the file it replaced.
    t = time.time()
    saved = []
    for i, img in enumerate(images):
        suffix = "" if len(images) == 1 else f"_{i + 1}"
        dest = out_dir / f"{stem}_edit{suffix}.jpg"
        fal.download(img["url"], dest)
        with Image.open(dest) as out:
            out_w, out_h = out.size
        saved.append((dest, out_w, out_h, img["url"]))
        emit(f"saved       {paths.rel(dest)}  {out_w}x{out_h}")
    t_download = time.time() - t
    t_total = time.time() - t_start

    log = out_dir / f"{stem}_log.md"
    lines = [
        f"# {stem} — Generation Log", "",
        "_Phase 1 below, then one block per retouch. Written by "
        "`1 - edicao/enhance.py`, appended to by `2 - retoque/retoque.py`._", "",
        "| | |", "|---|---|",
        f"| Run | {datetime.now(timezone.utc).isoformat(timespec='seconds')} |",
        f"| Source | `{photo.name}` · {src_w}×{src_h} |",
        f"| Model | `{model}` |",
        f"| Prompt | `PROMPT.md` · {len(prompt)} chars · fingerprint `#{prompt_id}` |",
    ]
    lines += fal.settings_row(model, payload, src_w, src_h)
    sent_desc = (f"{sent_size[0]}×{sent_size[1]} · {len(upload_bytes) / 1e6:.2f} MB (downscaled)"
                 if sent_size else f"{src_w}×{src_h} · {len(upload_bytes) / 1e6:.2f} MB (as-is)")
    lines += [
        f"| Sent to model | {sent_desc} |",
        f"| Timing | {t_total:.0f}s total — prepare {t_prepare:.1f}s · upload "
        f"{t_upload:.1f}s · generate {t_generate:.0f}s · download {t_download:.1f}s |",
        # Parsed back by `2 - retoque/retoque.py` — see SOURCE_URL_LABEL.
        f"| {SOURCE_URL_LABEL} | {image_url} |",
        "",
        "## Output", "",
    ]
    for dest, w, h, url in saved:
        lines.append(f"- `{paths.rel(dest)}` — {w}×{h} — [fal url]({url})")
    if result.get("description"):
        lines += ["", "## Model description of its own edit", "",
                  f"> {result['description']}"]
    lines += ["", f"## Prompt as sent (`#{prompt_id}`)", "", "```", prompt, "```", ""]
    log.write_text("\n".join(lines), encoding="utf-8")
    emit(f"logged      {paths.rel(log)}")
    emit(f"done        {t_total:.0f}s total")
    return saved[0][0]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("photo", nargs="?",
                    help="source photo, e.g. "
                         "'1 - edit/Job_0023/SALA_01_0001.jpg'")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--check", action="store_true",
                    help="audit PROMPT.md for self-contradictions; no photo, no cost")
    args = ap.parse_args()

    if args.check:
        sys.exit(check_prompt())
    if not args.photo:
        ap.error("a photo is required (or pass --check to audit PROMPT.md)")

    try:
        run(Path(args.photo), model=args.model)
    except EnhanceError as e:
        sys.exit(f"error: {e}")
    except KeyboardInterrupt:
        sys.exit("\ninterrupted — nothing saved for this photo")
    except Exception as e:                      # noqa: BLE001 — a clean message beats a traceback
        sys.exit(f"error: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
