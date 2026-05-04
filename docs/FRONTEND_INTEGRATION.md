# VisionForge — Frontend–Backend Integration Reference

## Genel Mimari

```
[Kullanıcı Tarayıcısı]
       │
       │  HTTPS  (statik dosya sunumu)
       ▼
[DigitalOcean Droplet]
  nginx → /var/www/visionforge/app/dist/
  Domain: https://www.visionforge.tech
       │
       │  HTTP/HTTPS  (tarayıcıdan doğrudan, Droplet üzerinden geçmez)
       ▼
[RunPod GPU Container]
  FastAPI — port 8000
  Isaac Sim + LLM Pipeline
  RTX A4000+ GPU
```

**Kritik nokta:** Tarayıcı, RunPod URL'sine **doğrudan** istek atar. Droplet yalnızca statik
HTML/JS/CSS dosyalarını servis eder. Aralarında bir proxy yoktur.

---

## Repolar

| Repo | Konum | Sorumluluk |
|------|-------|------------|
| `grad-project` (bu repo) | RunPod GPU container | FastAPI + Isaac Sim + LLM pipeline |
| `grad-project-front` | DigitalOcean Droplet | React/Vite SPA, nginx ile static serve |

---

## Frontend Tech Stack

- **Framework:** React 19 + TypeScript 5.7
- **Build Tool:** Vite 6.0
- **State:** Zustand 5.0 (localStorage persist)
- **Routing:** React Router v7
- **Stil:** Tailwind CSS 4.1
- **i18n:** i18next (varsayılan dil: Türkçe)

### Frontend Dizin Yapısı (özet)

```
app/src/
├── store/
│   ├── authStore.ts        # Auth state (şimdi localStorage mock)
│   ├── settingsStore.ts    # runpodUrl + nimApiKey
│   └── projectStore.ts     # Proje CRUD
├── auth/                   # Login / Signup sayfaları
├── home/                   # Dashboard (korumalı rota)
│   └── Settings.tsx        # RunPod URL + NIM API Key modal
└── project/
    └── ProjectPage.tsx     # Pipeline tetikleme ve durum takibi
```

---

## Backend Tech Stack (bu repo)

- **API Framework:** FastAPI (Python 3.10+)
- **Simülasyon:** NVIDIA Isaac Sim 4.2+ / Omniverse
- **Scripting:** Python + Omni.kit
- **Çalışma ortamı:** RunPod GPU container (RTX A4000+)
- **Giriş noktası:** `scripts/headless_runner.py` (Isaac Sim headless)

### Backend Dizin Yapısı

```
grad-project/
├── config/
│   └── generation_config.yaml   # Sahne, kamera, annotation parametreleri
├── scripts/
│   ├── headless_runner.py       # Ana orchestrator (SimulationApp + pipeline)
│   ├── scene_builder.py         # USD sahne inşası
│   ├── scenario_runner.py       # Tehlike senaryoları
│   ├── domain_randomizer.py     # Işık, texture, kamera randomizasyonu
│   └── data_writer.py           # Annotation + görsel çıktı
├── output/
│   └── dataset_v1/
│       ├── rgb/                 # {scene_id}_{frame_id}.png
│       └── annotations/         # KITTI / COCO formatı
└── containers/
    └── isaac_sim_dev_tools/     # Dockerfile
```

---

## API Sözleşmesi

### CORS Ayarı (zorunlu)

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://www.visionforge.tech",  # production
        "http://localhost:5173",          # Vite dev server
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],  # X-NIM-API-Key için şart
)
```

> `allow_origins=["*"]` kullanmayın. Özel header (`X-NIM-API-Key`) içeren preflight
> isteklerini tarayıcı bloklar.

---

### POST /run — Pipeline Başlatma

**Headers:**
```
Content-Type: application/json
X-NIM-API-Key: nvapi-xxxxxxxxxxxxxxxx
```

**Request body:**
```json
{
  "prompt": "A busy warehouse with 4 workers near a forklift, one without a helmet.",
  "preset": "warehouse_hazard",
  "frames": 100,
  "labels": ["worker", "forklift", "helmet", "vest"]
}
```

**Response 202 — Kuyruklandı:**
```json
{
  "jobId": "uuid-string",
  "status": "queued"
}
```

**FastAPI tarafı (iskelet):**
```python
from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel
import uuid

class RunRequest(BaseModel):
    prompt: str
    preset: str
    frames: int = 100
    labels: list[str] = []

jobs: dict = {}

@app.post("/run")
async def run_pipeline(request: Request, body: RunRequest):
    nim_api_key = request.headers.get("x-nim-api-key")
    if not nim_api_key:
        raise HTTPException(400, "Missing X-NIM-API-Key header")

    job_id = str(uuid.uuid4())
    jobs[job_id] = {"status": "queued", "progress": 0, "message": "Queued", "resultUrl": None}

    # TODO: background_tasks.add_task(run_isaac_pipeline, job_id, body, nim_api_key)

    return {"jobId": job_id, "status": "queued"}
