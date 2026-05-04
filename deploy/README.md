# deploy/

DigitalOcean Droplet konfigürasyon dosyaları.
Backend (FastAPI) RunPod'da ayrıca çalışır — bu klasör yalnızca frontend Droplet içindir.

| Dosya | Açıklama |
|---|---|
| `nginx.conf` | Statik React build'ini serve eden nginx konfigürasyonu (visionforge.tech, HTTPS+gzip+SPA fallback) |
