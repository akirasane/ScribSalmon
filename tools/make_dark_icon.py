r"""Build the dark variant of the salmon app icon from the light (original) artwork, plus sized PNGs and .ico files.

    .venv\Scripts\python tools\make_dark_icon.py

Needs opencv-python-headless, numpy and pillow (dev only: pip install -r requirements-dev.txt).
Input : assets/source/salmon-icon-light.png  (500x500 RGBA, transparent outside the rounded tile)
Output: assets/icon-salmon-{light,dark}-{512,256}.png, assets/icon-salmon-{light,dark}.ico, assets/icon-salmon-preview.png

How the dark version is made: the fish is cut out (GrabCut seeded with a rough outline, plus two hand-measured regions where
the glossy rim confuses it), the pink cloudy tile is recoloured to a deep warm glass using its own luminance (so the cloud
texture and the rim light survive), and the fish is composited back with its original pixels (edge colours re-extended from the
interior so no pink halo remains). The hand-measured regions belong to THIS artwork; a new source image needs new ones.
"""
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
SRC = ASSETS / "source" / "salmon-icon-light.png"
SIZES = [16, 24, 32, 48, 64, 128, 256]

# rough fish outline (generous) used to seed GrabCut
FISH_HULL = [(52, 258), (92, 252), (146, 282), (156, 232), (166, 168), (205, 128), (250, 130), (290, 138), (335, 144),
             (385, 168), (408, 208), (406, 255), (386, 290), (334, 328), (304, 336), (304, 376), (250, 372), (232, 350),
             (214, 340), (168, 336), (164, 376), (128, 402), (92, 398), (98, 330), (114, 300), (78, 290)]
# regions measured on the artwork, inset ~2 px inside the visible rim, forced into the fish matte
FISH_CAPS = [
    [(268, 152), (284, 144), (304, 140), (326, 139), (348, 143), (368, 152), (384, 166), (393, 184), (396, 206), (300, 206), (268, 206)],
    [(67, 266), (77, 262), (88, 259), (102, 261), (116, 268), (129, 279), (140, 290), (150, 302), (122, 306), (96, 304), (84, 294), (77, 283), (72, 274)],
    [(67, 266), (69, 276), (74, 290), (84, 304), (97, 319), (150, 322), (150, 302), (120, 296), (90, 290)],
]
DARK, MID, RIM = "#1a0e0b", "#3a201a", "#7a463a"        # tile palette (matches the app's dark salmon theme)
GLOW = (0.18, 0.30, 0.52)                                # BGR warm glow around the fish


def _hex_bgr(s: str) -> np.ndarray:
    s = s.lstrip("#")
    return np.array([int(s[4:6], 16), int(s[2:4], 16), int(s[0:2], 16)], np.float32) / 255


