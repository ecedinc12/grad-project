# scripts/

Production pipeline ve deployment scriptleri.

| Dosya | Açıklama |
|---|---|
| `run_pipeline.sh` | Ana pipeline orkestratörü: LLM → Isaac Sim → COCO→YOLO → tar arşivi |
| `start_api.sh` | RunPod'da FastAPI sunucusunu başlatır (`--foreground` flag opsiyonel) |
| `coco_to_yolo.py` | COCO JSON → YOLO `.txt` dönüştürücü, bounding box normalize eder |
| `gen_dataset_yaml.py` | YOLO eğitimi için `dataset.yaml` üretici |
| `make_video.sh` | `/tmp/dataset` RGB karelerinden `output.mp4` oluşturur |
| `build_and_push.sh` | Docker image build + RunPod registry push |
| `test_layouts.sh` | Tüm layout preset'lerini test JSON'larıyla sıralı çalıştırır |
| `setup_droplet.sh` | DigitalOcean Droplet tek seferlik kurulum (nginx + React build + SSL) |

**Debug scriptleri:** `dev/` klasörüne bakın.
