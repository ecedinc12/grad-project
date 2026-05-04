# Containers

VisionForge projesinde kullanılan Docker imajları. Tümü `nvcr.io/nvidia/isaac-sim:5.1.0` base imajı üzerine kuruludur.

## Mevcut Konteynerler

| Klasör | Amaç | Entrypoint |
|--------|------|-----------|
| `production/` | RunPod GPU pod — API otomatik başlar | `start.sh` |
| `development/` | Lokal geliştirme — interaktif kullanım | yok |
| `isaac_sim_dev_tools/` | Isaac Sim minimal araç seti | yok |

---

## Build

```bash
# Production
docker build -t <DOCKERHUB_USER>/visionforge:production -f containers/production/Dockerfile .

# Development
docker build -t <DOCKERHUB_USER>/visionforge:development -f containers/development/Dockerfile .

# Isaac Sim Dev Tools
docker build -t <DOCKERHUB_USER>/visionforge:isaac-dev -f containers/isaac_sim_dev_tools/dockerfile .
```

## Push

```bash
docker push <DOCKERHUB_USER>/visionforge:production
docker push <DOCKERHUB_USER>/visionforge:development
docker push <DOCKERHUB_USER>/visionforge:isaac-dev
```

## Pull & Çalıştır

```bash
# Production (RunPod — API port 8000'de otomatik ayağa kalkar)
docker pull <DOCKERHUB_USER>/visionforge:production

# Development (interaktif)
docker pull <DOCKERHUB_USER>/visionforge:development
docker run --gpus all -it --rm \
  -v $(pwd):/workspace/grad-project \
  -p 8000:8000 \
  <DOCKERHUB_USER>/visionforge:development bash

# Isaac Sim Dev Tools (interaktif)
docker pull <DOCKERHUB_USER>/visionforge:isaac-dev
docker run --gpus all -it --rm \
  <DOCKERHUB_USER>/visionforge:isaac-dev bash
```

---

Daha önce push edilmiş hazır imajlar için: [`pre-built_containers.md`](./pre-built_containers.md)
