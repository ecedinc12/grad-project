# isaac_backend/layouts/

Prosedürel depo layout üreticisi. `assets/layouts.json`'daki 8+ preset'i somutlaştırır.

| Dosya | Açıklama |
|---|---|
| `__init__.py` | `generate_layout()` — ana giriş noktası |
| `geometry.py` | Layout geometrisi, preset tanımları ve ölçümler |
| `rack.py` | Raf satırı yerleşimi, raf rafları doldurma, kolon guard'ları |
| `dock.py` | Yükleme rampası alanı: palet gridi, kapı kümeleri, stok taşması |
| `marking.py` | Zemin işaretleri: koridor şeritleri, bölge sınırları, ana yol |
| `materials.py` | Layout primitifleri için PBR malzeme kütüphanesi |
| `placement.py` | Props ve spawner'ların paylaştığı temel yerleştirme yardımcıları |

**Alt paketler:** `props/`, `realism/`
