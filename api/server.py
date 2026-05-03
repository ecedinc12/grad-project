"""
FastAPI backend — RunPod GPU container'ında çalışır.

Yeni VisionForge frontend API:
  POST /run             → pipeline'ı kuyruğa al, jobId dön (202)
  GET  /status/{jobId} → iş durumu ve ilerleme

Eski Gradio UI API (korundu):
  POST /generate        → pipeline stdout'unu SSE ile stream et
  GET  /status          → eski pipeline durumu
  GET  /frames          → son çalışmadaki RGB kare URL'leri
  GET  /frame/{name}    → tek kare dosyası
  GET  /video           → output.mp4
  GET  /annotated-video → output_annotated.mp4
  GET  /archive         → son dataset_*.tar.gz
"""
from __future__ import annotations

import asyncio
import glob
import os
import random
import sys
import time
import uuid
from pathlib import Path
from typing import Optional

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
RUN_SCRIPT = PROJECT_ROOT / "scripts" / "run_pipeline.sh"
DATASET_DIR = Path("/tmp/dataset")
API_KEY = os.environ.get("DROPLET_API_KEY", "")

# ---------------------------------------------------------------------------
# App & CORS
# ---------------------------------------------------------------------------
app = FastAPI(title="VisionForge Pipeline API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://www.visionforge.tech",
        "https://visionforge.tech",
        "http://localhost:5173",   # Vite dev server
        "http://localhost:4173",   # Vite preview
    ],
    allow_credentials=True,
    allow_methods=["*"],
    # X-NIM-API-Key must be listed here; allow_origins=["*"] would block it
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Job store  (in-memory; replace with Redis for multi-process deployments)
# ---------------------------------------------------------------------------
_jobs: dict[str, dict] = {}

# Legacy single-pipeline state (kept for /generate endpoint)
_state: dict = {
    "running": False,
    "job_id": None,
    "progress": 0,
    "exit_code": None,
    "started_at": None,
}


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def _verify_key(request: Request) -> None:
    if not API_KEY:
        return  # auth disabled in dev when env var not set
    auth = request.headers.get("Authorization", "")
    if auth != f"Bearer {API_KEY}":
        raise HTTPException(status_code=401, detail="Unauthorized")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _rgb_frames(limit: int = 12) -> list[str]:
    paths = sorted(glob.glob(str(DATASET_DIR / "rgb_*.png")))
    if len(paths) <= limit:
        return paths
    return sorted(random.sample(paths, limit))


def _newest_archive() -> Optional[Path]:
    archives = sorted(
        glob.glob(str(PROJECT_ROOT / "dataset_*.tar.gz")),
        key=lambda p: os.path.getmtime(p),
    )
    return Path(archives[-1]) if archives else None


def _parse_progress(line: str) -> Optional[int]:
    """'[3/9] ...' → 33"""
    import re
    m = re.search(r"\[(\d+)/(\d+)\]", line)
    if m:
        return round(int(m.group(1)) / int(m.group(2)) * 100)
    return None


def _build_subprocess_env(nim_api_key: str) -> dict:
    return {
        **os.environ,
        "PYTHONUNBUFFERED": "1",
        "ACCEPT_EULA": os.environ.get("ACCEPT_EULA", "Y"),
        "NIM_API_KEY": nim_api_key,
    }


# ---------------------------------------------------------------------------
# Background task for /run
# ---------------------------------------------------------------------------
async def _run_job(job_id: str, prompt: str, nim_api_key: str) -> None:
    _jobs[job_id].update(status="running", message="Starting pipeline...")

    env = _build_subprocess_env(nim_api_key)

    try:
        proc = await asyncio.create_subprocess_exec(
            "/bin/bash", str(RUN_SCRIPT), prompt,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(PROJECT_ROOT),
            env=env,
        )

        async for raw in proc.stdout:  # type: ignore[union-attr]
            line = raw.decode("utf-8", errors="replace").rstrip()
            progress = _parse_progress(line)
            if progress is not None:
                _jobs[job_id]["progress"] = progress
            _jobs[job_id]["message"] = line[:200]  # truncate runaway lines

        await proc.wait()

        if proc.returncode == 0:
            archive = _newest_archive()
            _jobs[job_id].update(
                status="completed",
                progress=100,
                message="Dataset ready",
                resultUrl="/archive" if archive else None,
            )
        else:
            _jobs[job_id].update(
                status="failed",
                message=f"Pipeline exited with code {proc.returncode}",
            )

    except Exception as exc:
        _jobs[job_id].update(status="failed", message=str(exc))


