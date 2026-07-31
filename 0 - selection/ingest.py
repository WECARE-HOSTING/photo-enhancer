#!/usr/bin/env python3
"""Read one delivered file cheaply: a proxy, its EXIF facts, and its geometry.

    ./_config/.venv/bin/python "0 - selection/ingest.py" "0 - selection/Casa Nirvana/source/DSC_0142.NEF"

Used by `cull.py` on every file in a delivery, and standalone to see what one
file measures. Nothing here judges a photo or writes into the delivery except
the proxy; the thresholds and the picking live in `cull.py`.

**The RAW file is never decoded.** Every camera writes a full JPEG preview
inside its own raw file, and `rawpy.extract_thumb()` hands that over without
demosaicing — milliseconds instead of seconds, and no 150 MB intermediate. A
500-file shoot becomes 500 small proxies in about a minute, and the negatives
are only ever developed for the ~30 frames that get picked (`develop.py`).

What comes back is three kinds of fact, and they are not equally trustworthy:

- **EXIF** — exact when present, and frequently absent. Measured on a real
  delivery: `FocalLengthIn35mmFilm` was in 12 of 40 files, `DateTimeOriginal`
  in 26, `BracketShotNumber` in none. So every field here is optional and the
  caller has to cope with `None` rather than assume a number.
- **Pixel geometry** — always available, since it is measured rather than read.
  Sharpness, clipping, and vertical convergence come out of the proxy itself.
- **A perceptual hash** — for finding the same corner shot five times.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from io import BytesIO
from pathlib import Path

import cv2
import exifread
import imagehash
import numpy as np
from PIL import Image, ImageOps
from pillow_heif import register_heif_opener

# Phones shoot HEIC by default, so a delivery pulled off someone's camera roll
# is mostly .heic — but Pillow has no HEIF decoder of its own and reports the
# file as unidentifiable. This registers one, and it has to happen before the
# first Image.open() anywhere in the process.
register_heif_opener()

SELECTION_DIR = Path(__file__).resolve().parent
ROOT = SELECTION_DIR.parent

# Proxies are for judging, not for output. 1600px is enough to see composition,
# clutter, and whether a bed is made, and is also plenty for the vision scorer
# (which reads at ~1024). ~300 KB each, so a 500-file shoot costs ~150 MB.
PROXY_LONG_EDGE = 1600
PROXY_QUALITY = 88

# Geometry is measured on a smaller copy: Hough and Laplacian scale with pixel
# count and gain nothing from resolution here. Fixed, not proportional, so the
# numbers are comparable between a 24 MP body and a 45 MP one.
WORK_LONG_EDGE = 1024

# --- vertical convergence (the doc's "three-point perspective") --------------
# How far from vertical a segment may lean and still count as a vertical
# architectural feature.
#
# This one number decides whether the measurement means anything. At 32 deg it
# also collects ceiling drying racks, floor grout, and patterned glass — long,
# parallel, consistently angled, and indistinguishable from converging
# architecture to any line fit. On a real delivery that reported a 40 deg roll
# for a laundry room whose walls are plainly straight.
#
# Swept against 46 real photos: 32 deg gave a p90 roll of 28.9 deg (nonsense),
# 15 deg gives 5.3 deg while still measuring 74% of frames. Tighter than that
# just loses coverage.
#
# The trade this accepts: a frame genuinely tilted past ~15 deg now reports
# *unmeasurable* rather than a big number. That is the right way round — a tilt
# that large is obvious at a glance on the contact sheet, and the reason to
# measure at all is the 3-6 deg lean that slips past the eye.
VERTICAL_TOLERANCE_DEG = 15
# ...and at least this fraction of the frame's height, so texture and clutter
# don't outvote the architecture.
MIN_LINE_FRACTION = 0.14
# Below this many usable segments the fit is noise. Reported as unknown rather
# than as zero, because "no verticals found" and "verticals are straight" are
# very different facts and conflating them silently passes bad frames.
MIN_LINES_FOR_FIT = 6
# The verticals also have to be spread out. A left-to-right trend measured from
# lines that all sit in one narrow column is extrapolation, not measurement.
MIN_X_SPAN_FRACTION = 0.35

# 35mm-equivalent focal length is what the wide-angle rule is actually about,
# but the EXIF field carrying it is usually missing. Body model -> crop factor
# lets it be derived from the plain FocalLength instead.
#
# **Add your photographers' bodies here as they show up.** An unknown body is
# reported as unknown, never guessed: a 12mm lens is a hard reject on full frame
# and perfectly fine on APS-C, so a wrong crop factor either throws away good
# photos or waves distorted ones through.
CROP_FACTORS = {
    r"ILCE-7|A7|DSC-RX1|EOS R[P58]?$|EOS 5D|EOS 6D|EOS 1D X|D8[0-9]{2}|D7[45]0|Z [678]|LUMIX S": 1.0,
    r"ILCE-6|EOS R7|EOS R10|EOS 90D|EOS 7D|D5[0-9]{3}|D7[0-9]{3}|Z 50|Z fc|X-T[0-9]|X-H[0-9]|X-Pro": 1.5,
    r"EOS M|EOS [0-9]{3}D|EOS Rebel": 1.6,
    r"DC-G|DMC-G|OM-1|OM-5|E-M[0-9]": 2.0,
}

RAW_EXTS = {
    ".nef", ".nrw", ".cr2", ".cr3", ".crw", ".arw", ".srf", ".sr2", ".raf",
    ".orf", ".rw2", ".pef", ".dng", ".srw", ".3fr", ".fff", ".iiq", ".erf",
    ".mos", ".mrw", ".x3f",
}


class IngestError(Exception):
    """This one file could not be read. Raised so a batch can carry on."""


@dataclass
class Facts:
    """Everything cheap that is knowable about one delivered file.

    Optional fields are `None` when the camera or the delivery did not provide
    them — never a stand-in value. A zero exposure bias and an unknown exposure
    bias group brackets very differently.
    """
    path: Path
    proxy: "Path | None" = None
    width: int = 0
    height: int = 0
    bytes_on_disk: int = 0
    is_raw: bool = False
    preview_source: str = ""          # "embedded" | "developed" | "file"

    # EXIF, all optional
    shot_at: "datetime | None" = None
    subsec: int = 0                   # ties inside one second, for bracket order
    exposure_bias: "float | None" = None
    exposure_time: "float | None" = None
    iso: "int | None" = None
    focal_mm: "float | None" = None
    focal_35mm: "float | None" = None
    focal_35mm_source: str = "none"   # "exif" | "derived" | "none"
    camera: "str | None" = None
    orientation_applied: bool = False

    # measured from pixels, always present
    sharpness: float = 0.0
    shadow_clip: float = 0.0
    highlight_clip: float = 0.0
    convergence_deg: "float | None" = None   # verticals splaying across frame
    roll_deg: "float | None" = None          # camera not level
    lines_found: int = 0
    phash: str = ""

    notes: "list[str]" = field(default_factory=list)

    @property
    def aspect(self) -> float:
        return self.width / self.height if self.height else 0.0

    @property
    def is_portrait(self) -> bool:
        return self.aspect < 1.0


def rel(p: Path) -> str:
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)


# ------------------------------------------------------------------ the image

def load_preview(photo: Path) -> "tuple[Image.Image, str]":
    """Get a viewable RGB image out of `photo` as cheaply as possible.

    For a raw file that means the camera's own embedded JPEG. Falling back to
    an actual raw decode is ~50x slower, so it is a last resort and gets noted —
    if it happens across a whole delivery, something is wrong with the files,
    not with the shoot.
    """
    if photo.suffix.lower() in RAW_EXTS:
        import rawpy
        try:
            with rawpy.imread(str(photo)) as raw:
                thumb = raw.extract_thumb()
                if thumb.format == rawpy.ThumbFormat.JPEG:
                    return Image.open(BytesIO(thumb.data)).convert("RGB"), "embedded"
                return Image.fromarray(thumb.data).convert("RGB"), "embedded"
        except Exception:                       # noqa: BLE001 — any libraw failure
            pass
        try:
            with rawpy.imread(str(photo)) as raw:
                rgb = raw.postprocess(half_size=True, use_camera_wb=True,
                                      no_auto_bright=True)
            return Image.fromarray(rgb), "developed"
        except Exception as e:                  # noqa: BLE001
            raise IngestError(f"libraw could not read it: {type(e).__name__}: {e}")

    try:
        return Image.open(photo).convert("RGB"), "file"
    except Exception as e:                      # noqa: BLE001
        raise IngestError(f"not a readable image: {type(e).__name__}: {e}")


def write_proxy(im: Image.Image, dest: Path) -> Image.Image:
    """Save the judging-size copy and return it (already oriented)."""
    small = im.copy()
    small.thumbnail((PROXY_LONG_EDGE, PROXY_LONG_EDGE), Image.LANCZOS)
    dest.parent.mkdir(parents=True, exist_ok=True)
    small.save(dest, "JPEG", quality=PROXY_QUALITY, optimize=True)
    return small


# ------------------------------------------------------------------- the EXIF

def _ratio(tag) -> "float | None":
    """exifread hands back Ratio objects, ints, and lists interchangeably."""
    try:
        v = tag.values
        if isinstance(v, (list, tuple)):
            if not v:
                return None
            v = v[0]
        return float(v.num) / float(v.den) if hasattr(v, "den") else float(v)
    except Exception:                           # noqa: BLE001
        return None


def crop_factor(model: "str | None") -> "float | None":
    if not model:
        return None
    for pattern, factor in CROP_FACTORS.items():
        if re.search(pattern, model, re.I):
            return factor
    return None


def read_exif(photo: Path, facts: Facts) -> None:
    """Fill in whatever EXIF this file happens to carry.

    Deliberately forgiving: a delivery routinely mixes bodies, phone shots, and
    files that went through an editor that stripped everything. Missing fields
    are left as None so the caller can degrade instead of trusting a default.
    """
    try:
        with photo.open("rb") as fh:
            tags = exifread.process_file(fh, details=False)
    except Exception as e:                      # noqa: BLE001
        facts.notes.append(f"EXIF unreadable ({type(e).__name__})")
        return

    if not tags:
        facts.notes.append("no EXIF at all — no timestamp, no focal length")
        return

    for key in ("EXIF DateTimeOriginal", "EXIF DateTimeDigitized", "Image DateTime"):
        if key in tags:
            try:
                facts.shot_at = datetime.strptime(str(tags[key]), "%Y:%m:%d %H:%M:%S")
                break
            except ValueError:
                continue
    else:
        facts.notes.append("no timestamp — cannot be grouped into a bracket")

    for key in ("EXIF SubSecTimeOriginal", "EXIF SubSecTime"):
        if key in tags and str(tags[key]).strip().isdigit():
            facts.subsec = int(str(tags[key]).strip()[:3].ljust(3, "0"))
            break

    if "EXIF ExposureBiasValue" in tags:
        facts.exposure_bias = _ratio(tags["EXIF ExposureBiasValue"])
    if "EXIF ExposureTime" in tags:
        facts.exposure_time = _ratio(tags["EXIF ExposureTime"])
    if "EXIF ISOSpeedRatings" in tags:
        iso = _ratio(tags["EXIF ISOSpeedRatings"])
        facts.iso = int(iso) if iso else None
    if "Image Model" in tags:
        facts.camera = str(tags["Image Model"]).strip() or None
    if "EXIF FocalLength" in tags:
        facts.focal_mm = _ratio(tags["EXIF FocalLength"])

    # The field the wide-angle rule wants, when the camera bothered to write it.
    for key in ("EXIF FocalLengthIn35mmFilm", "EXIF FocalLengthIn35mmFormat"):
        if key in tags:
            if v := _ratio(tags[key]):
                facts.focal_35mm, facts.focal_35mm_source = v, "exif"
            break

    # Otherwise derive it, but only from a body we actually recognize.
    if facts.focal_35mm is None and facts.focal_mm:
        if cf := crop_factor(facts.camera):
            facts.focal_35mm = round(facts.focal_mm * cf, 1)
            facts.focal_35mm_source = "derived"
        else:
            facts.notes.append(
                f"focal length is {facts.focal_mm:.0f}mm but the sensor size is "
                f"unknown{f' for {facts.camera}' if facts.camera else ''}, so the "
                "35mm equivalent can't be worked out — add the body to "
                "CROP_FACTORS in ingest.py")


# --------------------------------------------------------------- the geometry

def measure(small: Image.Image, facts: Facts) -> None:
    """Measure what the pixels say, independent of what EXIF claims."""
    work = small.copy()
    work.thumbnail((WORK_LONG_EDGE, WORK_LONG_EDGE), Image.BILINEAR)
    gray = np.asarray(work.convert("L"))

    # Focus. Absolute values are meaningless across scenes — a flat white wall
    # scores low while sharp — so cull.py only ever compares this *within* a
    # cluster of the same subject.
    lap = cv2.Laplacian(gray, cv2.CV_64F)
    facts.sharpness = float(lap.var())

    total = gray.size
    facts.shadow_clip = float((gray <= 2).sum() / total * 100)
    facts.highlight_clip = float((gray >= 253).sum() / total * 100)

    conv, roll, n = vertical_geometry(gray)
    facts.convergence_deg, facts.roll_deg, facts.lines_found = conv, roll, n
    facts.phash = str(imagehash.phash(work))


def vertical_geometry(gray: np.ndarray) -> "tuple[float | None, float | None, int]":
    """Measure whether the building's verticals stay vertical.

    Returns (convergence_deg, roll_deg, n_lines), or (None, None, n) when there
    is not enough architecture in frame to say.

    The distinction being drawn matters, because the two failures have different
    fixes and the doc only condemns one of them:

    - **roll** — the whole frame is rotated. Every vertical leans the same way.
      A level correction fixes it, and it costs a small crop.
    - **convergence** — the camera was pitched up or down, so verticals splay:
      the ones on the left lean one way and the ones on the right lean the
      other. This is the "three-point perspective" / "falling backwards" look
      the strategy document rejects outright, and no rotation fixes it.

    Which is which comes out of *where* each line sits: if lean correlates with
    horizontal position, that is convergence; if every line leans alike, that is
    roll. So a line is fitted through (x_centre, lean) and its slope across the
    full frame width is the convergence.
    """
    h, w = gray.shape
    edges = cv2.Canny(gray, 60, 180, apertureSize=3)
    segments = cv2.HoughLinesP(edges, rho=1, theta=np.pi / 360, threshold=60,
                               minLineLength=int(h * MIN_LINE_FRACTION),
                               maxLineGap=int(h * 0.02))
    if segments is None or len(segments) == 0:
        return None, None, 0

    # OpenCV 4 returns (N, 1, 4); OpenCV 5 dropped the middle axis and returns
    # (N, 4). Reshaping covers both instead of betting on the installed version.
    segments = np.asarray(segments).reshape(-1, 4)

    xs, leans = [], []
    for x1, y1, x2, y2 in segments:
        dx, dy = float(x2 - x1), float(y2 - y1)
        if dy == 0:
            continue
        # Lean from true vertical, signed. atan2 on (dx, dy) with dy forced
        # positive keeps the sign meaningful instead of flipping with the
        # direction Hough happened to walk the segment.
        if dy < 0:
            dx, dy = -dx, -dy
        lean = np.degrees(np.arctan2(dx, dy))
        if abs(lean) > VERTICAL_TOLERANCE_DEG:
            continue
        if np.hypot(dx, dy) < h * MIN_LINE_FRACTION:
            continue
        xs.append((x1 + x2) / 2.0)
        leans.append(lean)

    n = len(xs)
    if n < MIN_LINES_FOR_FIT:
        return None, None, n

    x = np.asarray(xs, dtype=float)
    y = np.asarray(leans, dtype=float)

    # The verticals must actually spread across the frame before a left-to-right
    # trend can be claimed. When they all sit in one narrow band — a single door
    # frame, a stack of shelf edges — the fitted slope is unconstrained, and
    # multiplying it by the full frame width extrapolates nonsense. Measured on a
    # real 307-photo delivery, that produced convergence values above 200 deg and
    # rolls above 80, which is impossible for a photograph and would have made
    # every threshold above it meaningless.
    if (x.max() - x.min()) < w * MIN_X_SPAN_FRACTION:
        return None, None, n

    # Theil-Sen rather than least squares: the median of pairwise slopes ignores
    # the handful of segments that latched onto a curtain fold or a rug pattern,
    # where polyfit lets them drag the whole line.
    idx = np.arange(n)
    if n > 40:                                   # cap the pair count on busy frames
        idx = np.linspace(0, n - 1, 40).astype(int)
    xi, yi = x[idx], y[idx]
    i, j = np.triu_indices(len(xi), k=1)
    dx = xi[j] - xi[i]
    usable = np.abs(dx) > w * 0.05               # ignore near-vertical pairs
    if usable.sum() < 3:
        return None, None, n
    slopes = (yi[j][usable] - yi[i][usable]) / dx[usable]
    slope = float(np.median(slopes))

    # Roll is the lean at frame centre, taken as the median residual so one bad
    # segment cannot shift it either.
    intercept = float(np.median(y - slope * (x - w / 2.0)))

    convergence = abs(slope * w)                 # total splay, edge to edge
    return round(convergence, 2), round(intercept, 2), n


# ----------------------------------------------------------------------- read

def probe(photo: Path) -> Facts:
    """EXIF only — no pixels touched, no proxy written.

    Exists so a delivery can be *profiled* before it is processed. Reading the
    EXIF header of 307 files takes about a second; decoding their pixels takes
    seventeen. Deciding what kind of delivery this is (labelled JPEGs? bracketed
    raw? an already-culled set?) needs only the header, so a wrong guess about
    the delivery gets caught before the expensive pass, not after it.
    """
    facts = Facts(path=photo, bytes_on_disk=photo.stat().st_size,
                  is_raw=photo.suffix.lower() in RAW_EXTS)
    read_exif(photo, facts)
    return facts


def read(photo: Path, proxy_dir: "Path | None" = None) -> Facts:
    """Everything cheap about one file. Raises IngestError if it can't be read."""
    facts = Facts(path=photo, bytes_on_disk=photo.stat().st_size,
                  is_raw=photo.suffix.lower() in RAW_EXTS)

    im, source = load_preview(photo)
    facts.preview_source = source
    if source == "developed":
        facts.notes.append("no embedded preview — had to decode the raw file, "
                           "which is ~50x slower")

    before = im.size
    im = ImageOps.exif_transpose(im)
    facts.orientation_applied = im.size != before
    facts.width, facts.height = im.size

    proxy_dir = proxy_dir or (photo.parent.parent / "_proxies")
    facts.proxy = proxy_dir / f"{photo.stem}.jpg"
    small = write_proxy(im, facts.proxy)
    im.close()

    read_exif(photo, facts)
    measure(small, facts)
    small.close()
    return facts


