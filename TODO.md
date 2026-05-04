#### Phase 0: RunPod Environment Setup
- [x] **Task 0.1: Scaffolding.** Inside `/workspace`, create the directory structure: `llm_pipeline/`, `isaac_backend/`, `assets/`, `configs/`, `scripts/`.
- [x] **Task 0.2: Virtual Environments.** Ensure the agent knows that `llm_pipeline/` scripts use the system Python (e.g., `python3`), while `isaac_backend/` scripts MUST use Isaac Sim's bundled Python (`/isaac-sim/python.sh`).

#### Phase 1: Data Structures & Asset Registry
- [x] **Task 1.1: Pydantic Schemas.** In `llm_pipeline/schemas.py`, define the strict JSON schema:
    - `PPEState`: booleans (`hardhat`, `vest`).
    - `Entity`: `type` (worker/vehicle/zone), `asset_id`, `PPEState`, `anchor_zone`.
    - `SceneConfig`: List of entities, camera angles, lighting conditions.
- [x] **Task 1.2: Asset Registry.** In `assets/library.json`, map plain English terms to valid USD paths (e.g., `"forklift": "omniverse://localhost/NVIDIA/Assets/Isaac/.../forklift.usd"`).

#### Phase 2: The LLM "Text-to-Config" Layer
- [x] **Task 2.1: Instructor Integration.** In `llm_pipeline/generator.py`, implement the `instructor` library using a lightweight API (e.g., Groq/Gemini via standard `requests` or `openai` client) to save RunPod VRAM.
- [x] **Task 2.2: The Extraction Prompt.** Write the prompt logic to map user input ("spawn forklift near worker without hardhat") into the `SceneConfig` schema. Set defaults (e.g., `hardhat=True` unless stated otherwise).
- [x] **Task 2.3: Config Exporter.** Save the validated output to `/workspace/configs/current_scene.json`.

#### Phase 3: Isaac Sim Backend Foundation
- [x] **Task 3.1: Headless Bootstrapper.** In `isaac_backend/main.py`, instantiate `SimulationApp({"headless": True})`.
- [x] **Task 3.2: Config Ingestion.** Write a parser in `main.py` that loads `/workspace/configs/current_scene.json` and cross-references `assets/library.json`.
- [x] **Task 3.3: Replicator Writer.** Import `omni.replicator.core as rep`. Initialize `rep.WriterRegistry.get("BasicWriter")`. 
    - **CRITICAL:** Set `output_dir="/tmp/dataset"`. Enable `rgb`, `bounding_box_2d_tight`, and `semantic_segmentation`. Format MUST be `coco`.

#### Phase 4: Industrial Safety Logic (Sim-to-Real)
- [x] **Task 4.1: Semantics Applicator.** Write `apply_semantics(prim, class_name)` using `rep.modify.semantics([("class", class_name)])`. Workers = `Person`, Forklifts = `Vehicle`.
- [x] **Task 4.2: Geofence Bounds.** Write a function using `rep.randomizer.scatter_2d` to spawn entities strictly within invisible USD volume bounds (Hazard Zones).
- [x] **Task 4.3: PPE Physics Attacher.** Write `attach_ppe(worker_prim, ppe_state)`. Use `omni.physx` to create a `FixedJoint` between the worker's head mesh/bone and the hardhat USD so it doesn't float.

#### Phase 5: Execution Loop & I/O Optimization
- [x] **Task 5.1: The SDG Trigger.** Wrap the generation logic in `with rep.trigger.on_frame(num_frames=1000):`. Add `rep.randomizer.camera_pan()` to get varied shots from one config.
- [x] **Task 5.2: COCO to YOLO Converter.** In `scripts/coco_to_yolo.py`, write a standard Python script (NOT Isaac Python) that reads the generated COCO JSON in `/tmp/dataset`, normalizes the bounding boxes `(x_center, y_center, width, height)` by image dimensions, and writes YOLO `.txt` files.
- [x] **Task 5.3: RunPod Orchestrator Script.** Create `/workspace/scripts/run_pipeline.sh`. It must execute exactly this sequence:
    1. `python3 /workspace/llm_pipeline/generator.py --prompt "$1"`
    2. `rm -rf /tmp/dataset` (Clear old fast-disk data)
    3. `/isaac-sim/python.sh /workspace/isaac_backend/main.py` (Generate data)
