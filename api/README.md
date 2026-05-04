# api/

RunPod container'ında çalışan FastAPI backend. VisionForge frontend ile haberleşir.
Port 8000, `scripts/start_api.sh` ile başlatılır.

| Dosya | Açıklama |
|---|---|
| `server.py` | `POST /run` (job kuyruğa al), `GET /status/{jobId}` (durum sorgula), eski `POST /generate` (SSE stream, korundu) |
