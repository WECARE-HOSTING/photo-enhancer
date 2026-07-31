#!/usr/bin/env python3
"""Run a real estate photo through the fal.ai API with the fixed PROMPT.md.

    ./_config/.venv/bin/python "1 - edit/enhance.py" "1 - edit/Job_0023/SALA_01_0001.jpg"

Same prompt, every photo. No per-photo analysis or per-photo prompt file:
the model reads the attached source image itself; PROMPT.md just tells it
what to preserve, fix, remove, and tidy.

The one exception is `extra=`: when you send a photo back at the gate with a
comment, that sentence is appended to the prompt for **that photo's re-run
only**. The log records the base fingerprint and the addendum separately, so
"which wording produced this image" stays answerable. A comment that keeps
coming back is a `PROMPT.md` edit waiting to happen — the addendum fixes one
photo, the file fixes every future one.

The source's name is kept and `_edit` is appended — `SALA_01_0001.jpg` becomes
`SALA_01_0001_edit.jpg`, alongside `SALA_01_0001_log.md`. Both are written **next
to the source photo**, inside its job folder, so a job stays one self-contained
bundle. Nothing here renames, moves or archives anything; that is `batch.py`'s
job.

A re-run overwrites the previous `_edit`. One photo has one current edit.

PROMPT.md is re-read from disk on every single photo, so editing it mid-batch
takes effect on the very next photo. Each log records the prompt's fingerprint
(a short hash), which is how you tell which wording produced the image you are
looking at.

To change model or behavior, edit the constants below, or PROMPT.md itself.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import re
import sys
import time
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent.parent
PROMPT_PATH = Path(__file__).resolve().parent / "PROMPT.md"

# Everything in PROMPT.md from this marker onward is reference documentation
# (the fal.ai request settings table) — not sent to the model as prompt text.
PROMPT_END_MARKER = "===== END OF PROMPT"

DEFAULT_MODEL = "openai/gpt-image-2/edit"
NUM_IMAGES = 1   # set to 2-3 while tuning PROMPT.md to see the spread; 1 for batches
QUALITY = "medium"            # gpt-image-2 family: auto / low / medium / high
TARGET_LONG_EDGE = 2048       # gpt-image-2 family: always target ~2K output
RESOLUTION = "2K"             # nano-banana family: 1K / 2K / 4K
SEED = None                   # nano-banana family only; set an int to reuse

# Source photos are downscaled to this long edge before upload. The models
# render at TARGET_LONG_EDGE and read the input through a vision encoder that
# downscales anyway, so nothing is lost — but a 18 MB camera original takes
# ~67s to upload where its 2048px version takes ~4s. This is the single
# biggest speed win in the pipeline. Set to None to upload originals as-is.
UPLOAD_LONG_EDGE = 2048
UPLOAD_JPEG_QUALITY = 92

# Per-attempt timeout when fetching the finished image. Generous, because the
# first fetch warms fal's CDN edge and can legitimately take ~50s — but bounded,
# so a hung fetch fails and retries instead of stalling the batch forever.
DOWNLOAD_TIMEOUT = 120

# fal aspect_ratio enum -> decimal. Used by the nano-banana-style family.
RATIOS = {
    "21:9": 21 / 9, "16:9": 16 / 9, "3:2": 1.5, "4:3": 4 / 3, "5:4": 1.25,
    "1:1": 1.0, "4:5": 0.8, "3:4": 0.75, "2:3": 2 / 3, "9:16": 9 / 16,
}

class EnhanceError(Exception):
    """One photo failed. Raised rather than exiting, so a batch can carry on.

    `phase` says whether the request had already reached fal when it died —
    `before` means nothing was billed, `after` means it may have been. At 2am,
    after two failures in a batch of sixty, "did I pay for 60 or for 62" is a
    real question and nobody is going to open sixty log files to answer it.
    """

    def __init__(self, msg: str, phase: str = "before"):
        super().__init__(msg)
        self.phase = phase


def fail(msg: str, phase: str = "before") -> "None":
    raise EnhanceError(msg, phase)


def is_gpt_image(model: str) -> bool:
    return "gpt-image" in model


def nearest_ratio(width: int, height: int) -> str:
    target = width / height
    return min(RATIOS, key=lambda r: abs(RATIOS[r] - target))


def round16(x: float) -> int:
    return max(16, round(x / 16) * 16)


def custom_image_size(src_w: int, src_h: int, long_edge: int = TARGET_LONG_EDGE) -> dict:
    """Custom {width, height} matching the source's exact aspect ratio at ~2K."""
    ratio = src_w / src_h
    if ratio >= 1:
        w, h = long_edge, long_edge / ratio
    else:
        w, h = long_edge * ratio, long_edge
    return {"width": round16(w), "height": round16(h)}