```

---

### GET /status/{jobId} — İş Durumu Sorgulama

**Response — devam ediyor:**
```json
{
  "jobId": "uuid-string",
  "status": "running",
  "progress": 45,
  "message": "Rendering frame 45/100...",
  "resultUrl": null
}
```

**Response — tamamlandı:**
```json
{
  "jobId": "uuid-string",
  "status": "completed",
  "progress": 100,
  "message": "Dataset ready",
  "resultUrl": "https://your-runpod-url/results/uuid-string.tar.gz"
}
```

**Response — başarısız:**
```json
{
  "jobId": "uuid-string",
  "status": "failed",
  "progress": 0,
  "message": "texture_overflow at rack_07",
  "resultUrl": null
}
```

---

## NVIDIA NIM API Key Akışı

Kullanıcı, NIM API anahtarını (`nvapi-...`) kendi tarayıcısında Settings modalına girer.
Anahtar `localStorage` (Zustand persist: `visionforge-settings`) içinde saklanır.
Backend bu anahtarı her pipeline isteğinde HTTP header üzerinden alır.

```
[Kullanıcı Tarayıcısı]
  localStorage: nimApiKey = "nvapi-xxx"
       │
       │  POST /run
       │  Header: X-NIM-API-Key: nvapi-xxx
       ▼
[RunPod FastAPI]
  nim_api_key = request.headers.get("x-nim-api-key")
       │
       │  runtime parametre olarak geçer
       ▼
[LLM Pipeline / llm_pipeline/generator.py]
  client = openai.AsyncOpenAI(api_key=nim_api_key, ...)
```

**Neden bu yaklaşım:**
- Backend stateless kalır, anahtar diskde saklanmaz
- Her kullanıcı kendi anahtarını kullanır
- Container yeniden başlatıldığında env-var değişikliği gerekmez

**`generator.py` içinde şu an `os.getenv("NIM_API_KEY")` kullanıyorsanız** bunu runtime
parametreye çevirin:
```python
async def generate_scene_config(prompt: str, nim_api_key: str) -> SceneConfig:
    client = openai.AsyncOpenAI(
        base_url="https://integrate.api.nvidia.com/v1",
        api_key=nim_api_key,
    )
    ...
```

---

## Auth Endpoint'leri (Gelecek Entegrasyon)

Frontend şu an **localStorage mock auth** kullanıyor (`authStore.ts`). Gerçek backend
hazır olduğunda `login()` ve `signup()` fonksiyonları aşağıdaki endpoint'lere fetch atacak.

### POST /api/auth/login

```json
// Request
{ "identifier": "user@example.com", "password": "yourpassword" }

// 200 OK
{ "user": { "id": "uuid", "email": "...", "isAdmin": false }, "token": "jwt-token" }

// 401
{ "error": "invalid_credentials" }
```

### POST /api/auth/signup

```json
// Request
{ "email": "user@example.com", "password": "yourpassword" }

// 201 Created
{ "user": { "id": "uuid", "email": "...", "isAdmin": false }, "token": "jwt-token" }

// 409
{ "error": "email_taken" }
```

### POST /api/auth/logout

```
Header: Authorization: Bearer <token>
Response: { "success": true }
```

**Admin seed:** Başlangıçta DB'ye `admin` / `admin@visionforge.tech` / `admin123`
kullanıcısını ekleyin (frontend mock'uyla uyumlu).

---

## Frontend Ayarları (Browser-only)

Hiçbir ayar backend tarafında saklanmaz.

| localStorage anahtarı | İçerik |
|-----------------------|--------|
| `visionforge-auth` | `{ user, isAuthenticated }` |
| `visionforge-users` | Kayıtlı kullanıcılar (mock auth için) |
| `visionforge-settings` | `{ runpodUrl, nimApiKey }` |
| `visionforge-projects` | Proje listesi |

**`runpodUrl` kullanımı:**
```
runpodUrl = "https://abc123-8000.proxy.runpod.net"
→ POST https://abc123-8000.proxy.runpod.net/run
→ GET  https://abc123-8000.proxy.runpod.net/status/{jobId}
```
URL doğrudan FastAPI uygulama köküne işaret eder, `/api/` prefix'i yoktur.

---

## Frontend Deployment Özeti

| Adım | Komut |
|------|-------|
| Local build | `cd app && npm run build` |
| Droplet'e güncelleme | `ssh root@<ip>` → `cd /var/www/visionforge && git pull origin main` → `cd app && npm install && npm run build` |
| nginx reload | `sudo systemctl reload nginx` |

- **nginx config:** `/etc/nginx/sites-available/sdg-ui`
- **Dist dizini:** `/var/www/visionforge/app/dist/`
- **SSL:** Let's Encrypt (Certbot otomatik yenileme)

---

## Backend Deployment Özeti (RunPod)

1. RunPod'da GPU container başlat (RTX A4000+ şart)
2. Isaac Sim 4.2+ kurulu container image kullan (`containers/` dizinine bak)
3. FastAPI uygulamasını `uvicorn main:app --host 0.0.0.0 --port 8000` ile başlat
4. RunPod'un verdiği proxy URL'ini (`https://abc123-8000.proxy.runpod.net`) frontend
   Settings modalına gir

Container her yeniden başladığında URL değişebilir — kullanıcının Settings modalını
güncellemesi gerekir.

---

## Entegrasyon Kontrol Listesi

- [ ] FastAPI'da CORS middleware doğru origin'lerle ayarlandı
- [ ] `/run` endpoint'i `X-NIM-API-Key` header'ını okuyor
- [ ] `generator.py` anahtarı runtime parametre olarak kabul ediyor (env-var değil)
- [ ] `/status/{jobId}` endpoint'i beklenen JSON şemasını döndürüyor
- [ ] Auth endpoint'leri hazır olduğunda `authStore.ts` güncellenecek
- [ ] Admin kullanıcı DB'ye seed edildi
- [ ] RunPod URL frontend Settings modalına girildi