4. `python3 /workspace/scripts/coco_to_yolo.py --dir /tmp/dataset` (Post-process)
     5. `tar -czf /workspace/dataset_$(date +%s).tar.gz -C /tmp dataset/` (Move to slow persistent storage)

#### Phase 6: IRA Behavior Script Animation (Replaces omni.anim.people)
- [x] **Task 6.1: Behavior Script Package.** Create `isaac_backend/behaviors/` with `__init__.py`, `worker_patrol.py`, `worker_idle_pose.py`.
    - `WorkerPatrolBehavior`: Waypoint lerping (GoTo), idle pause, look-around rotation, SkeletalAnimation blending (walk while moving, idle while stopped).
    - `WorkerIdlePoseBehavior`: Periodic Y-rotation randomization + idle SkelAnimation for workers without commands.
- [x] **Task 6.2: Unified Animation Module.** Create `isaac_backend/animation.py` replacing `people.py` + `animator.py`.
    - `attach_worker_patrol()`: Attaches `worker_patrol.py` via PythonScriptingComponent with USD-exposed waypoints/speed/duration params.
    - `attach_worker_idle_pose()`: Attaches `worker_idle_pose.py` with interval/rotation-range params.
    - `setup_all_behaviors()`: Orchestrates attachment for all spawned workers, enables `isaacsim.replicator.behavior` extension.
- [x] **Task 6.3: Simplify Worker Spawning.** Rewrite `workers.py` — remove `attach_character_behavior()`, `_find_skelroot()`, `_wait_for_skelroot()`, `AnimGraphSchema` dependency. Workers are now just Xform + USD ref + semantics; behavior scripts attached separately by `animation.py`.
- [x] **Task 6.4: Simplify Pipeline Orchestrator.** Rewrite `main.py` — remove `--anim-mode` flag, `enable_extensions()`, `setup_navmesh()`, `setup_people_simulation()`, `write_command_file()`, direct-mode branch, all diagnostics. Single animation path: `spawn_workers()` → `setup_all_behaviors()` → timeline play → Replicator loop.
- [x] **Task 6.5: Clean Up.** Delete `isaac_backend/people.py` and `isaac_backend/animator.py`. Update `__init__.py` exports.

#### Phase 7: Complete Rewrite — Isaac Sim 5.1 Extension & Library Update
- [x] **Task 7.1: Delete Deprecated Files.** Removed `people.py`, `animator.py`, `test_people_walk.py`, `references/omni_anim_people/`.
- [x] **Task 7.2: Rewrite `main.py`.** `isaacsim.core.api.World`, CocoWriter with 14 categories (incl. hazard zones), DLSS Quality mode, capture_on_play=False, extracted helper functions.
- [x] **Task 7.3: Rewrite `animation.py`.** Removed `omni.behavior.scripting.core` from explicit extension list, clean IRA/fallback paths.
- [x] **Task 7.4: Rewrite `behaviors/worker_patrol.py`.** Clean imports, docstring with exposed attribute docs.
- [x] **Task 7.5: Rewrite `behaviors/worker_idle_pose.py`.** Clean imports, docstring with exposed attribute docs.
- [x] **Task 7.6: Rewrite `workers.py`.** Updated `apply_semantics` → `apply_usd_semantics`, removed unused imports.
- [x] **Task 7.7: Rewrite `semantics.py`.** Renamed `apply_semantics` → `apply_usd_semantics`, added docstrings.
- [x] **Task 7.8: Rewrite `warehouse.py`.** Updated import to `apply_usd_semantics`.
- [x] **Task 7.9: Rewrite `spawner.py`.** Added docstrings, no API changes needed.
- [x] **Task 7.10: Rewrite `camera.py`.** Moved `rep` import to top level, added docstrings.
- [x] **Task 7.11: Rewrite `lighting.py`.** Added docstring, no API changes needed.
- [x] **Task 7.12: Rewrite `config_loader.py`.** Added docstring, no API changes needed.
- [x] **Task 7.13: Update `__init__.py`.** Updated `apply_semantics` → `apply_usd_semantics` export.
- [x] **Task 7.14: Update `run_pipeline.sh`.** Added `--/exts/isaacsim.core.throttling/enable_async=false` flag.
- [x] **Task 7.15: Update `coco_to_yolo.py`.** Updated help text from BasicWriter → CocoWriter.
- [x] **Task 7.16: Update `AGENTS.md`.** Updated architecture diagram, gotchas (CocoWriter, isaacsim.core.api, IRA-only, DLSS, async flag).
- [x] **Task 7.17: Update `TODO.md`.** Added Phase 7 tracking.
- [ ] **Task 7.18: Rebuild RAG Index.** Run `python3 -m rag_system.build_index` on the pod.
- [ ] **Task 7.19: Syntax Validation.** Run `python3 -m py_compile` on all modified files.

