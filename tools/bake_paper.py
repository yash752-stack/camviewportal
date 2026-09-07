"""Bake the report stock and the section photographs into flat JPEGs.

    python tools/bake_paper.py

Why: headless Chromium on a small server (Render's free tier is a tenth of a
CPU) took minutes to print a report when every page carried a semi-transparent
grain layer, a vector gear at 7% opacity and a 2400 px photograph to composite
at print resolution. A flat, opaque JPEG is painted once and costs nothing, so
the grain, the mottle and the gear are baked into `assets/paper.jpg` here, and
each photograph is baked as its navy duotone (with the white gear already on
it) under `assets/photos/baked/`. `iv_paper` prefers these files and falls back
to computing them only when they are missing.

Run this again after changing a photograph, the gear or the paper textures,
and commit the results. Needs Pillow and PyMuPDF (the latter only to
rasterise the gear SVG).
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageEnhance, ImageOps

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
sys.path.insert(0, str(ROOT / "backend"))

PAPER = (253, 253, 254)
NAVY = (59, 88, 119)
W_MM, H_MM = 297.0, 210.0
PX_PER_MM = 3.0                     # 891 x 630 px: enough for grain at A4


def gear_rgba(size_px: int) -> Image.Image:
    import pymupdf
    doc = pymupdf.open(str(ASSETS / "iv-gear-watermark.svg"))
    pg = doc[0]
    zoom = size_px / pg.rect.width
    pix = pg.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=True)
    return Image.frombytes("RGBA", [pix.width, pix.height], pix.samples)


def tint_gear(g: Image.Image, rgb: tuple, alpha: float) -> Image.Image:
    mask = g.split()[3].point(lambda a: int(a * alpha))
    out = Image.new("RGBA", g.size, rgb + (0,))
    out.putalpha(mask)
    return out


def bake_paper() -> Path:
    W, H = int(W_MM * PX_PER_MM), int(H_MM * PX_PER_MM)
    base = Image.new("RGB", (W, H), PAPER)
    fibre = Image.open(ASSETS / "paper-fibre.png").convert("RGBA")
    mottle = Image.open(ASSETS / "paper-mottle.png").convert("RGBA").resize((W, H))
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    tile = int(34 * PX_PER_MM)
    fibre = fibre.resize((tile, tile))
    for y in range(0, H, tile):
        for x in range(0, W, tile):
            layer.alpha_composite(fibre, (x, y))
    layer.alpha_composite(mottle)
    layer.putalpha(layer.split()[3].point(lambda a: int(a * 0.42)))
    out = Image.alpha_composite(base.convert("RGBA"), layer)
    # the gear, navy at 7%, bled off the bottom-right corner (150 mm wide, 28/24 mm off the edge)
    g = tint_gear(gear_rgba(int(150 * PX_PER_MM)), NAVY, 0.07)
    out.alpha_composite(g, (W - g.width + int(28 * PX_PER_MM), H - g.height + int(24 * PX_PER_MM)))
    p = ASSETS / "paper.jpg"
    out.convert("RGB").save(p, "JPEG", quality=88, optimize=True)
    return p


def duotone(path: Path, maxpx: int = 1400) -> Image.Image:
    im = Image.open(path).convert("L")
    im.thumbnail((maxpx, maxpx))
    im = ImageEnhance.Contrast(im).enhance(1.15)
    im = ImageOps.colorize(im, (24, 52, 79), (221, 229, 235))
    navy = Image.new("RGB", im.size, NAVY)
    im = Image.blend(im, ImageChops.multiply(im, navy), 0.40)
    try:
        import numpy as np
        a = np.asarray(im).astype("int16")
        a = a + np.random.default_rng(7).integers(-9, 10, size=a.shape[:2])[:, :, None]
        im = Image.fromarray(a.clip(0, 255).astype("uint8"))
    except Exception:
        pass
    return im


def bake_photos() -> list[Path]:
    out_dir = ASSETS / "photos" / "baked"
    out_dir.mkdir(parents=True, exist_ok=True)
    gear_src = gear_rgba(900)
    done = []
    for src in sorted((ASSETS / "photos").glob("*.jpg")):
        im = duotone(src).convert("RGBA")
        if src.stem != "cover":
            # section pages: the white gear at 22%, bled off the bottom-right, as on the sheet
            w, h = im.size
            k = w / W_MM                         # px per mm of the page the photo fills
            g = tint_gear(gear_src.resize((int(110 * k),) * 2), (255, 255, 255), 0.22)
            im.alpha_composite(g, (w - g.width + int(22 * k), h - g.height + int(16 * k)))
        p = out_dir / src.name
        im.convert("RGB").save(p, "JPEG", quality=76, optimize=True)
        done.append(p)
    return done


if __name__ == "__main__":
    p = bake_paper()
    print(p.name, p.stat().st_size // 1024, "KB")
    for q in bake_photos():
        print(q.relative_to(ASSETS), q.stat().st_size // 1024, "KB")
