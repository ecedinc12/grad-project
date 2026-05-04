# llm_pipeline/

NVIDIA NIM üzerinden metin prompt'unu `SceneConfig` JSON'una dönüştüren LLM katmanı.
System Python (`python3`) ile çalışır — Isaac Sim Python'u kullanmaz.

| Dosya | Açıklama |
|---|---|
| `schemas.py` | Pydantic şemaları: `PPEState`, `Entity`, `HazardZone`, `WorkerBehavior`, `SceneConfig` |
| `generator.py` | `generate_scene_config(prompt, nim_api_key, output_path)` — NIM fallback chain ile JSON üretir (mistral-nemotron → step-3.5-flash → llama-4-maverick) |
