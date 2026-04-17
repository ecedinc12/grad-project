#!/bin/bash
# RunPod'da FastAPI sunucusunu başlatır.
# Kullanım: bash scripts/start_api.sh [--foreground]

set -e

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$PROJECT_ROOT/.env"
LOG_FILE="/tmp/sdg_api.log"
PID_FILE="/tmp/sdg_api.pid"

# .env varsa yükle
if [ -f "$ENV_FILE" ]; then
    set -a
    source "$ENV_FILE"
    set +a
fi

# ACCEPT_EULA her zaman Y
export ACCEPT_EULA="${ACCEPT_EULA:-Y}"

# Zaten çalışıyorsa uyar
if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "[WARN] API sunucusu zaten çalışıyor (PID: $(cat "$PID_FILE")). Durdurmak için:"
    echo "       kill \$(cat $PID_FILE)"
    exit 0
fi

cd "$PROJECT_ROOT"

# pip bağımlılıklarını yükle (yeni pod başlangıcında)
echo "[*] API bağımlılıkları kontrol ediliyor..."
pip install -q --break-system-packages -r "$PROJECT_ROOT/api/requirements.txt"

if [ "$1" = "--foreground" ]; then
    echo "[*] API sunucusu ön planda başlatılıyor (port 8000)..."
    exec uvicorn api.server:app --host 0.0.0.0 --port 8000 --log-level info
else
    echo "[*] API sunucusu arka planda başlatılıyor (port 8000)..."
    nohup uvicorn api.server:app \
        --host 0.0.0.0 \
        --port 8000 \
        --log-level info \
        > "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    echo "[OK] PID: $(cat "$PID_FILE") — Loglar: $LOG_FILE"
    echo "     RunPod HTTP Service URL'sini port 8000 için kontrol panelinden alın."
fi
