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
