"""
FastAPI backend — RunPod'da çalışır.
POST /generate → pipeline stdout'unu SSE ile stream eder.
GET  /status   → pipeline durumu
GET  /frames   → son çalışmadaki RGB kare URL'leri
GET  /frame/{name} → tek kare dosyası
GET  /video    → output.mp4
GET  /annotated-video → output_annotated.mp4 (işçi kutuları)
GET  /archive  → son dataset_*.tar.gz
"""
from __future__ import annotations

import asyncio
import glob
import os
import time
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
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
app = FastAPI(title="SDG Pipeline API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # API key auth sağlar güvenliği
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Pipeline state (tek process — concurrent çalışmayı engelle)
# ---------------------------------------------------------------------------
_state: dict = {
    "running": False,
    "job_id": None,
    "progress": 0,   # 0–100
    "exit_code": None,
    "started_at": None,
}


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def _verify_key(request: Request) -> None:
    if not API_KEY:
        return  # key tanımlı değilse auth devre dışı (geliştirme modu)
    auth = request.headers.get("Authorization", "")
    if auth != f"Bearer {API_KEY}":
        raise HTTPException(status_code=401, detail="Unauthorized")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _rgb_frames(limit: int = 12) -> list[str]:
    import random
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


# ---------------------------------------------------------------------------
# Routes
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

    async def _sse_stream():
        job_id = str(int(time.time()))
        _state.update(running=True, job_id=job_id, progress=0,
                      exit_code=None, started_at=time.time())

        env = {
            **os.environ,
            "PYTHONUNBUFFERED": "1",
            "ACCEPT_EULA": os.environ.get("ACCEPT_EULA", "Y"),
        }

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

                # SSE satır formatı: "data: <içerik>\n\n"
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
            "X-Accel-Buffering": "no",  # Nginx proxy buffering'i kapat
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
    """Son çalışmadaki ilk 12 RGB kare dosya adlarını döndürür."""
    _verify_key(request)
    names = [Path(p).name for p in _rgb_frames()]
    return {"frames": names, "count": len(names)}


@app.get("/frame/{filename}")
async def frame(filename: str, request: Request):
    _verify_key(request)
    # Basit path traversal koruması
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
    return FileResponse(
        str(path),
        media_type="video/mp4",
        filename="output.mp4",
    )


@app.get("/annotated-video")
async def annotated_video(request: Request):
    _verify_key(request)
    path = DATASET_DIR / "output_annotated.mp4"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Annotated video not found")
    return FileResponse(
        str(path),
        media_type="video/mp4",
        filename="output_annotated.mp4",
    )


@app.get("/archive")
async def archive(request: Request):
    _verify_key(request)
    path = _newest_archive()
    if path is None:
        raise HTTPException(status_code=404, detail="No archive found")
    return FileResponse(
        str(path),
        media_type="application/gzip",
        filename=path.name,
    )


@app.get("/health")
async def health():
    return {"status": "ok"}
