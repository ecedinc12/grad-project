# scripts/dev/

Geliştirme ve debug yardımcıları — production pipeline'ında kullanılmaz.

| Dosya | Açıklama |
|---|---|
| `debug_dataset.py` | Oluşturulan dataset'i inceler: kare sayısı, annotation kontrolü |
| `debug_warehouse_semantics.py` | Depo USD sahnesindeki semantik etiketleri listeler |
| `debug_workers.py` | Spawn edilen worker prim'lerini ve skeleton root'larını kontrol eder |
| `inspect_worker_assets.py` | Worker USD asset'lerinin içeriğini ve stage hiyerarşisini basar |
| `view_dataset.py` | Dataset karelerini bounding box overlay ile görüntüler |
| `view_video.py` | Oluşturulan video dosyasını oynatır |
| `class_balance.py` | Dataset'teki kategori dağılımını hesaplar ve raporlar |
| `annotate_video.py` | COCO annotation'larını video karelerine çizer, annotated video üretir |
