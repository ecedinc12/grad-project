# Containers

VisionForge projesinde kullanılan Docker imajları. Tümü `nvcr.io/nvidia/isaac-sim:5.1.0` base imajı üzerine kuruludur.

## Mevcut Konteynerler

| Klasör | Amaç | Entrypoint |
|--------|------|-----------|
| `production/` | RunPod GPU pod — API otomatik başlar | `start.sh` |
| `development/` | Lokal geliştirme — interaktif kullanım | yok |

---

## Build

```bash
# Production
docker build -t arda78484/visionforge:production:v1.x .

# Development
docker build -t arda78484/visionforge:development:v1.x .
```
## Push

```bash
docker push arda78484/visionforge_production:v1.x
docker push arda78484/visionforge_development:v1.x
```

## Pull & Çalıştırma Runpod (veya farklı bir GPU provider) üzerinden yapılır

---

## Mevcut İmajlar

| Ad | Tag | Açıklama |
|---|---|---|
| `arda78484/isaac_sim_dev_tools` | `v-1.0` | Isaac Sim geliştirme araçları |
| `arda78484/isaac_sim_dev_tools` | `v-1.1` | Requirements yüklendi |
| `arda78484/visionforge_production` | `v1.0` | Production container init |
| `arda78484/visionforge_development` | `v1.0` | Development container init |
