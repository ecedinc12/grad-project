#!/bin/bash
# VisionForge RunPod auto-start script
# Runs automatically when the container starts.
# Set these env vars in your RunPod template:
#   GITHUB_TOKEN    — personal access token if repo is private (repo scope only)
#   NIM_API_KEY     — NVIDIA NIM key (optional; users can also enter via UI)
#   DROPLET_API_KEY — API bearer token (leave empty to disable auth)

REPO_HTTPS="https://github.com/ecedinc12/grad-project.git"
BRANCH="master"
DIR="/workspace/grad-project"

echo "╔══════════════════════════════════════════╗"
echo "║     VisionForge — Container Startup      ║"
echo "╚══════════════════════════════════════════╝"

# ── 1. Install ffmpeg if missing ────────────────────────────
if ! command -v ffmpeg &>/dev/null; then
    echo "[startup] Installing ffmpeg..."
    apt-get update -qq && apt-get install -y -qq ffmpeg git curl supervisor \
        && rm -rf /var/lib/apt/lists/*
fi

# ── 2. Clone or update the repo ─────────────────────────────
if [ -n "${GITHUB_TOKEN:-}" ]; then
    CLONE_URL="https://${GITHUB_TOKEN}@github.com/ecedinc12/grad-project.git"
else
    CLONE_URL="$REPO_HTTPS"
fi

if [ -d "$DIR/.git" ]; then
    echo "[startup] Updating repo ($BRANCH)..."
    git -C "$DIR" remote set-url origin "$CLONE_URL" 2>/dev/null || true
    git -C "$DIR" pull origin "$BRANCH" || echo "[startup] git pull failed — using existing code"
else
    echo "[startup] Cloning repo ($BRANCH)..."
    git clone --branch "$BRANCH" "$CLONE_URL" "$DIR" \
        || { echo "[startup] ERROR: git clone failed. Set GITHUB_TOKEN if repo is private."; exit 1; }
fi

# ── 3. Patch Isaac Sim fast_importer ────────────────────────
FAST_IMPORTER="/isaac-sim/kit/kernel/py/omni/ext/_impl/fast_importer.py"
if [ -f "$FAST_IMPORTER" ]; then
    sed -i 's/for p in spec_default.submodule_search_locations:/for p in (spec_default.submodule_search_locations or []):/' \
        "$FAST_IMPORTER" && echo "[startup] Patched fast_importer.py"
fi

# ── 4. Install Python dependencies ──────────────────────────
echo "[startup] Installing Python dependencies..."
pip3 install --break-system-packages -q \
    "fastapi>=0.110.0" \
    "uvicorn[standard]>=0.29.0" \
    "python-dotenv>=1.0.0" \
    "instructor>=1.4.0" \
    "openai>=1.30.0" \
    "pydantic>=2.0.0" \
    "pillow>=10.0.0" \
    "numpy>=1.24.0"

echo "[startup] All dependencies ready."

# ── 5. Write supervisord config ─────────────────────────────
mkdir -p /etc/supervisor/conf.d
cat > /etc/supervisor/conf.d/api.conf << 'EOF'
[supervisord]
nodaemon=true
logfile=/dev/null
logfile_maxbytes=0
pidfile=/tmp/supervisord.pid

[unix_http_server]
file=/tmp/supervisor.sock

[rpcinterface:supervisor]
supervisor.rpcinterface_factory = supervisor.rpcinterface:make_main_rpcinterface

[supervisorctl]
serverurl=unix:///tmp/supervisor.sock

[program:api]
command=uvicorn api.server:app --host 0.0.0.0 --port 8000 --timeout-keep-alive 600 --log-level warning
directory=/workspace/grad-project
autostart=true
autorestart=true
startretries=10
stopasgroup=true
killasgroup=true
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
stderr_logfile=/dev/stderr
stderr_logfile_maxbytes=0
EOF

# ── 6. Start supervisord ─────────────────────────────────────
echo "[startup] Starting supervisord..."
exec supervisord -c /etc/supervisor/conf.d/api.conf
