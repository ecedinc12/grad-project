# Containers

Bu dizin altındaki diğer klasörlerde bulunan `Dockerfile`’ları build edip registry’ye push etmek için kısa notlar.

## Önkoşullar
- Docker kurulu olmalı
- Docker login yapılmış olmalı

## Build (tek bir klasör için)
`Dockerfile` hangi klasördeyse o klasöre girip build alabilirsiniz:
```bash
cd <KLASOR_ADI>
docker build -t <REGISTRY>/<NAMESPACE>/<IMAGE_NAME>:<TAG> .
```

Örnek:
```bash
cd api
docker build -t ghcr.io/username/api:latest .
```

## Push
Build aldığınız image’ı push edin:
```bash
docker push <REGISTRY>/<NAMESPACE>/<IMAGE_NAME>:<TAG>
```

Örnek:
```bash
docker push ghcr.io/your-org/api:latest
```

## Notlar
- `<TAG>` için `latest` yerine sürüm kullanmanız önerilir (örn. `1.0.0`).
- Her klasör için aynı adımları tekrarlayın (ilgili klasöre gir → `docker build` → `docker push`).