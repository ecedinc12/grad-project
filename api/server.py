"""
FastAPI backend — RunPod GPU container'ında çalışır.

Auth:
  POST /auth/register   → yeni kullanıcı kaydı, JWT dön
  POST /auth/login      → giriş, JWT dön

Kullanıcı ayarları:
  GET  /user/nim-key    → NIM key kayıtlı mı? ({"saved": bool})
  PUT  /user/nim-key    → NIM key'i şifreli kaydet

Pipeline:
  POST /run             → pipeline'ı kuyruğa al, jobId dön (202)
  GET  /status/{jobId} → iş durumu ve ilerleme

Medya:
  GET  /video, /annotated-video, /archive, /frames, /frame/{name}
"""
from __future__ import annotations

import asyncio
import base64
import glob
import hashlib
import json
import os
import random
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import jwt as pyjwt
from cryptography.fernet import Fernet
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUN_SCRIPT   = PROJECT_ROOT / "scripts" / "run_pipeline.sh"
DATASET_DIR  = Path("/tmp/dataset")
DATA_DIR     = PROJECT_ROOT / "data"
USERS_FILE   = DATA_DIR / "users.json"

DROPLET_API_KEY  = os.environ.get("DROPLET_API_KEY", "")
SECRET_KEY       = os.environ.get("SECRET_KEY", "")
if not SECRET_KEY:
    import secrets as _sec
    SECRET_KEY = _sec.token_hex(32)
    print("[WARN] SECRET_KEY env var not set — using ephemeral key. Tokens will be invalid after restart.")

JWT_ALGORITHM    = "HS256"
JWT_EXPIRE_DAYS  = 30
ADMIN_EMAIL      = "admin@visionforge.tech"
ADMIN_PW_HASH    = hashlib.sha256(b"admin123").hexdigest()

