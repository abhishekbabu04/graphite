"""Photo -> realistic pencil sketch. Pure OpenCV + NumPy, no ML weights."""
import io
import os

import cv2
import numpy as np
from PIL import Image, ImageOps

Image.MAX_IMAGE_PIXELS = 60_000_000  # decompression-bomb guard
MAX_SIDE = int(os.environ.get("MAX_SIDE", 2000))  # set MAX_SIDE=1200 on low-RAM hosts (e.g. Render free)
STYLES = ("graphite", "charcoal", "colored", "crosshatch")
PAPER = np.array([0.90, 0.94, 0.97], np.float32)  # warm off-white (BGR)


def load_image(data: bytes) -> np.ndarray:
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    img.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    return cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2BGR)


def _blur(a, sigma):
    return cv2.GaussianBlur(a, (0, 0), max(float(sigma), 0.3))


def _line_ink(gray, sigma):
    """Colour-dodge sketch: gray / blur(gray). Returns ink (dark = 1)."""
    return 1.0 - np.clip(gray / (_blur(gray, sigma) + 0.01), 0, 1)


def _tooth(shape, angle, length, seed):
    """Directional paper-grain texture, zero mean / unit variance."""
    n = np.random.default_rng(seed).random(shape, dtype=np.float32)
    length = max(5, int(length)) | 1
    k = np.zeros((length, length), np.float32)
    k[length // 2, :] = 1
    m = cv2.getRotationMatrix2D((length / 2 - 0.5, length / 2 - 0.5), angle, 1)
    k = cv2.warpAffine(k, m, (length, length))
    t = cv2.filter2D(n, -1, k / k.sum())
    return (t - t.mean()) / (t.std() + 1e-6)


def _hatch(gray, side, intensity, detail):
    h, w = gray.shape
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    tone = np.clip(_blur(1 - gray, side * 0.002 + 0.5) * (0.8 + 0.6 * intensity), 0, 1)
    sp = max(3.0, side / (150 + 150 * detail))
    warp = _blur(np.random.default_rng(3).standard_normal((h, w)).astype(np.float32), side * 0.01)
    warp = warp / (warp.std() + 1e-6) * sp * 0.35  # hand-drawn wobble
    ink = np.zeros_like(gray)
    for angle, th in ((45, 0.18), (-45, 0.38), (0, 0.58), (90, 0.76)):
        r = np.deg2rad(angle)
        u = xx * np.cos(r) + yy * np.sin(r) + warp
        line = np.clip((np.cos(2 * np.pi * u / sp) - 0.35) * 3, 0, 1)
        ink = np.maximum(ink, line * np.clip((tone - th) / 0.12, 0, 1))
    edges = np.clip(_line_ink(gray, side * 0.005) * 3, 0, 1) * 0.85
    return np.clip(np.maximum(ink * 0.9, edges) + tone * 0.12, 0, 1)


def render(img, style="graphite", intensity=0.5, detail=0.5, paper=True):
    h, w = img.shape[:2]
    side = max(h, w)
    f = img.astype(np.float32) / 255
    gray = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
    gray = np.clip(gray, 0.0, 1.0)  # float rounding can push values just outside 0..1
    charcoal = style == "charcoal"

    if style == "crosshatch":
        ink = _hatch(gray, side, intensity, detail)
    else:
        sigma = side * (0.014 - 0.010 * detail)
        lines = 0.55 * _line_ink(gray, sigma) + 0.45 * _line_ink(gray, sigma * 0.35)
        lines = np.clip(lines * (1.6 + 2.0 * intensity), 0, 1) ** 0.9
        tone_w = (0.75 if charcoal else 0.25 + 0.5 * intensity) * (0.7 if style == "colored" else 1)
        # clip BEFORE the power: a tiny negative value ** 1.5 would give NaN
        tone = np.clip(1.0 - _blur(gray, sigma * 0.5), 0.0, 1.0) ** 1.5
        ink = np.clip(lines + tone * tone_w, 0, 1)
        if charcoal:  # smudge + soft bloom
            ink = np.clip(0.8 * _blur(ink, side * 0.0015) + 0.35 * _blur(ink, side * 0.012), 0, 1)

    t = 0.6 * _tooth((h, w), 45, side // 150, 1) + 0.4 * _tooth((h, w), -30, side // 200, 2)
    ink = np.clip(ink * (1 + (0.6 if charcoal else 0.35) * t), 0, 1)

    if paper:
        rng = np.random.default_rng(5)
        fib = _blur(rng.standard_normal((h, w)).astype(np.float32), 1.2)
        base = PAPER * (1 + 0.018 * fib / (fib.std() + 1e-6))[..., None]
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        r2 = ((xx / w - 0.5) ** 2 + (yy / h - 0.5) ** 2) * 2
        base = base * (1 - 0.10 * r2)[..., None]
    else:
        base = np.ones((h, w, 3), np.float32)

    lead = np.array([0.09] * 3 if charcoal else [0.21, 0.20, 0.20], np.float32)
    out = base * (1 - ink[..., None]) + lead * ink[..., None]

    if style == "colored":
        col = _blur(f, side * 0.004)
        hsv = cv2.cvtColor(col, cv2.COLOR_BGR2HSV)
        sat = np.clip(hsv[..., 1] * 1.6, 0, 1)
        hsv[..., 1] = np.clip(hsv[..., 1] * 1.25, 0, 1)
        hsv[..., 2] = 1
        hue = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
        cov = np.clip(0.6 + 0.3 * t, 0, 1) * sat * (0.45 + 0.4 * intensity)
        out = out * (1 - cov[..., None] + cov[..., None] * hue)

    out = np.nan_to_num(out, nan=1.0, posinf=1.0, neginf=0.0)  # safety net: never cast NaN to uint8
    return (np.clip(out, 0, 1) * 255).astype(np.uint8)