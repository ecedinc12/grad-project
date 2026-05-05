# ═══════════════════════════════════════════════════════════════
#  VisionForge RunPod Container
#  Base: nvcr.io/nvidia/isaac-sim:5.1.0
#
#  Build & push:
#    docker build -t YOUR_DOCKERHUB_USER/visionforge:latest -f docker/Dockerfile .
#    docker push YOUR_DOCKERHUB_USER/visionforge:latest
#
#  RunPod Template setup:
#    Container Image : YOUR_DOCKERHUB_USER/visionforge:latest
#    Expose TCP port : 8000
#    Environment variables:
#      GITHUB_TOKEN    = <GitHub PAT — required if repo is private>
#      NIM_API_KEY     = <NVIDIA NIM key — optional, users can enter via UI>
#      DROPLET_API_KEY = <API bearer token — leave empty to disable auth>
#
#  API starts automatically on pod creation — no SSH needed.
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
    supervisor \
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

# ── Startup script ───────────────────────────────────────────
COPY start.sh /start.sh
RUN chmod +x /start.sh

WORKDIR /workspace
EXPOSE 8000

ENTRYPOINT ["/start.sh"]
