#!/usr/bin/env python3
"""Turn downloaded photos into the category tile images.

Usage:
    python tools/prepare_category_photos.py ~/Downloads/category-photos

Put one photo per category in that folder, named by slug (footwear.jpg,
skincare.webp, beverages.png ...). The script centre-crops each to a square,
resizes to 480x480 and saves frontend/static/img/categories/<slug>.png.
Categories without a photo keep their current image. Needs: pip install pillow
"""
import sys
from pathlib import Path
from PIL import Image, ImageOps

SLUGS = """mobile-accessories computers-office audio-wearables home-entertainment
mens-wear womens-wear footwear bags-accessories furniture kitchen-dining home-decor
bedding-bath cleaning-supplies skincare haircare makeup-cosmetics personal-care
packaged-foods beverages household-supplies fitness-exercise outdoor-gear
sports-equipment baby-care toys-games auto-accessories tools-home-improvement""".split()
EXTS = (".jpg", ".jpeg", ".png", ".webp")
OUT = Path(__file__).resolve().parent.parent / "frontend" / "static" / "img" / "categories"

def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    src = Path(sys.argv[1]).expanduser()
    done, missing = [], []
    for slug in SLUGS:
        match = next((src / f"{slug}{e}" for e in EXTS if (src / f"{slug}{e}").exists()), None)
        if not match:
            missing.append(slug); continue
        im = ImageOps.exif_transpose(Image.open(match)).convert("RGB")
        im = ImageOps.fit(im, (480, 480), Image.LANCZOS, centering=(0.5, 0.5))
        im.save(OUT / f"{slug}.png", optimize=True)
        done.append(slug)
    print(f"Updated {len(done)} images in {OUT}")
    if missing:
        print("No photo found for (kept current image):", ", ".join(missing))

if __name__ == "__main__":
    main()