#### Phase 8: Switch to IRA Built-in Behavior + AgentManager Command Injection
- [x] **Task 8.1: Delete Custom Behavior Scripts.** Removed `behaviors/worker_patrol.py` and `behaviors/worker_idle_pose.py`.
- [x] **Task 8.2: Rewrite `animation.py`.** IRA built-in `character_behavior.py` via `CharacterUtil.setup_python_scripts_to_character()`. Phase 1: attach before play. Phase 2: inject GoTo/Idle/LookAround via `AgentManager.inject_command()`.
- [x] **Task 8.3: Update `main.py`.** Added `inject_worker_commands()` after timeline.play() + warmup.
- [x] **Task 8.4: Update `AGENTS.md`.** Architecture + gotchas updated.
- [x] **Task 8.5: Write IRA Reference Guide.** `references/ira_people_animation_guide.md`.
- [x] **Task 8.6: Syntax Validation.** Run `python3 -m py_compile` on all modified files.
- [x] **Task 8.7: RunPod Test.** Execute pipeline and verify workers move via IRA navmesh.

---

#### Phase 9: Yeni React Frontend Entegrasyonu (VisionForge)
> Gradio tabanlı eski `ui/app.py` artık aktif değil. Yeni frontend `grad-project-front` reposunda;
> DigitalOcean Droplet'te nginx ile statik olarak servis ediliyor (`https://www.visionforge.tech`).
> Bu phase'de `api/server.py` yeni frontend'in beklediği API sözleşmesine uyarlanıyor.

- [x] **Task 9.1: `/run` endpoint.** `api/server.py` — mevcut `POST /generate` endpoint'ini kaldır (veya eski adla bırak, yeni `/run` endpoint'i ekle). Body: `{prompt, preset, frames, labels}`. `X-NIM-API-Key` header'ı oku, yoksa `HTTP 400` dön. Arka planda pipeline'ı başlat, anında `{jobId, status: "queued"}` dön (HTTP 202).
- [x] **Task 9.2: `/status/{jobId}` endpoint.** `api/server.py` — `GET /status/{job_id}`: `{jobId, status, progress, message, resultUrl}` döndür. Status değerleri: `queued | running | completed | failed`. `resultUrl` tamamlandığında `tar.gz` download URL'ini göstermeli.
- [x] **Task 9.3: Job store.** `api/server.py` — Şimdilik in-memory dict yeterli (`jobs: dict`). İleride Redis'e taşınabilir. Job kaydı: `{status, progress, message, resultUrl}`.
- [x] **Task 9.4: CORS güncelle.** `api/server.py` — `allow_origins` listesine `"https://www.visionforge.tech"` ve `"http://localhost:5173"` ekle. `allow_headers=["*"]` — `X-NIM-API-Key` custom header'ı için şart. `allow_origins=["*"]` KULLANMA (custom header'lı preflight'ı bloklar).
- [x] **Task 9.5: `.env.example` güncelle.** `GEMINI_API_KEY` satırını kaldır (NIM key artık header'dan geliyor). `ACCEPT_EULA`, `DROPLET_API_KEY` bırak.
- [x] **Task 9.6: `FRONTEND_INTEGRATION.md` referans al.** `AGENTS.md`'ye `docs/FRONTEND_INTEGRATION.md`'yi referans olarak ekle.

---

#### Phase 10: NIM LLM Migration & Fallback Sistemi
> `llm_pipeline/generator.py` Gemini tabanlıydı. NVIDIA NIM'e geçildi (OpenAI-uyumlu API,
> `https://integrate.api.nvidia.com/v1`). API key artık env var değil — her istekle birlikte
> frontend'den `X-NIM-API-Key` header'ı üzerinden runtime'da geliyor.
> NIM'e yoğun talep geldiğinde tek modele bağımlılık pipeline'ı durdurur; fallback sistemi şart.