# ---------------------------------------------------------------------------
# Routes — VisionForge frontend API
# ---------------------------------------------------------------------------
class RunRequest(BaseModel):
    prompt: str
    preset: str = ""
    frames: int = 100
    labels: list[str] = []


@app.post("/run", status_code=202)
async def run(req: RunRequest, request: Request, background_tasks: BackgroundTasks):
    """Queue a pipeline job. Returns jobId immediately; poll /status/{jobId}."""
    _verify_key(request)

    nim_api_key = request.headers.get("x-nim-api-key", "").strip()
    if not nim_api_key:
        raise HTTPException(status_code=400, detail="Missing X-NIM-API-Key header")

    if not req.prompt.strip():
        raise HTTPException(status_code=422, detail="Prompt cannot be empty")

    job_id = str(uuid.uuid4())
    _jobs[job_id] = {
        "status": "queued",
        "progress": 0,
        "message": "Job queued",
        "resultUrl": None,
    }

    background_tasks.add_task(_run_job, job_id, req.prompt.strip(), nim_api_key)

    return {"jobId": job_id, "status": "queued"}


@app.get("/status/{job_id}")
async def job_status(job_id: str, request: Request):
    """Poll job status. Status values: queued | running | completed | failed."""
    _verify_key(request)
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"jobId": job_id, **job}


# ---------------------------------------------------------------------------
# Routes — legacy Gradio UI API (unchanged)
# ---------------------------------------------------------------------------
class GenerateRequest(BaseModel):
    prompt: str


@app.post("/generate")
async def generate(req: GenerateRequest, request: Request):
    _verify_key(request)

    if _state["running"]:
        raise HTTPException(status_code=409, detail="Pipeline is already running")

    if not req.prompt.strip():
        raise HTTPException(status_code=422, detail="Prompt cannot be empty")

    nim_api_key = request.headers.get("x-nim-api-key", "").strip()
    # Legacy endpoint: fall back to env var if header absent (Gradio UI path)
    if not nim_api_key:
        nim_api_key = os.environ.get("NIM_API_KEY", "")

    async def _sse_stream():
        job_id = str(int(time.time()))
        _state.update(running=True, job_id=job_id, progress=0,
                      exit_code=None, started_at=time.time())

        env = _build_subprocess_env(nim_api_key)

        try:
            proc = await asyncio.create_subprocess_exec(
                "/bin/bash", str(RUN_SCRIPT), req.prompt.strip(),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(PROJECT_ROOT),
                env=env,
            )

            async for raw in proc.stdout:  # type: ignore[union-attr]
                line = raw.decode("utf-8", errors="replace").rstrip("\n")
                progress = _parse_progress(line)
                if progress is not None:
                    _state["progress"] = progress
                yield f"data: {line}\n\n"

            await proc.wait()
            _state["exit_code"] = proc.returncode
            status = "OK" if proc.returncode == 0 else f"ERROR:{proc.returncode}"
            yield f"data: [DONE] {status}\n\n"

        except Exception as exc:
            yield f"data: [FATAL] {exc}\n\n"
        finally:
            _state["running"] = False

    return StreamingResponse(
        _sse_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/status")
async def status(request: Request):
    _verify_key(request)
    return {
        "running": _state["running"],
        "job_id": _state["job_id"],
        "progress": _state["progress"],
        "exit_code": _state["exit_code"],
        "elapsed": (
            round(time.time() - _state["started_at"])
            if _state["started_at"] and _state["running"]
            else None
        ),
    }


@app.get("/frames")
async def frames(request: Request):
    _verify_key(request)
    names = [Path(p).name for p in _rgb_frames()]
    return {"frames": names, "count": len(names)}


@app.get("/frame/{filename}")
async def frame(filename: str, request: Request):
    _verify_key(request)
    if "/" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    path = DATASET_DIR / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Frame not found")
    return FileResponse(str(path), media_type="image/png")


@app.get("/video")
async def video(request: Request):
    _verify_key(request)
    path = DATASET_DIR / "output.mp4"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Video not found")
    return FileResponse(str(path), media_type="video/mp4", filename="output.mp4")


@app.get("/annotated-video")
async def annotated_video(request: Request):
    _verify_key(request)
    path = DATASET_DIR / "output_annotated.mp4"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Annotated video not found")
    return FileResponse(str(path), media_type="video/mp4", filename="output_annotated.mp4")


@app.get("/archive")
async def archive(request: Request):
    _verify_key(request)
    path = _newest_archive()
    if path is None:
        raise HTTPException(status_code=404, detail="No archive found")
    return FileResponse(str(path), media_type="application/gzip", filename=path.name)


@app.get("/health")
async def health():
    return {"status": "ok"}