def shutter(t: "float | None") -> str:
    """Shutter speed the way a photographer writes it.

    Interiors on a tripod routinely run past a second, where `1/round(1/t)`
    collapses to a nonsensical `1/0`.
    """
    if not t:
        return "—"
    return f"{t:.1f}s" if t >= 1 else f"1/{round(1 / t)}"


def describe(f: Facts) -> "list[str]":
    """One file's facts as printable lines — used by the CLI and by --explain."""
    def opt(v, fmt="{:.1f}", dash="—"):
        return dash if v is None else fmt.format(v)

    lines = [
        f"file        {f.path.name}  {f.width}x{f.height}  "
        f"{f.bytes_on_disk / 1e6:.1f} MB  {'raw' if f.is_raw else 'jpeg'}",
        f"preview     {f.preview_source}"
        + ("  (orientation applied)" if f.orientation_applied else ""),
        f"proxy       {rel(f.proxy)}" if f.proxy else "proxy       —",
        f"shot        {f.shot_at.isoformat(sep=' ') if f.shot_at else '—'}"
        + (f".{f.subsec:03d}" if f.shot_at and f.subsec else "")
        + f"   ev {opt(f.exposure_bias, '{:+.2f}')}"
        + f"   {shutter(f.exposure_time)}"
        + f"   iso {f.iso or '—'}",
        f"camera      {f.camera or '—'}   "
        f"{opt(f.focal_mm, '{:.0f}mm')} → {opt(f.focal_35mm, '{:.0f}mm')} eq "
        f"({f.focal_35mm_source})",
        f"sharpness   {f.sharpness:.0f}   "
        f"clip {f.shadow_clip:.1f}% dark / {f.highlight_clip:.1f}% blown",
        f"verticals   convergence {opt(f.convergence_deg, '{:.2f}°')}   "
        f"roll {opt(f.roll_deg, '{:+.2f}°')}   from {f.lines_found} line(s)"
        + ("  — too few to judge" if f.convergence_deg is None else ""),
        f"phash       {f.phash}",
    ]
    lines += [f"note        {n}" for n in f.notes]
    return lines


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("photo", help="one delivered file (raw or jpeg)")
    ap.add_argument("--proxy-dir", type=Path,
                    help="where to write the proxy (default: ../_proxies/)")
    args = ap.parse_args()

    photo = Path(args.photo)
    if not photo.is_absolute():
        photo = (ROOT / photo).resolve() if not photo.exists() else photo.resolve()
    if not photo.exists():
        sys.exit(f"error: no such file: {photo}")

    try:
        facts = read(photo, args.proxy_dir)
    except IngestError as e:
        sys.exit(f"error: {photo.name}: {e}")
    for line in describe(facts):
        print(line)


if __name__ == "__main__":
    main()
