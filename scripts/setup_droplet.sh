#!/bin/bash
# DigitalOcean Droplet kurulum scripti.
# Ubuntu 22.04 LTS üzerinde tek seferlik çalıştırılır.
# Kullanım: sudo bash scripts/setup_droplet.sh

set -e

REPO_DIR="/opt/grad-project"
SERVICE_FILE="/etc/systemd/system/sdg-ui.service"
NGINX_CONF="/etc/nginx/sites-available/sdg-ui"
PYTHON_BIN="python3.11"

echo "========================================"
echo " SDG UI — Droplet Kurulumu"
echo "========================================"

# ------------------------------------------------------------------ #
# 1. Sistem güncellemesi & paketler                                   #
# ------------------------------------------------------------------ #
echo "[1/6] Sistem paketleri güncelleniyor..."
apt-get update -q
apt-get install -y -q \
    python3.11 python3.11-venv python3.11-dev \
    python3-pip \
    nginx \
    git \
    curl

# ------------------------------------------------------------------ #
# 2. Repo kopyala / güncelle                                         #
# ------------------------------------------------------------------ #
echo "[2/6] Repo hazırlanıyor: $REPO_DIR"
if [ -d "$REPO_DIR/.git" ]; then
    git -C "$REPO_DIR" pull --ff-only
else
    # GitHub Education reposunu kopyala; URL'yi kendi repo'nuza göre güncelleyin
    git clone https://github.com/YOUR_USERNAME/grad-project.git "$REPO_DIR"
fi

# ------------------------------------------------------------------ #
# 3. Python sanal ortamı & bağımlılıklar                             #
# ------------------------------------------------------------------ #
echo "[3/6] Python sanal ortamı oluşturuluyor..."
$PYTHON_BIN -m venv "$REPO_DIR/.venv"
"$REPO_DIR/.venv/bin/pip" install -q --upgrade pip
"$REPO_DIR/.venv/bin/pip" install -q \
    gradio \
    httpx \
    python-dotenv

# ------------------------------------------------------------------ #
# 4. .env dosyası                                                     #
# ------------------------------------------------------------------ #
echo "[4/6] .env dosyası kontrol ediliyor..."
if [ ! -f "$REPO_DIR/.env" ]; then
    cp "$REPO_DIR/.env.example" "$REPO_DIR/.env"
    echo ""
    echo "  ⚠️  $REPO_DIR/.env oluşturuldu."
    echo "     BACKEND_URL ve DROPLET_API_KEY değerlerini doldurun:"
    echo "     nano $REPO_DIR/.env"
    echo ""
fi

# ------------------------------------------------------------------ #
# 5. systemd servisi                                                  #
# ------------------------------------------------------------------ #
echo "[5/6] systemd servisi kuruluyor..."
cat > "$SERVICE_FILE" <<'EOF'
[Unit]
Description=SDG Digital Twin — Gradio UI
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/grad-project
EnvironmentFile=/opt/grad-project/.env
ExecStart=/opt/grad-project/.venv/bin/python3 /opt/grad-project/ui/app.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable sdg-ui
systemctl restart sdg-ui
echo "    systemd: sdg-ui servisi aktif"

# ------------------------------------------------------------------ #
# 6. Nginx reverse proxy                                              #
# ------------------------------------------------------------------ #
echo "[6/6] Nginx yapılandırılıyor (port 80 → 7860)..."
cat > "$NGINX_CONF" <<'EOF'
server {
    listen 80;
    server_name _;

    # Gradio WebSocket + SSE için gerekli
    proxy_read_timeout 3600;
    proxy_send_timeout 3600;
    proxy_buffering    off;

    location / {
        proxy_pass         http://127.0.0.1:7860;
        proxy_http_version 1.1;
        proxy_set_header   Upgrade $http_upgrade;
        proxy_set_header   Connection "upgrade";
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_cache_bypass $http_upgrade;
    }
}
EOF

ln -sf "$NGINX_CONF" /etc/nginx/sites-enabled/sdg-ui
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

echo ""
echo "========================================"
echo " Kurulum tamamlandı!"
echo " GUI: http://$(curl -s ifconfig.me)"
echo " Loglar: journalctl -u sdg-ui -f"
echo "========================================"
