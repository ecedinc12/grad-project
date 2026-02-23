# Technical Execution Plan (Detailed)

> **Directive:** All tasks must be implemented with strict type-safety, explicit error handling for Isaac Sim edge cases, and VRAM awareness.

## Phase 1: Core Systems (Refinement) - COMPLETED

### 1.1 Config & Initialization
- [x] **Refine `config/generation_config.yaml`**
    - **Schema:** Created with all required fields.
    - **Logic Check:** Path concatenation handled via string formatting with proper stripping.
    - **Validation:** Updated `validate_environment.py` to parse YAML and check connectivity to `nucleus_server` using `omni.client.stat`.

### 1.2 Asset Integration (Hardening)
- [x] **Update `scripts/scene_builder.py` for Robust Asset Loading**
    - **Task:** Implemented `add_asset_from_nucleus(path_suffix)` wrapper with retry logic.
    - **Error Prevention:**
        - *Issue:* Nucleus server might be slow or disconnected.
        - *Fix:* Wrapped `add_reference_to_stage` in a retry loop (3 attempts) with `time.sleep`.
        - *Issue:* Invalid USD paths cause silent failures or pink placeholders.
        - *Fix:* Uses `omni.client.stat(url)` to verify file existence before attempting to reference.

## Phase 2: Domain Randomization & Sensor Pipeline (New Modules) - COMPLETED

### 2.1 Domain Randomizer (`scripts/domain_randomizer.py`)
- [x] **Class Structure Implementation**
    - **Task:** Created `DomainRandomizer` class initialized with `Usd.Stage`.
    - **Method:** `randomize_lights(intensity_range: tuple, color_temp_range: tuple)`
        - *Logic:* Iterates over `UsdLux.DomeLight` and `UsdLux.DistantLight`.
        - *Constraint:* Ensures intensity >= 0.
    - **Method:** `randomize_materials(prim_paths: List[str])`
        - *Logic:* Uses `omni.replicator.core.randomizer.materials`.
        - *Pitfall:* Recursively traverses children to find `UsdGeom.Mesh` prims before applying materials.
    - **Method:** `spawn_distractors(n=5)`
        - *Logic:* Creates primitives (Cube, Sphere, Cone) in "/World/Distractors/" scope.
        - *Physics:* Sets `rigid_body_enabled=True` and `kinematic_enabled=True`.
        - *Cleanup:* Implemented `clear_distractors()` method to destroy prims and prevent VRAM leaks.

### 2.2 Data Writer (`scripts/data_writer.py`)
- [x] **Replicator Writer Implementation**
    - **Task:** Created `SafetyDatasetWriter` inheriting from `omni.replicator.core.Writer`.
    - **Constructor:** Accepts `output_dir`, `class_mapping` (dict).
    - **Annotators:**
        - Initializes `rgb`, `bounding_box_2d_tight`, `semantic_segmentation`.
        - *Pitfall:* Asynchronous operation handled by calling `rep.orchestrator.step()` in main loop.
    - **Serialization (Write to Disk):**
        - *Format:* KITTI text files implemented; COCO placeholder.
        - *Coordinate System:* Uses pixel coordinates (0-W, 0-H).
        - *Safety Check:* Verifies BBox area > 0; discards microscopic boxes (<5x5 px).
        - *Metadata:* Includes `is_negative_sample`, `camera_pose`, `time_of_day`.
    - **Backend:** Uses atomic writes (temp file + rename) to prevent corruption.

## Phase 3: Orchestration & Main Loop - COMPLETED

### 3.1 Headless Runner (`scripts/headless_runner.py`)
- [x] **Main Entry Point Logic**
    - **Task:** Created `HeadlessRunner` class that orchestrates all components.
    - **Flow:**
        1. Initializes `SimulationApp({"headless": True})` as first import.
        2. Imports `World` from `omni.isaac.core`.
        3. Instantiates `SceneBuilder`, builds stage.
        4. Instantiates `ScenarioRunner`.
        5. Instantiates `DomainRandomizer`.
        6. Instantiates `SafetyDatasetWriter` and registers with Replicator.
    - **Loop Structure:** Implemented exactly as specified with physics, logic, randomization, render/write steps.
    - **Error Handling:** Wrapped in `try...except` with proper cleanup on `KeyboardInterrupt`, `CUDA out of memory`, or other exceptions.

## Phase 4: Quality Control Scripting

### 4.1 Dataset Validation (`scripts/validate_dataset.py`)
- [ ] **Post-Process verification**
    - **Task:** Standalone script (no Isaac Sim dependency) to verify output.
    - **Checks:**
        1. **Pairing:** Every `.png` has a corresponding `.json` or `.txt`.
        2. **Bounds:** Load image and draw BBox. If BBox is outside image dimensions, flag error.
        3. **Empty Frames:** If `is_negative=False` but JSON has 0 objects -> ERROR.
        4. **Black Frames:** Compute mean pixel intensity. If < 5 (out of 255), flag as "Black Frame Error" (common rendering glitch).
