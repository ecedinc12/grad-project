# rag_system/

Isaac Sim 5.1 dokümantasyonu üzerinde RAG (Retrieval-Augmented Generation) sistemi.
API agent'larına bağlam sağlar — pipeline'da opsiyonel kullanılır.

| Dosya | Açıklama |
|---|---|
| `build_index.py` | Vektör indeksi oluşturur: dokümanları indir, chunk'la, embed et, ChromaDB'ye kaydet |
| `loader.py` | Isaac Sim 5.1 dokümantasyonu ve proje kaynak dosyalarını yükler |
| `chunker.py` | Dokümanları overlapping token chunk'larına böler |
| `vector_store.py` | ChromaDB vektör store ve sentence-transformers embedding |
| `query.py` | Etkileşimli RAG sorgu CLI'ı |
| `generation.py` | RAG destekli sahne üretimi |
| `package.py` | RAG sistemi paket yardımcıları |