def fish_matte(bgr8: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    """Soft fish matte (float 0..1)."""
    h, w = alpha.shape
    rough = np.zeros((h, w), np.uint8)
    cv2.fillPoly(rough, [np.array(FISH_HULL, np.int32)], 255)
    mask = np.full((h, w), cv2.GC_BGD, np.uint8)
    mask[(cv2.dilate(rough, np.ones((21, 21), np.uint8)) > 0) & (alpha > 128)] = cv2.GC_PR_BGD
    mask[(rough > 0) & (alpha > 128)] = cv2.GC_PR_FGD
    mask[cv2.erode(rough, np.ones((45, 45), np.uint8)) > 0] = cv2.GC_FGD
    cv2.grabCut(bgr8, mask, None, np.zeros((1, 65)), np.zeros((1, 65)), 12, cv2.GC_INIT_WITH_MASK)
    fish = ((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD)).astype(np.uint8) * 255
    fish[alpha <= 128] = 0
    n, lab, stats, _ = cv2.connectedComponentsWithStats((fish > 0).astype(np.uint8))
    fish = ((lab == 1 + np.argmax(stats[1:, cv2.CC_STAT_AREA])) * 255).astype(np.uint8)
    for cap in FISH_CAPS:
        cv2.fillPoly(fish, [np.array(cap, np.int32)], 255)
    fish[alpha <= 128] = 0
    s = 4  # smooth the contour at 4x, then back down for an antialiased edge
    up = cv2.resize(fish, (w * s, h * s), interpolation=cv2.INTER_CUBIC).astype(np.float32) / 255
    up = (cv2.GaussianBlur(up, (0, 0), s * 1.9) > 0.5).astype(np.float32)
    return cv2.resize(cv2.GaussianBlur(up, (0, 0), s * 0.5), (w, h), interpolation=cv2.INTER_AREA)


def make_dark(light_rgba: np.ndarray) -> np.ndarray:
    """light_rgba: uint8 BGRA (cv2 order). Returns float32 BGRA 0..1."""
    im = light_rgba.astype(np.float32) / 255
    bgr, a = im[:, :, :3], im[:, :, 3]
    h, w = a.shape
    bgr8 = light_rgba[:, :, :3].copy()
    fk = fish_matte(bgr8, light_rgba[:, :, 3])
    fish_bin = (fk > 0.5).astype(np.uint8)

    # tile: remove the fish (inpaint), then map the remaining luminance onto the dark palette
    hole = cv2.dilate(fish_bin * 255, np.ones((13, 13), np.uint8))
    bg_only = cv2.inpaint(bgr8, hole, 9, cv2.INPAINT_TELEA)
    lum = cv2.cvtColor(bg_only, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255
    inside = a > 0.5
    lo, hi = np.percentile(lum[inside], 2), np.percentile(lum[inside], 99.5)
    t = np.clip((lum - lo) / (hi - lo), 0, 1)[..., None]
    dark, mid, rim = _hex_bgr(DARK), _hex_bgr(MID), _hex_bgr(RIM)
    col = np.where(t < 0.7, dark + (mid - dark) * (t / 0.7), mid + (rim - mid) * ((t - 0.7) / 0.3))
    col = col * (1.12 - 0.22 * np.linspace(0, 1, h)[:, None, None])           # slightly lighter at the top, like glass
    col = np.clip(col + cv2.GaussianBlur(fk, (0, 0), 16)[..., None] * np.array(GLOW, np.float32) * 0.5, 0, 1)

    # fish: original pixels; re-extend interior colours over a thin edge ring so no pink halo is left
    core = cv2.erode(fish_bin, np.ones((3, 3), np.uint8), iterations=2)
    ring = (cv2.dilate(fish_bin, np.ones((7, 7), np.uint8)) > 0) & (core == 0)
    fish_col = cv2.inpaint(bgr8, (ring * 255).astype(np.uint8), 4, cv2.INPAINT_TELEA).astype(np.float32) / 255
    fish_col = np.where((core > 0)[..., None], bgr, fish_col)
    fa = cv2.GaussianBlur(cv2.erode(fish_bin, np.ones((3, 3), np.uint8)).astype(np.float32), (0, 0), 0.8)[..., None]
    out = np.clip(fish_col * 1.02, 0, 1) * fa + col * (1 - fa)
    return np.dstack([out, a])


def to_pil(bgra: np.ndarray) -> Image.Image:
    u8 = np.clip(bgra * 255 + 0.5, 0, 255).astype(np.uint8) if bgra.dtype != np.uint8 else bgra
    return Image.fromarray(cv2.cvtColor(u8, cv2.COLOR_BGRA2RGBA), "RGBA")


def write_set(img: Image.Image, name: str) -> None:
    for s in (512, 256):
        img.resize((s, s), Image.LANCZOS).save(ASSETS / f"icon-salmon-{name}-{s}.png")
    img.save(ASSETS / f"icon-salmon-{name}.ico", sizes=[(s, s) for s in SIZES])


def preview(light: Image.Image, dark: Image.Image) -> None:
    W = 420
    sheet = Image.new("RGBA", (W * 3 + 40, W + 300), (30, 30, 30, 255))
    for i, (img, bg) in enumerate(((light, (245, 245, 245)), (dark, (245, 245, 245)), (dark, (13, 9, 7)))):
        tile = Image.new("RGBA", (W, W), bg + (255,))
        tile.alpha_composite(img.resize((W - 20, W - 20), Image.LANCZOS), (10, 10))
        sheet.paste(tile, (i * (W + 20), 0))
    x = 10
    for img in (light, dark):
        for s in (16, 24, 32, 48, 64):
            small = img.resize((s, s), Image.LANCZOS)
            sheet.alpha_composite(small.resize((s * 2, s * 2), Image.NEAREST), (x, W + 20 + (0 if img is light else 150)))
            x += s * 2 + 10
        x = 10
    sheet.convert("RGB").save(ASSETS / "icon-salmon-preview.png")


def main() -> None:
    src = cv2.imread(str(SRC), cv2.IMREAD_UNCHANGED)
    if src is None or src.shape[2] != 4:
        raise SystemExit(f"cannot read an RGBA image at {SRC}")
    light = to_pil(src)
    dark = to_pil(make_dark(src))
    write_set(light, "light")
    write_set(dark, "dark")
    preview(light, dark)
    print("wrote", ", ".join(sorted(p.name for p in ASSETS.glob("icon-salmon-*"))))


if __name__ == "__main__":
    main()
