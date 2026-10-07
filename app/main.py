import os
import secrets
from pathlib import Path

import cv2
import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

try:  # optional: read GOOGLE_CLIENT_ID / SECRET_KEY from a local .env file
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from google.auth.transport import requests as g_requests
from google.oauth2 import id_token

from .sketch import STYLES, load_image, render

STATIC = Path(__file__).resolve().parent.parent / "static"
MAX_BYTES = 12 * 1024 * 1024
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "").strip()

SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY:
    SECRET_KEY = secrets.token_urlsafe(32)
    print("WARNING: SECRET_KEY is not set - logins will reset every time the server restarts.")

app = FastAPI(title="Pencil Sketch Studio", docs_url=None, redoc_url=None)
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    session_cookie="graphite_session",
    max_age=60 * 60 * 24 * 30,                 # stay logged in for 30 days
    same_site="lax",
    https_only=bool(os.environ.get("RENDER")),  # Secure cookie on Render (https), plain on localhost
)

_G_REQUEST = g_requests.Request()


class NoCacheStatic(StaticFiles):
    """Static files that the browser must re-check every time (fast 304 if unchanged),
    so a new deploy / edited file is never hidden behind a stale cached copy."""

    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        resp.headers["Cache-Control"] = "no-cache"
        return resp


def _make_favicon() -> bytes:
    """Tiny pencil icon drawn at startup, so /favicon.ico never 404s."""
    img = np.zeros((64, 64, 4), np.uint8)
    img[:] = (18, 23, 27, 255)
    body = np.array([[34, 8], [43, 10], [33, 50], [24, 48]], np.int32)
    tip = np.array([[24, 48], [33, 50], [27, 58]], np.int32)
    cv2.fillPoly(img, [body], (106, 184, 232, 255))
    cv2.fillPoly(img, [tip], (180, 205, 230, 255))
    ok, buf = cv2.imencode(".png", img)
    return buf.tobytes()


FAVICON = _make_favicon()


def _pct(v: float) -> float:
    return max(0.0, min(100.0, v)) / 100


def _json(data: dict) -> JSONResponse:
    return JSONResponse(data, headers={"Cache-Control": "no-store"})


@app.api_route("/health", methods=["GET", "HEAD"])   # HEAD too: uptime monitors often use it
def health():
    return {"ok": True}


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return Response(FAVICON, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


# ---------------- auth (Sign in with Google) ----------------
class GoogleToken(BaseModel):
    credential: str


@app.get("/api/config")
def config():
    return _json({"google_client_id": GOOGLE_CLIENT_ID})


@app.get("/api/me")
def me(request: Request):
    return _json({"user": request.session.get("user")})


@app.post("/api/auth/google")
def auth_google(body: GoogleToken, request: Request):
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(503, "Google login is not configured on the server")
    try:
        info = id_token.verify_oauth2_token(
            body.credential, _G_REQUEST, GOOGLE_CLIENT_ID, clock_skew_in_seconds=10
        )
    except ValueError:
        raise HTTPException(401, "Google sign-in could not be verified. Please try again.")
    if not info.get("email_verified", False):
        raise HTTPException(401, "Your Google email is not verified")
    user = {
        "sub": info["sub"],
        "name": info.get("name") or info.get("email"),
        "email": info["email"],
        "picture": info.get("picture", ""),
    }
    request.session["user"] = user
    return _json({"user": user})


@app.post("/api/auth/logout")
def logout(request: Request):
    request.session.clear()
    return _json({"ok": True})


# ---------------- sketch API (login required) ----------------
@app.post("/api/sketch")
def sketch(
    request: Request,
    file: UploadFile = File(...),
    style: str = Form("graphite"),
    intensity: float = Form(50),
    detail: float = Form(50),
    paper: bool = Form(True),
):
    if not request.session.get("user"):
        raise HTTPException(401, "Please log in to create a sketch")
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


app.mount("/", NoCacheStatic(directory=STATIC, html=True), name="static")