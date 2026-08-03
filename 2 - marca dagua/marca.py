#!/usr/bin/env python3
"""Put the WeCare mark on one photo, in the corner, legible over whatever is there.

    ./_config/.venv/bin/python "2 - marca dagua/marca.py" "2 - marca dagua/Job_0023/SALA_01_0001_edit.jpg"
    ./_config/.venv/bin/python "2 - marca dagua/marca.py" <photo> --variant claro

Reads `<name>_edit.jpg`, writes `<name>_final.jpg` beside it. The API's output is
never touched, which is what makes re-marking free: change a number below, run
`batch.py --rebrand`, and the whole job is redone in seconds without another
fal.ai call.

**The mark could not be asked of the model.** `PROMPT.md` forbids adding anything
to a room, and merely naming a watermark in a prompt trips fal's content policy —
the request is rejected before it reaches the model. Compositing locally is the
only route compatible with the stage's contract.

## Choosing the ink

The art is the stacked WeCare lockup — pin over `wecare HOSTING` — in two
colourways with nothing in them but one ink: pure black `#000000` for light
backgrounds and pure white `#FFFFFF` for dark ones. Which one goes on is decided
per photo, from the pixels the art will actually cover:

  1. Alpha-weighted WCAG relative luminance of that exact rectangle — only the
     pixels the strokes land on count, not the empty space between them.
  2. Contrast against each ink; the higher one wins.
  3. If even the winner is under MIN_CONTRAST or the background is busier than
     BUSY_STD (foliage, a bookcase, a venetian blind), a soft glow goes
     underneath — the art's own alpha, blurred, in the opposite tone. A halo that
     follows the letterforms, never a box or a band, which would wreck the
     photograph.

**Black and white are the extremes of the scale, so step 2 can no longer fail.**
The two inks sit at L=0 and L=1; the worst possible background is the luminance
where they tie, and even there the winner is 4.58:1. Every real photograph
measures better. MIN_CONTRAST is kept as a floor for a future non-extreme
colourway and as the number the gate page prints, but with this art the glow is
decided by BUSY_STD alone.

Measured over 278 real photographs (the archive plus Job_0023) at
LOGO_HEIGHT_PCT = 0.10: 75% black, 25% white, glow on 21%, worst contrast
4.61:1, median 9.34:1. The rates move with LOGO_HEIGHT_PCT — at 0.08 the glow
fires on 13%, at 0.14 on 28% — because a bigger mark samples a bigger patch, so
re-measure when you change the size. It is free.

What the measurement does not catch is a mark that straddles an edge: art half on
a dark headboard and half on a light ceiling reads as a low spread over a mid
luminance, and one half of the lockup goes quiet. That is what `glow=on` at the
gate is for; no threshold finds it, because the patch really is uniform on
average.

The previous art was a horizontal lockup in navy and cream, both carrying a
mid-tone gold that lost force in warm light — the fragile element the thresholds
were built around. A single pure ink has no such part, which is why the contrast
floor stopped mattering. Do not reintroduce a third colour into the PNGs without
re-measuring.

This reads pixels to **measure** them. It does not grade the photograph, and the
rule against inspecting results is untouched.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_config"))
import paths  # noqa: E402

# `claro` and `escuro` name the INK, not the background. The black one goes on a
# light wall; the white one goes on a dark room. Reading these backwards is the
# obvious mistake and the reason this comment is here.
LOGO_DARK_INK = paths.LOGOS_DIR / "logo preto.png"
LOGO_LIGHT_INK = paths.LOGOS_DIR / "logo branco.png"

# Fractions of the photo's LONG EDGE, not its height. Scaling by height would
# give a portrait photo a mark 33% bigger than a landscape one in the same
# gallery. **By HEIGHT, because this lockup is stacked** — taller than it is
# wide, where the old horizontal one was 5:1 the other way. Sizing a stacked mark
# by its width is what makes it tower over the photograph.
LOGO_HEIGHT_PCT = 0.10        # 205x166 px on a 2048px photo
MARGIN_PCT = 0.03             # 61 px in from the top and left
OPACITY = 0.85

MIN_CONTRAST = 4.0            # below this the glow comes on — unreachable with a
                              # pure black/white pair, which ties at 4.58:1
BUSY_STD = 0.18               # background luminance spread that counts as busy —
                              # p79 of 278 real photographs at this mark size
GLOW_RADIUS_PCT = 0.35        # of the logo's height
GLOW_OPACITY = 0.45

# 4:4:4. The mark is the one part of the frame with a hard edge, and chroma
# subsampling drags the photo's colour across it at these sizes.
JPEG_QUALITY = 95
JPEG_SUBSAMPLING = 0

SUFFIX = "_final"
SOURCE_SUFFIX = "_edit"
VARIANTS = ("escuro", "claro")


class MarcaError(Exception):
    """One photo failed. Raised rather than exiting, so a batch can carry on —
    a `sys.exit` inside a worker thread kills nothing and hangs everything."""


def fail(msg: str) -> "None":
    raise MarcaError(msg)


def luminance(rgb: np.ndarray) -> np.ndarray:
    """sRGB 0-255 -> WCAG relative luminance."""
    r = rgb / 255.0
    lin = np.where(r <= 0.04045, r / 12.92, ((r + 0.055) / 1.055) ** 2.4)
    return 0.2126 * lin[..., 0] + 0.7152 * lin[..., 1] + 0.0722 * lin[..., 2]


def contrast(a: float, b: float) -> float:
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


class Logo:
    """One colourway, cropped to its art and measured once."""

    _cache: "dict[tuple[str, float], Logo]" = {}

    def __init__(self, path: Path):
        if not path.exists():
            fail(f"no logo at {paths.rel(path)} — the mark cannot be applied.\n"
                 f"       Expected both files in {paths.rel(paths.LOGOS_DIR)}/")
        with Image.open(path) as im:
            im = im.convert("RGBA")
            box = im.getchannel("A").getbbox()
            if not box:
                fail(f"{path.name} is fully transparent")
            # The exported PNGs carry 52px of transparent padding on the left and
            # 55 on the top, and the two lockups pad differently. Sizing by the
            # canvas would render 5% less art than asked for and put the margin
            # somewhere other than where the constant says.
            self.im = im.crop(box)
        a = np.asarray(self.im).astype(float)
        alpha = a[..., 3] / 255.0
        self.L = float((luminance(a[..., :3]) * alpha).sum() / alpha.sum())
        self.name = "claro" if self.L > 0.5 else "escuro"
        self.path = path

    @classmethod
    def load(cls, path: Path) -> "Logo":
        """Decode and measure once per file, per version of that file.

        Only entries for *this* path are dropped on a miss. Clearing the whole
        cache looked equivalent and was not: `inks()` loads two logos in a row,
        so the second load evicted the first, the next call evicted the second,
        and the cache never held both. Measured, that decoded two 2192x480 PNGs
        on every single call — 41 ms a photo, on every page write.
        """
        key = (str(path), path.stat().st_mtime)
        if key not in cls._cache:
            for stale in [k for k in cls._cache if k[0] == str(path)]:
                del cls._cache[stale]   # this file changed; its old measure is stale
            cls._cache[key] = cls(path)
        return cls._cache[key]


def inks() -> "tuple[Logo, Logo]":
    return Logo.load(LOGO_DARK_INK), Logo.load(LOGO_LIGHT_INK)


def geometry(width: int, height: int, art: Logo) -> "tuple[int, int, int]":
    """(logo width, logo height, margin) in pixels for a photo this size.

    Per-art, not once for the pair: the two exports do not crop to quite the same
    bbox — the white one carries 29 px more above the pin — so their aspects
    differ by 1.8%. Deriving the width from `dark` and painting `light` into it
    stretched the white lockup by that much. Both marks are the same height and
    land at the same corner; the white one is a couple of pixels narrower.
    """
    base = max(width, height)
    lh = round(base * LOGO_HEIGHT_PCT)
    lw = round(lh * art.im.width / art.im.height)
    return lw, lh, round(base * MARGIN_PCT)


def measure(patch: Image.Image, mask: np.ndarray) -> "tuple[float, float]":
    """Background luminance and spread under the art, weighted by its alpha."""
    lum = luminance(np.asarray(patch.convert("RGB")).astype(float))
    total = mask.sum()
    L = float((lum * mask).sum() / total)
    var = float((mask * (lum - L) ** 2).sum() / total)
    return L, var ** 0.5


def render(img: Image.Image, art: Logo, lw: int, lh: int, m: int,
           glow: bool) -> Image.Image:
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    logo = art.im.resize((lw, lh), Image.LANCZOS)

    if glow:
        tone = (255, 255, 255) if art.L < 0.5 else (10, 10, 10)
        blur = logo.getchannel("A").filter(
            ImageFilter.GaussianBlur(max(1.0, lh * GLOW_RADIUS_PCT)))
        blur = blur.point(lambda v: int(v * GLOW_OPACITY))
        halo = Image.new("RGBA", logo.size, tone + (0,))
        halo.putalpha(blur)
        layer.paste(halo, (m, m), halo)

    logo = logo.copy()
    logo.putalpha(logo.getchannel("A").point(lambda v: int(v * OPACITY)))
    layer.paste(logo, (m, m), logo)
    return Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")


def run(edit: Path, out_dir: "Path | None" = None, emit=print,
        variant: "str | None" = None, glow: "bool | None" = None,
        write: bool = True) -> dict:
    """Mark one `_edit.jpg`. Returns the facts, for the job's `marca.md`.

    Always reads the `_edit`, never a `_final` — so marking is idempotent and
    JPEG loss never accumulates, however many times it is redone.

    `write=False` measures and decides without saving anything. That is how the
    gate page gets the numbers it prints beside each photo: measuring is
    deterministic and costs milliseconds, so the page never has to read
    `marca.md` back. No script in this project reads a log to decide anything.
    """
    edit = Path(edit)
    if not edit.exists():
        fail(f"no such photo: {paths.rel(edit)}")
    if SUFFIX in edit.stem:
        fail(f"{edit.name} is already a result — mark the {SOURCE_SUFFIX} instead")

    out_dir = Path(out_dir) if out_dir else edit.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    # Split, not endswith. With `NUM_IMAGES > 1` — which `enhance.py` documents as
    # the prompt-tuning setting — stage 1 writes `NAME_edit_1.jpg`, and an
    # endswith test fell through and produced `NAME_edit_1_final.jpg`. Nothing
    # then found it: `result_of` looks for `NAME_final.jpg`, so every run
    # re-marked the whole job, the review page showed zero photos right after
    # saying it had marked them all, and `--approve` refused forever.
    stem = edit.stem.split(SOURCE_SUFFIX)[0] if SOURCE_SUFFIX in edit.stem \
        else edit.stem

    dark, light = inks()
    with Image.open(edit) as im:
        img = im.convert("RGB")
        W, H = img.size
        # Measured through the black art's alpha, then rendered with whichever ink
        # wins. The two masks differ by 0.5% of coverage, far below anything the
        # decision turns on, and measuring twice would only invite the two answers
        # to disagree about the same patch.
        lw, lh, m = geometry(W, H, dark)
        if m + lw > W or m + lh > H:
            fail(f"{edit.name} is {W}x{H} — too small for a {lw}x{lh} mark")

        mask = np.asarray(dark.im.resize((lw, lh), Image.LANCZOS)
                          ).astype(float)[..., 3] / 255.0
        L, std = measure(img.crop((m, m, m + lw, m + lh)), mask)
        c_dark, c_light = contrast(L, dark.L), contrast(L, light.L)

        if variant in VARIANTS:
            art = dark if variant == "escuro" else light
            best = c_dark if variant == "escuro" else c_light
            why = "forçada"
        else:
            art, best = (dark, c_dark) if c_dark >= c_light else (light, c_light)
            why = "contraste"

        lw, lh, m = geometry(W, H, art)
        auto_glow = best < MIN_CONTRAST or std > BUSY_STD
        use_glow = auto_glow if glow is None else glow

        dest = out_dir / f"{stem}{SUFFIX}.jpg"
        if write:
            render(img, art, lw, lh, m, use_glow).save(
                dest, "JPEG", quality=JPEG_QUALITY,
                subsampling=JPEG_SUBSAMPLING, optimize=True)

    if write:
        emit(f"marcado     {paths.rel(dest)}  {art.name} {best:.2f}:1"
             f"{' +glow' if use_glow else ''}  {lw}x{lh} @ {m}")

    return {
        "stem": stem, "dest": dest, "variant": art.name, "why": why,
        "L": L, "std": std, "c_dark": c_dark, "c_light": c_light,
        "contrast": best, "glow": use_glow,
        "reason": ("contraste < " + str(MIN_CONTRAST) if best < MIN_CONTRAST
                   else "fundo agitado" if std > BUSY_STD else ""),
        "box": (m, m, lw, lh), "size": (W, H),
        "logo": art.path.name,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("photo", help="an _edit.jpg")
    ap.add_argument("--variant", choices=VARIANTS,
                    help="force the ink instead of measuring for it")
    ap.add_argument("--glow", dest="glow", action="store_true", default=None)
    ap.add_argument("--no-glow", dest="glow", action="store_false")
    ap.add_argument("--out", type=Path, help="write somewhere else (for trying "
                                             "settings against an archived photo)")
    args = ap.parse_args()

    try:
        f = run(Path(args.photo), out_dir=args.out, variant=args.variant,
                glow=args.glow)
    except MarcaError as e:
        sys.exit(f"error: {e}")
    except Exception as e:                  # noqa: BLE001 — a clean message beats a traceback
        sys.exit(f"error: {type(e).__name__}: {e}")

    print(f"fundo       L {f['L']:.3f} · desvio {f['std']:.3f}")
    print(f"contraste   preto {f['c_dark']:.2f}:1 · branco {f['c_light']:.2f}:1"
          f"  -> {f['variant']} ({f['why']})")
    if f["glow"]:
        print(f"glow        ligado — {f['reason'] or 'forçado'}")


if __name__ == "__main__":
    main()
