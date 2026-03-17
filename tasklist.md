


Here is the master vibecoding task list. Copy and paste this directly into your AI IDE (Cursor, Windsurf, or Copilot). It is structured sequentially so the agent builds the foundation before attempting complex Omniverse APIs, preventing context collapse.

### ⚙️ Master Prompt Context (Give this to your Agent first)
> **Role:** You are an expert NVIDIA Isaac Sim, Universal Scene Description (USD), and AI pipeline engineer. 
> **Goal:** Build an industrial safety Synthetic Data Generation (SDG) pipeline.
> **Architecture:** A two-part system. Part 1: An LLM extracts user text into a strict Pydantic/JSON schema. Part 2: A Python backend running inside Isaac Sim parses this JSON to generate environments using `omni.replicator`.
> **Strict Rules:** 
> 1. NEVER write agent-generated Python code that executes live in the simulator. The LLM only outputs JSON.
> 2. IN ALL ISAAC SIM SCRIPTS, `SimulationApp` must be instantiated BEFORE any `omni.*` or `pxr.*` imports.
> 3. Use `omni.replicator.core` for all object placements, randomizations, and rendering. Do not use raw USD transform math.

---

### 📋 Vibecoding Task List

#### Phase 1: Project Scaffolding & Data Structures
- [ ] **Task 1.1: Initialize Workspace.** Create the following directory structure: `llm_pipeline/`, `isaac_backend/`, `assets_registry/`, `configs/`, `output_dataset/`.
- [ ] **Task 1.2: Define Pydantic Schemas.** In `llm_pipeline/schemas.py`, define the strict JSON schema. 
    - Create `PPEState` (booleans for hardhat, vest, glasses).
    - Create `Entity` (type: worker/forklift/zone, asset_id, PPEState, anchor_zone).
    - Create `SceneConfig` (list of entities, lighting time-of-day, camera angle).
- [ ] **Task 1.3: Build Asset Registry.** In `assets_registry/library.json`, map plain English terms to USD paths (e.g., `"forklift": "omniverse://localhost/NVIDIA/Assets/Isaac/2023.1.1/Isaac/Props/Forklift/forklift.usd"`).

#### Phase 2: The LLM "Text-to-Config" Layer
- [ ] **Task 2.1: Setup Instructor LLM.** In `llm_pipeline/generator.py`, use the `instructor` library with a free/efficient model API (e.g., Gemini 2.0 Flash or Groq Llama 3.3). 
- [ ] **Task 2.2: Write the Extraction Prompt.** Create a system prompt that enforces:
    - Translation of spatial terms ("near") into bounding boxes or anchor zone IDs.
    - Defaulting PPE rules (if not mentioned, set `hardhat=True`).
    - Outputting ONLY the `SceneConfig` Pydantic model.
- [ ] **Task 2.3: Config Exporter.** Write a function to save the validated Pydantic model to `configs/current_scene.json`.

#### Phase 3: Isaac Sim Backend Foundation
- [ ] **Task 3.1: Headless Bootstrapper.** In `isaac_backend/main.py`, write the boot sequence. Instantiate `SimulationApp({"headless": True})`. 
- [ ] **Task 3.2: Config Ingestion.** Write a parser in `main.py` that reads `configs/current_scene.json` and loads the `assets_registry/library.json`.
- [ ] **Task 3.3: Replicator Setup.** Import `omni.replicator.core as rep`. Initialize a basic Replicator Writer (e.g., `rep.WriterRegistry.get("BasicWriter")`) and point the output directory to `output_dataset/`.

#### Phase 4: Industrial Safety SDG Logic (The Core)
- [ ] **Task 4.1: Semantic Labeler Component.** Write `apply_semantics(prim, class_name)`. It must use `rep.modify.semantics([("class", class_name)])` to tag workers as `Person` and forklifts as `Vehicle` for the segmentation dataset.
- [ ] **Task 4.2: Geofence & Anchor Component.** Write a function that creates invisible USD Volumes for "Hazard Zones". Use `rep.randomizer.scatter_2d` to spawn assets ONLY within these defined bounds.
- [ ] **Task 4.3: PPE Physics Attacher.** Write a function `attach_ppe(worker_prim, ppe_state)`. 
    - If `hardhat=True`, spawn the hardhat USD.
    - **CRITICAL:** Use `omni.physx` to create a Fixed Joint between the worker's `Head_Bone` and the Hardhat prim so it moves with animations.
- [ ] **Task 4.4: Collision Avoidance Spawner.** Write logic to spawn a worker and vehicle on an intersecting trajectory or near each other, checking `omni.physx` bounds to ensure they don't spawn inside one another (no clipping).

#### Phase 5: Execution & Rendering
- [ ] **Task 5.1: The SDG Loop.** Wrap the scene generation in `with rep.trigger.on_frame(num_frames=50):`. Add camera randomization (slight panning/tilting) to generate varied data from the single text prompt.
- [ ] **Task 5.2: Sensor Setup.** Configure an RGB Camera, Bounding Box 2D Tight, and Semantic Segmentation sensors. Attach them to the Replicator Writer.
- [ ] **Task 5.3: Headless Shell Script.** Create `run_pipeline.sh`. It should:
    1. Run the `llm_pipeline/generator.py` with an arg (e.g., `"spawn a forklift near a worker without a vest"`).
    2. Execute Isaac Sim headless using the generated config: `~/.local/share/ov/pkg/isaac-sim-2023.1.1/python.sh isaac_backend/main.py`.

### 💡 How to use this for Vibecoding:
1. Copy Phase 1 into your IDE. Let the agent build it.
2. Verify the Pydantic schema looks right.
3. Paste Phase 2. Run a test python script to ensure typing "dangerous forklift scene" actually spits out a valid JSON file.
4. Paste Phase 3, 4, and 5 sequentially. 
5. **Never paste the whole list at once**, or the agent will hallucinate Isaac Sim API imports in the LLM pipeline. Keep the environments strictly separated.