def load_prompt() -> "tuple[str, str]":
    """Read PROMPT.md fresh and return (prompt_text, 8-char fingerprint).

    Re-read per photo on purpose: PROMPT.md is the one tuning surface in this
    project and is expected to keep changing, so an edit lands on the next
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


def prepare_upload(photo: Path) -> "tuple[bytes, str, int, int, tuple[int, int] | None]":
    """Read the photo, honor its EXIF orientation, and downscale it for upload.

    Returns (bytes_to_upload, mime_type, true_width, true_height, sent_size).
    `sent_size` is None when the original bytes are uploaded untouched.
    """
    with Image.open(photo) as im:
        im = ImageOps.exif_transpose(im)   # bake rotation in; measure what the model sees
        src_w, src_h = im.size

        if UPLOAD_LONG_EDGE is None or max(src_w, src_h) <= UPLOAD_LONG_EDGE:
            return photo.read_bytes(), _mime(photo), src_w, src_h, None

        small = im.convert("RGB")
        small.thumbnail((UPLOAD_LONG_EDGE, UPLOAD_LONG_EDGE), Image.LANCZOS)
        buf = BytesIO()
        small.save(buf, "JPEG", quality=UPLOAD_JPEG_QUALITY)
        return buf.getvalue(), "image/jpeg", src_w, src_h, small.size


def _mime(photo: Path) -> str:
    mime_type, _ = mimetypes.guess_type(str(photo))
    return mime_type or "application/octet-stream"


def upload(data: bytes, mime_type: str, file_name: str, attempts: int = 3) -> str:
    """Put the source on fal's CDN, with retries.

    Uploading crosses the network twice — a CDN auth-token refresh, then the
    transfer — and either can time out transiently. Observed in practice, so
    this retries rather than letting a blip kill the run (or, in a batch, that
    photo). Nothing has been submitted at this point, so a retry costs nothing.
    """
    import fal_client

    last = None
    for attempt in range(1, attempts + 1):
        try:
            return fal_client.upload(data, mime_type, file_name=file_name)
        except Exception as e:                  # noqa: BLE001 — retry any transport failure
            last = e
            if attempt < attempts:
                time.sleep(2 * attempt)
    fail(f"could not upload source after {attempts} attempts: "
         f"{type(last).__name__}: {last}")


def download(url: str, dest: Path, attempts: int = 3) -> None:
    """Fetch the finished image, with a timeout and retries.

    The first fetch of a fresh result can be slow — fal's CDN materializes the
    object at its edge on that request, which has been measured at ~50s for a
    file that then re-downloads in ~1s. That is normal and server-side. What
    matters here is the timeout: a hung fetch must fail and retry rather than
    stall a whole batch forever, which is what a bare urlretrieve would do.
    """
    import httpx

    last = None
    for attempt in range(1, attempts + 1):
        try:
            with httpx.stream("GET", url, timeout=DOWNLOAD_TIMEOUT,
                              follow_redirects=True) as r:
                r.raise_for_status()
                with dest.open("wb") as fh:
                    for chunk in r.iter_bytes(65536):
                        fh.write(chunk)
            return
        except Exception as e:                  # noqa: BLE001 — retry any transport failure
            last = e
            dest.unlink(missing_ok=True)
            if attempt < attempts:
                time.sleep(2 * attempt)
    # phase="after": by the time anything is downloaded the model has already
    # run and fal has already billed for it. Reporting this as "before" would
    # tell you at 2am that nothing was charged, which is the one thing the
    # phase field exists to answer correctly.
    fail(f"could not download result after {attempts} attempts: {last}",
         phase="after")


def rel(p: Path) -> str:
    """Path for display: project-relative when it is inside the project."""
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)


def run(photo: Path, model: str = DEFAULT_MODEL,
        emit=print, out_dir: "Path | None" = None,
        extra: "str | None" = None) -> Path:
    """Run one photo through the pipeline. Returns the saved image path.
    Raises EnhanceError on failure.

    Results land in `out_dir`, which defaults to the photo's own folder — for
    a job that means `Job_NNNN/` gets the source, the enhanced image, and the
    log side by side.

    Used by the CLI below and by batch.py. `emit` collects this photo's
    progress lines — batch.py hands it a per-photo buffer so parallel runs
    don't interleave their output.

    `extra` is the comment written at the gate when this photo was sent back.
    It is appended to PROMPT.md's text for this run only, and recorded in the
    log beside the base fingerprint rather than folded into it.
    """
    t_start = time.time()
    if not photo.is_absolute():
        photo = (ROOT / photo).resolve()
    if not photo.exists():
        fail(f"no such photo: {photo}")

    out_dir = out_dir or photo.parent
    stem = photo.stem
    prompt, prompt_id = load_prompt()

    extra = (extra or "").strip()
    if extra:
        # Appended last so it reads as the most recent instruction. An absolute
        # rule earlier in PROMPT.md still outranks it — see CONTEXT.md, "When an
        # instruction is being ignored, look for the conflict".
        prompt = f"{prompt}\n\nCorreção para esta foto: {extra}"

    t = time.time()
    upload_bytes, mime_type, src_w, src_h, sent_size = prepare_upload(photo)
    t_prepare = time.time() - t

    gpt_image = is_gpt_image(model)

    emit(f"photo       {photo.name}  {src_w}x{src_h}  "
         f"({photo.stat().st_size / 1e6:.1f} MB)")
    emit(f"prompt      {PROMPT_PATH.name}  {len(prompt)} chars  #{prompt_id}")
    emit(f"model       {model}")
    if sent_size:
        emit(f"uploading   {sent_size[0]}x{sent_size[1]}  "
             f"{len(upload_bytes) / 1e6:.2f} MB  (downscaled in {t_prepare:.1f}s)")
    else:
        emit(f"uploading   {src_w}x{src_h}  {len(upload_bytes) / 1e6:.2f} MB  (as-is)")

    if gpt_image:
        image_size = custom_image_size(src_w, src_h)
        emit(f"quality     {QUALITY}   image_size {image_size['width']}x{image_size['height']}"
             f"   (source {src_w / src_h:.3f})")

        payload = {
            "prompt": prompt,
            "num_images": NUM_IMAGES,
            "image_size": image_size,
            "quality": QUALITY,
            "output_format": "jpeg",
        }
    else:
        ratio = nearest_ratio(src_w, src_h)
        emit(f"resolution  {RESOLUTION}   aspect_ratio {ratio}"
             f"   (source {src_w / src_h:.3f})")

        payload = {
            "prompt": prompt,
            "num_images": NUM_IMAGES,
            "aspect_ratio": ratio,
            "resolution": RESOLUTION,
            "output_format": "jpeg",
        }
        if SEED is not None:
            payload["seed"] = SEED

    from dotenv import load_dotenv
    load_dotenv(ROOT / "_config" / ".env")
    import os
    if not os.environ.get("FAL_KEY"):
        fail("FAL_KEY is not set. Put it in _config/.env (see _config/.env.example) or export it.")

    import fal_client

    t = time.time()
    image_url = upload(
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
        download(img["url"], dest)
        with Image.open(dest) as out:
            out_w, out_h = out.size
        saved.append((dest, out_w, out_h, img["url"]))
        emit(f"saved       {rel(dest)}  {out_w}x{out_h}")
    t_download = time.time() - t
    t_total = time.time() - t_start

    log = out_dir / f"{stem}_log.md"
    lines = [
        f"# {stem} — Generation Log", "",
        "| | |", "|---|---|",
        f"| Run | {datetime.now(timezone.utc).isoformat(timespec='seconds')} |",
        f"| Source | `{photo.name}` · {src_w}×{src_h} |",
        f"| Model | `{model}` |",
        f"| Prompt | `PROMPT.md` · {len(prompt)} chars · fingerprint `#{prompt_id}` |",
    ]
    if extra:
        # Recorded beside the fingerprint, never folded into it. The fingerprint
        # answers "which PROMPT.md wording was in force"; this answers "and what
        # was added for this one photo".
        lines.append(f"| Correção desta foto | {extra} |")
    if gpt_image:
        lines += [
            f"| Quality | {QUALITY} |",
            f"| Image size | {image_size['width']}x{image_size['height']} (source {src_w / src_h:.3f}) |",
        ]
    else:
        lines += [
            f"| Resolution | {RESOLUTION} |",
            f"| Aspect ratio | {ratio} (source {src_w / src_h:.3f}) |",
        ]
    sent_desc = (f"{sent_size[0]}×{sent_size[1]} · {len(upload_bytes) / 1e6:.2f} MB (downscaled)"
                 if sent_size else f"{src_w}×{src_h} · {len(upload_bytes) / 1e6:.2f} MB (as-is)")
    lines += [
        f"| Sent to model | {sent_desc} |",
        f"| Timing | {t_total:.0f}s total — prepare {t_prepare:.1f}s · upload "
        f"{t_upload:.1f}s · generate {t_generate:.0f}s · download {t_download:.1f}s |",
        f"| Uploaded source | {image_url} |",
        "",
        "## Output", "",
    ]
    for dest, w, h, url in saved:
        lines.append(f"- `{rel(dest)}` — {w}×{h} — [fal url]({url})")
    if result.get("description"):
        lines += ["", "## Model description of its own edit", "",
                  f"> {result['description']}"]
    lines += ["", f"## Prompt as sent (`#{prompt_id}`)", "", "```", prompt, "```", ""]
    log.write_text("\n".join(lines), encoding="utf-8")
    emit(f"logged      {rel(log)}")
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
