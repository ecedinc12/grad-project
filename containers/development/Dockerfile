# ═══════════════════════════════════════════════════════════════
#  VisionForge Development Container
#  Base: nvcr.io/nvidia/isaac-sim:5.1.0
#
#  Build & push:
#    docker build -t YOUR_DOCKERHUB_USER/visionforge:dev -f containers/development/Dockerfile .
#    docker push YOUR_DOCKERHUB_USER/visionforge:dev
#
#  Run interactively:
#    docker run --gpus all -it --rm \
#      -v $(pwd):/workspace/grad-project \
#      -p 8000:8000 \
#      YOUR_DOCKERHUB_USER/visionforge:dev bash
# ═══════════════════════════════════════════════════════════════

FROM nvcr.io/nvidia/isaac-sim:5.1.0

USER root

# ── System packages ─────────────────────────────────────────
RUN apt-get update && apt-get install -y \
    build-essential \
    git \
    nano \
    curl \
    wget \
    ffmpeg \
    python3-dev \
    python3-pip \
    python3-venv \
    && rm -rf /var/lib/apt/lists/*

# ── LLM pipeline dependencies ────────────────────────────────
RUN pip3 install --no-cache-dir --break-system-packages \
    "instructor>=1.6.0" \
    "openai>=1.30.0" \
    "pydantic>=2.0.0" \
    "numpy>=1.24.0,<2.0.0" \
    "Pillow>=10.0.0" \
    "huggingface_hub>=0.20.0"

# ── FastAPI server dependencies ──────────────────────────────
RUN pip3 install --no-cache-dir --break-system-packages \
    "fastapi>=0.110.0" \
    "uvicorn[standard]>=0.29.0" \
    "python-dotenv>=1.0.0"

WORKDIR /workspace
EXPOSE 8000
