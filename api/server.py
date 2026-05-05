from __future__ import annotations

import asyncio
import glob
import os
import random
import re
import time
import uuid
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUN_SCRIPT   = PROJECT_ROOT / "scripts" / "run_pipeline.sh"
DATASET_DIR  = Path("/tmp/dataset")
FRAMES_DIR   = DATASET_DIR / "Replicator"

DROPLET_API_KEY = os.environ.get("DROPLET_API_KEY", "")

# ---------------------------------------------------------------------------
# App & CORS
# ---------------------------------------------------------------------------
app = FastAPI(title="VisionForge Pipeline API", version="2.0.0")

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
# Auth guard  (DROPLET_API_KEY simple check)
# ---------------------------------------------------------------------------
def _verify_key(request: Request) -> None:
    if not DROPLET_API_KEY:
        return
    auth = request.headers.get("Authorization", "")
    if auth == f"Bearer {DROPLET_API_KEY}":
        return
    raise HTTPException(status_code=401, detail="Unauthorized")


# ---------------------------------------------------------------------------
# Job store  (in-memory)
# ---------------------------------------------------------------------------
_jobs: dict[str, dict] = {}

_state: dict = {
    "running": False, "job_id": None, "progress": 0,
    "exit_code": None, "started_at": None,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _rgb_frames(limit: int = 12) -> list[str]:
    paths = sorted(glob.glob(str(FRAMES_DIR / "rgb_*.png")))
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
# Background task
# ---------------------------------------------------------------------------
async def _run_job(job_id: str, prompt: str, nim_api_key: str,
                   frames: int = 100, generate_video: bool = True,
                   annotation_format: str = "both") -> None:
    _jobs[job_id].update(status="running", message="Starting pipeline...")
    env = _build_env(nim_api_key)
    try:
        proc = await asyncio.create_subprocess_exec(
            "/bin/bash", str(RUN_SCRIPT), prompt,
            str(frames), str(generate_video).lower(), annotation_format,
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
    generate_video: bool = True
    annotation_format: str = "both"  # coco | yolo | both


@app.post("/run", status_code=202)
async def run(req: RunRequest, request: Request, background_tasks: BackgroundTasks):
    _verify_key(request)

    nim_api_key = request.headers.get("x-nim-api-key", "").strip()
    if not nim_api_key:
        raise HTTPException(400, "NIM API key missing — pass X-NIM-API-Key header")

    if not req.prompt.strip():
        raise HTTPException(422, "Prompt cannot be empty")

    job_id = str(uuid.uuid4())
    _jobs[job_id] = {"status": "queued", "progress": 0, "message": "Job queued", "resultUrl": None, "logs": []}
    background_tasks.add_task(_run_job, job_id, req.prompt.strip(), nim_api_key,
                               req.frames, req.generate_video, req.annotation_format)
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
    path = FRAMES_DIR / filename
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