- [x] **Task 10.1: Generator imzasını güncelle.** `llm_pipeline/generator.py` — `generate_scene_config(prompt: str, nim_api_key: str) -> SceneConfig`. `os.getenv("NIM_API_KEY")` veya `GEMINI_API_KEY` kullanımını kaldır; anahtar parametre olarak gelsin.
- [x] **Task 10.2: Primary model — Mistral Nemotron.** `generate_scene_config` içinde önce `mistralai/mistral-nemotron` dene. OpenAI SDK ile streaming:
  ```python
  from openai import OpenAI
  client = OpenAI(base_url="https://integrate.api.nvidia.com/v1", api_key=nim_api_key)
  completion = client.chat.completions.create(
      model="mistralai/mistral-nemotron",
      messages=[...], temperature=0.6, top_p=0.7, max_tokens=4096, stream=True
  )
  ```
- [x] **Task 10.3: Fallback 1 — Step 3.5 Flash.** `mistral-nemotron` 429/503/timeout verirse `stepfun-ai/step-3.5-flash` dene. `reasoning_content` alanını da işle (`chunk.choices[0].delta.reasoning_content`). `max_tokens=16384`.
- [x] **Task 10.4: Fallback 2 — Llama 4 Maverick.** `step-3.5-flash` de başarısız olursa `meta/llama-4-maverick-17b-128e-instruct` dene. `requests` + SSE streaming:
  ```python
  import requests
  headers = {"Authorization": f"Bearer {nim_api_key}", "Accept": "text/event-stream"}
  payload = {"model": "meta/llama-4-maverick-17b-128e-instruct", "messages": [...], "stream": True}
  response = requests.post("https://integrate.api.nvidia.com/v1/chat/completions", headers=headers, json=payload)
  for line in response.iter_lines():
      if line: process_sse_line(line.decode("utf-8"))
  ```
- [x] **Task 10.5: Retry + exponential backoff.** Her model için max 2 deneme, aralarında 2^attempt saniyelik bekleme. Tüm modeller başarısız olursa `NIMUnavailableError` fırlat; `api/server.py` bunu yakalar, job'u `failed` olarak işaretle.
- [x] **Task 10.6: Instructor entegrasyonu koru.** NIM modelleriyle `instructor` kütüphanesi `SceneConfig` Pydantic validation'ını sürdürmeli. `instructor.patch(client)` OpenAI SDK path'inde çalışır; Maverick `requests` path'i için JSON parse fallback yaz.
- [x] **Task 10.7: `api/server.py` entegrasyonu.** `/run` endpoint'i, header'dan okunan `nim_api_key`'i `generate_scene_config(..., nim_api_key=nim_api_key)` çağrısına ilet.
- [x] **Task 10.8: Test.** Geçersiz API key → 400. Geçerli key + Mistral yanıt veriyor → SceneConfig üretildi. Mistral 503 → Fallback chain tamamlanıyor. Üç model de 503 → job `failed`.
