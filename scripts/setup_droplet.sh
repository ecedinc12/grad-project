#!/bin/bash
# DigitalOcean Droplet kurulum scripti — tek seferlik çalıştırılır.
# Statik React frontend (grad-project-front) + nginx + SSL kurulumu yapar.
# Kullanım: sudo bash scripts/setup_droplet.sh
#
# Mimari: Frontend (bu droplet) ←→ Backend API (RunPod, ayrı)

set -e

FRONTEND_REPO="https://github.com/ecedinc12/grad-project-front.git"
DEPLOY_DIR="/var/www/visionforge"
NGINX_CONF="/etc/nginx/sites-available/sdg-ui"
DOMAIN="visionforge.tech"

echo "========================================"
echo " VisionForge — Droplet Kurulumu"
echo "========================================"

# ------------------------------------------------------------------ #
# 1. Sistem güncellemesi & paketler                                   #
# ------------------------------------------------------------------ #
echo "[1/5] Sistem paketleri güncelleniyor..."
apt-get update -q
apt-get install -y -q nginx git curl nodejs npm certbot python3-certbot-nginx

# ------------------------------------------------------------------ #
# 2. Frontend repo'sunu kopyala / güncelle                           #
# ------------------------------------------------------------------ #
echo "[2/5] Frontend repo hazırlanıyor: $DEPLOY_DIR"
if [ -d "$DEPLOY_DIR/.git" ]; then
    git -C "$DEPLOY_DIR" pull --ff-only
else
    git clone "$FRONTEND_REPO" "$DEPLOY_DIR"
fi

# React build
cd "$DEPLOY_DIR/app"
npm install --silent
npm run build
echo "    React build tamamlandı: $DEPLOY_DIR/app/dist"

# ------------------------------------------------------------------ #
# 3. .env dosyası                                                     #
# ------------------------------------------------------------------ #
echo "[3/5] .env kontrol ediliyor..."
if [ ! -f "$DEPLOY_DIR/.env" ]; then
    echo "  DROPLET_API_KEY değerini doldurun: nano $DEPLOY_DIR/.env"
fi

# ------------------------------------------------------------------ #
# 4. Nginx — statik React SPA                                        #
# ------------------------------------------------------------------ #
echo "[4/5] Nginx yapılandırılıyor..."
cp "$(dirname "$0")/../deploy/nginx.conf" "$NGINX_CONF"
ln -sf "$NGINX_CONF" /etc/nginx/sites-enabled/sdg-ui
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx
echo "    Nginx hazır (HTTP, SSL sonra eklenecek)"

# ------------------------------------------------------------------ #
# 5. SSL — Let's Encrypt                                             #
# ------------------------------------------------------------------ #
echo "[5/5] SSL sertifikası alınıyor ($DOMAIN)..."
certbot --nginx -d "$DOMAIN" -d "www.$DOMAIN" --non-interactive --agree-tos --email ardacam2004@gmail.com || \
    echo "  SSL kurulumu atlandı — certbot manuel çalıştırın: certbot --nginx -d $DOMAIN"

echo ""
echo "========================================"
echo " Kurulum tamamlandı!"
echo " Site: https://$DOMAIN"
echo " Güncelleme: cd $DEPLOY_DIR && git pull && cd app && npm run build"
echo "========================================"
