from pathlib import Path

import cv2
import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from .sketch import STYLES, load_image, render

STATIC = Path(__file__).resolve().parent.parent / "static"
MAX_BYTES = 12 * 1024 * 1024

app = FastAPI(title="Pencil Sketch Studio", docs_url=None, redoc_url=None)


def _make_favicon() -> bytes:
    """Tiny pencil icon drawn at startup, so /favicon.ico never 404s."""
    img = np.zeros((64, 64, 4), np.uint8)
    img[:] = (18, 23, 27, 255)                                   # dark brown background
    body = np.array([[34, 8], [43, 10], [33, 50], [24, 48]], np.int32)
    tip = np.array([[24, 48], [33, 50], [27, 58]], np.int32)
    cv2.fillPoly(img, [body], (106, 184, 232, 255))             # amber pencil (BGRA)
    cv2.fillPoly(img, [tip], (180, 205, 230, 255))              # wood tip
    ok, buf = cv2.imencode(".png", img)
    return buf.tobytes()


FAVICON = _make_favicon()


def _pct(v: float) -> float:
    return max(0.0, min(100.0, v)) / 100


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return Response(FAVICON, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


@app.post("/api/sketch")
def sketch(
    file: UploadFile = File(...),
    style: str = Form("graphite"),
    intensity: float = Form(50),
    detail: float = Form(50),
    paper: bool = Form(True),
):
    if style not in STYLES:
        raise HTTPException(400, "Unknown style")
    data = file.file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "Image too large (max 12 MB)")
    try:
        img = load_image(data)
    except Exception:
        raise HTTPException(400, "Could not read this image")
    out = render(img, style, _pct(intensity), _pct(detail), paper)
    ok, buf = cv2.imencode(".png", out)
    if not ok:
        raise HTTPException(500, "Encoding failed")
    return Response(buf.tobytes(), media_type="image/png", headers={"Cache-Control": "no-store"})


app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")