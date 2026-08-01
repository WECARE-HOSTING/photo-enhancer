#!/usr/bin/env python3
"""The trip to fal.ai, and the settings that govern it. Shared by both phases.

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "_config"))
    import fal
    data, mime, w, h, sent = fal.prepare_upload(photo)
    url = fal.upload(data, mime, file_name="photo.jpg")

`1 - edicao/enhance.py` and `2 - retoque/retoque.py` make the same journey —
prepare, upload, submit, download — and differ only in **what they send**:
phase 1 sends the source photo with a fixed prompt, phase 3 sends the edit plus
the original with the human's own sentence. That difference is the whole point
of the two folders, so it lives there; the journey lives here.

It lives in `_config/` rather than in either folder because `retoque.py`
importing `enhance.py` would make phase 3 depend on phase 1, and the two would
stop being independent contracts — which is the reason they were split.

**Every tunable is a constant in this file.** Model, quality, size, timeouts.
Edit the constant; there are no flags to remember. (`WORKERS` is the exception
and lives in `1 - edit/batch.py`, because how many photos run at once is that
script's concern, not the API's.)
"""

from __future__ import annotations

import mimetypes
import os
import time
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps

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

# How long to wait on the HEAD that asks whether a source URL recorded in an old
# log is still alive. Short on purpose: this is an optimisation check, and
# re-uploading the original costs ~4s, so a slow answer is worse than no answer.
HEAD_TIMEOUT = 15

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


def require_key() -> None:
    """Load `_config/.env` and insist FAL_KEY is there, before anything uploads."""
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
    if not os.environ.get("FAL_KEY"):
        fail("FAL_KEY is not set. Put it in _config/.env (see _config/.env.example) "
             "or export it.")


# ------------------------------------------------------------------- geometry

def is_gpt_image(model: str) -> bool:
    return "gpt-image" in model


def nearest_ratio(width: int, height: int) -> str:
    target = width / height
    return min(RATIOS, key=lambda r: abs(RATIOS[r] - target))


def round16(x: float) -> int:
    return max(16, round(x / 16) * 16)


def custom_image_size(src_w: int, src_h: int,
                      long_edge: int = TARGET_LONG_EDGE) -> dict:
    """Custom {width, height} matching the source's exact aspect ratio at ~2K."""
    ratio = src_w / src_h
    if ratio >= 1:
        w, h = long_edge, long_edge / ratio
    else:
        w, h = long_edge * ratio, long_edge
    return {"width": round16(w), "height": round16(h)}


def payload_for(model: str, prompt: str, src_w: int, src_h: int,
                num_images: int = NUM_IMAGES) -> "tuple[dict, str]":
    """The request body minus `image_urls`, plus one line describing it.

    Branches on the model family: gpt-image-2 takes `image_size` + `quality`,
    the nano-banana family takes `aspect_ratio` + `resolution` and is the only
    one with a `seed`. Both callers need the same branch, so it lives here.
    """
    if is_gpt_image(model):
        image_size = custom_image_size(src_w, src_h)
        return ({
            "prompt": prompt,
            "num_images": num_images,
            "image_size": image_size,
            "quality": QUALITY,
            "output_format": "jpeg",
        }, f"quality     {QUALITY}   image_size "
           f"{image_size['width']}x{image_size['height']}   "
           f"(source {src_w / src_h:.3f})")

    ratio = nearest_ratio(src_w, src_h)
    body = {
        "prompt": prompt,
        "num_images": num_images,
        "aspect_ratio": ratio,
        "resolution": RESOLUTION,
        "output_format": "jpeg",
    }
    if SEED is not None:
        body["seed"] = SEED
    return body, (f"resolution  {RESOLUTION}   aspect_ratio {ratio}   "
                  f"(source {src_w / src_h:.3f})")


def settings_row(model: str, payload: dict, src_w: int, src_h: int) -> "list[str]":
    """The model-family-specific rows of a log table, for either phase."""
    if is_gpt_image(model):
        size = payload["image_size"]
        return [f"| Quality | {QUALITY} |",
                f"| Image size | {size['width']}x{size['height']} "
                f"(source {src_w / src_h:.3f}) |"]
    return [f"| Resolution | {RESOLUTION} |",
            f"| Aspect ratio | {payload['aspect_ratio']} "
            f"(source {src_w / src_h:.3f}) |"]


# --------------------------------------------------------------------- the wire

def prepare_upload(photo: Path) -> "tuple[bytes, str, int, int, tuple[int, int] | None]":
    """Read the photo, honor its EXIF orientation, and downscale it for upload.

    Returns (bytes_to_upload, mime_type, true_width, true_height, sent_size).
    `sent_size` is None when the original bytes are uploaded untouched — which
    is what happens to a `_edit.jpg` in phase 3, since it is already at 2048px.
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
    """Put an image on fal's CDN, with retries.

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


def url_alive(url: str) -> bool:
    """Does this fal CDN URL still serve? Used before reusing one from an old log.

    fal's uploads have outlived every job measured so far, but "the URL recorded
    a month ago still resolves" is an assumption, not a guarantee, and the cost
    of being wrong is a request that reaches the model with a broken reference
    and gets billed anyway. A HEAD is ~200ms against a ~4s re-upload.
    """
    import httpx
    try:
        r = httpx.head(url, timeout=HEAD_TIMEOUT, follow_redirects=True)
        return r.status_code < 400
    except Exception:                           # noqa: BLE001 — no answer is a dead URL
        return False


def download(url: str, dest: Path, attempts: int = 3) -> None:
    """Fetch the finished image, with a timeout and retries. Atomic.

    The first fetch of a fresh result can be slow — fal's CDN materializes the
    object at its edge on that request, which has been measured at ~50s for a
    file that then re-downloads in ~1s. That is normal and server-side. What
    matters here is the timeout: a hung fetch must fail and retry rather than
    stall a whole batch forever, which is what a bare urlretrieve would do.

    **It writes to `<dest>.part` and renames.** In phase 3 the destination *is*
    the image that was uploaded as input — a failed download that truncated or
    unlinked `dest` would destroy the photo needed to try again. `os.replace()`
    is atomic on the same filesystem, so `dest` is either the old file or the
    new one, never half of either.
    """
    import httpx

    part = dest.with_name(dest.name + ".part")
    last = None
    for attempt in range(1, attempts + 1):
        try:
            with httpx.stream("GET", url, timeout=DOWNLOAD_TIMEOUT,
                              follow_redirects=True) as r:
                r.raise_for_status()
                with part.open("wb") as fh:
                    for chunk in r.iter_bytes(65536):
                        fh.write(chunk)
            os.replace(part, dest)
            return
        except Exception as e:                  # noqa: BLE001 — retry any transport failure
            last = e
            part.unlink(missing_ok=True)
            if attempt < attempts:
                time.sleep(2 * attempt)
    # phase="after": by the time anything is downloaded the model has already
    # run and fal has already billed for it. Reporting this as "before" would
    # tell you at 2am that nothing was charged, which is the one thing the
    # phase field exists to answer correctly.
    fail(f"could not download result after {attempts} attempts: {last}",
         phase="after")