# ---------------------------------------------------------------------------
# App & CORS
# ---------------------------------------------------------------------------
app = FastAPI(title="VisionForge Pipeline API", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://www.visionforge.tech",
        "https://visionforge.tech",
        "http://localhost:5173",
        "http://localhost:4173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# User store helpers
# ---------------------------------------------------------------------------
def _load_users() -> dict:
    if not USERS_FILE.exists():
        return {}
    try:
        return json.loads(USERS_FILE.read_text())
    except Exception:
        return {}


def _save_users(users: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    USERS_FILE.write_text(json.dumps(users, indent=2))


def _hash_pw(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------
def _fernet() -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(SECRET_KEY.encode()).digest())
    return Fernet(key)


def _create_token(user_id: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(days=JWT_EXPIRE_DAYS)
    return pyjwt.encode({"sub": user_id, "exp": exp}, SECRET_KEY, algorithm=JWT_ALGORITHM)


def _decode_token(token: str) -> str | None:
    try:
        payload = pyjwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return payload["sub"]
    except Exception:
        return None


def _user_id_from_request(request: Request) -> str | None:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    return _decode_token(auth[7:])


# ---------------------------------------------------------------------------
# API key guard (DROPLET_API_KEY or valid JWT)
# ---------------------------------------------------------------------------
def _verify_key(request: Request) -> None:
    if not DROPLET_API_KEY:
        return  # auth disabled when env var not set
    auth = request.headers.get("Authorization", "")
    if auth == f"Bearer {DROPLET_API_KEY}":
        return
    if auth.startswith("Bearer ") and _decode_token(auth[7:]):
        return
    raise HTTPException(status_code=401, detail="Unauthorized")


# ---------------------------------------------------------------------------
# NIM key helpers
# ---------------------------------------------------------------------------
def _get_stored_nim_key(user_id: str) -> str | None:
    if user_id == "admin":
        return None  # admin always supplies key via header
    users = _load_users()
    user = next((u for u in users.values() if u["id"] == user_id), None)
    if not user or not user.get("nim_key"):
        return None
    try:
        return _fernet().decrypt(user["nim_key"].encode()).decode()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Job store  (in-memory)
# ---------------------------------------------------------------------------
_jobs: dict[str, dict] = {}

_state: dict = {
    "running": False, "job_id": None, "progress": 0,
    "exit_code": None, "started_at": None,
}


# ---------------------------------------------------------------------------
# Misc helpers
# ---------------------------------------------------------------------------
def _rgb_frames(limit: int = 12) -> list[str]:
    paths = sorted(glob.glob(str(DATASET_DIR / "rgb_*.png")))
    return paths if len(paths) <= limit else sorted(random.sample(paths, limit))


def _newest_archive() -> Optional[Path]:
    archives = sorted(
        glob.glob(str(PROJECT_ROOT / "dataset_*.tar.gz")),
        key=lambda p: os.path.getmtime(p),
    )
    return Path(archives[-1]) if archives else None


def _parse_progress(line: str) -> Optional[int]:
    m = re.search(r"\[(\d+)/(\d+)\]", line)
    return round(int(m.group(1)) / int(m.group(2)) * 100) if m else None


_SIGNAL_RE = re.compile(
    r"\[\d+/\d+\]|"
    r"\[LLM\]|\[PROGRESS\]|\[ERROR\]|\[FATAL\]|\[OK\]|\[WARN(?:ING)?\]|\[INFO\]|"
    r"^={4}|Simulation App|app ready|Starting Generation Pipeline|Prompt:|"
    r"IRA core imports|Warning: ffmpeg|rm: cannot"
)


def _is_signal(line: str) -> bool:
    return bool(line.strip() and _SIGNAL_RE.search(line))


def _build_env(nim_api_key: str) -> dict:
    return {
        **os.environ,
        "PYTHONUNBUFFERED": "1",
        "ACCEPT_EULA": os.environ.get("ACCEPT_EULA", "Y"),
        "NIM_API_KEY": nim_api_key,
    }


# ---------------------------------------------------------------------------
# Routes — Auth
# ---------------------------------------------------------------------------
class AuthRequest(BaseModel):
    email: str
    password: str


@app.post("/auth/register", status_code=201)
async def register(req: AuthRequest):
    if req.email == ADMIN_EMAIL:
        raise HTTPException(409, "Email already registered")
    users = _load_users()
    if req.email in users:
        raise HTTPException(409, "Email already registered")
    uid = str(uuid.uuid4())
    users[req.email] = {
        "id": uid, "email": req.email,
        "password_hash": _hash_pw(req.password), "nim_key": None,
    }
    _save_users(users)
    return {"token": _create_token(uid), "user": {"id": uid, "email": req.email}}


@app.post("/auth/login")
async def login_user(req: AuthRequest):
    if req.email == ADMIN_EMAIL and _hash_pw(req.password) == ADMIN_PW_HASH:
        return {"token": _create_token("admin"), "user": {"id": "admin", "email": ADMIN_EMAIL}}
    users = _load_users()
    user = users.get(req.email)
    if not user or user["password_hash"] != _hash_pw(req.password):
        raise HTTPException(401, "Invalid credentials")
    return {"token": _create_token(user["id"]), "user": {"id": user["id"], "email": user["email"]}}


# ---------------------------------------------------------------------------
# Routes — User NIM key
# ---------------------------------------------------------------------------
@app.get("/user/nim-key")
async def nim_key_status(request: Request):
    uid = _user_id_from_request(request)
    if not uid:
        raise HTTPException(401, "Unauthorized")
    if uid == "admin":
        return {"saved": False}
    users = _load_users()
    user = next((u for u in users.values() if u["id"] == uid), None)
    return {"saved": bool(user and user.get("nim_key"))}


class NimKeyRequest(BaseModel):
    nimKey: str


@app.put("/user/nim-key")
async def save_nim_key(req: NimKeyRequest, request: Request):
    uid = _user_id_from_request(request)
    if not uid:
        raise HTTPException(401, "Unauthorized")
    if not req.nimKey.strip():
        raise HTTPException(422, "nimKey is required")
    users = _load_users()
    user = next((u for u in users.values() if u["id"] == uid), None)
    if not user:
        raise HTTPException(404, "User not found")
    user["nim_key"] = _fernet().encrypt(req.nimKey.strip().encode()).decode()
    _save_users(users)
    return {"saved": True}


# ---------------------------------------------------------------------------
# Background task for /run
# ---------------------------------------------------------------------------
async def _run_job(job_id: str, prompt: str, nim_api_key: str) -> None:
    _jobs[job_id].update(status="running", message="Starting pipeline...")
    env = _build_env(nim_api_key)
    try:
        proc = await asyncio.create_subprocess_exec(
            "/bin/bash", str(RUN_SCRIPT), prompt,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(PROJECT_ROOT), env=env,
        )
        async for raw in proc.stdout:  # type: ignore[union-attr]
            line = raw.decode("utf-8", errors="replace").rstrip()
            progress = _parse_progress(line)
            if progress is not None:
                _jobs[job_id]["progress"] = progress
            if not _is_signal(line):
                continue
            _jobs[job_id]["message"] = line[:200]
            _jobs[job_id]["logs"].append(line[:200])
            if len(_jobs[job_id]["logs"]) > 300:
                _jobs[job_id]["logs"] = _jobs[job_id]["logs"][-300:]
        await proc.wait()
        if proc.returncode == 0:
            archive = _newest_archive()
            _jobs[job_id].update(
                status="completed", progress=100,
                message="Dataset ready", resultUrl="/archive" if archive else None,
            )
        else:
            _jobs[job_id].update(status="failed", message=f"Pipeline exited with code {proc.returncode}")
    except Exception as exc:
        _jobs[job_id].update(status="failed", message=str(exc))


# ---------------------------------------------------------------------------
# Routes — Pipeline
# ---------------------------------------------------------------------------
class RunRequest(BaseModel):
    prompt: str
    preset: str = ""
    frames: int = 100
    labels: list[str] = []


@app.post("/run", status_code=202)
async def run(req: RunRequest, request: Request, background_tasks: BackgroundTasks):
    _verify_key(request)

    # NIM key: prefer explicit header, fall back to stored user key
    nim_api_key = request.headers.get("x-nim-api-key", "").strip()
    if not nim_api_key:
        uid = _user_id_from_request(request)
        if uid:
            nim_api_key = _get_stored_nim_key(uid) or ""

    if not nim_api_key:
        raise HTTPException(400, "NIM API key missing — save it in Settings or pass X-NIM-API-Key header")

    if not req.prompt.strip():
        raise HTTPException(422, "Prompt cannot be empty")

    job_id = str(uuid.uuid4())
    _jobs[job_id] = {"status": "queued", "progress": 0, "message": "Job queued", "resultUrl": None, "logs": []}
    background_tasks.add_task(_run_job, job_id, req.prompt.strip(), nim_api_key)
    return {"jobId": job_id, "status": "queued"}


@app.get("/status/{job_id}")
async def job_status(job_id: str, request: Request):
    _verify_key(request)
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return {"jobId": job_id, **job}


# ---------------------------------------------------------------------------
# Routes — Media
# ---------------------------------------------------------------------------
@app.post("/generate")
async def generate(request: Request):
    """Legacy SSE endpoint — kept for compatibility."""
    _verify_key(request)
    raise HTTPException(410, "Legacy /generate endpoint removed. Use POST /run + GET /status/{jobId}.")


@app.get("/status")
async def status_legacy(request: Request):
    _verify_key(request)
    return {"running": _state["running"], "job_id": _state["job_id"],
            "progress": _state["progress"], "exit_code": _state["exit_code"]}


@app.get("/frames")
async def frames(request: Request):
    _verify_key(request)
    names = [Path(p).name for p in _rgb_frames()]
    return {"frames": names, "count": len(names)}


@app.get("/frame/{filename}")
async def frame(filename: str, request: Request):
    _verify_key(request)
    if "/" in filename or ".." in filename:
        raise HTTPException(400, "Invalid filename")
    path = DATASET_DIR / filename
    if not path.is_file():
        raise HTTPException(404, "Frame not found")
    return FileResponse(str(path), media_type="image/png")


@app.get("/video")
async def video(request: Request):
    _verify_key(request)
    path = DATASET_DIR / "output.mp4"
    if not path.is_file():
        raise HTTPException(404, "Video not found")
    return FileResponse(str(path), media_type="video/mp4", filename="output.mp4")


@app.get("/annotated-video")
async def annotated_video(request: Request):
    _verify_key(request)
    path = DATASET_DIR / "output_annotated.mp4"
    if not path.is_file():
        raise HTTPException(404, "Annotated video not found")
    return FileResponse(str(path), media_type="video/mp4", filename="output_annotated.mp4")


@app.get("/archive")
async def archive(request: Request):
    _verify_key(request)
    path = _newest_archive()
    if path is None:
        raise HTTPException(404, "No archive found")
    return FileResponse(str(path), media_type="application/gzip", filename=path.name)


@app.get("/health")
async def health():
    return {"status": "ok"}
