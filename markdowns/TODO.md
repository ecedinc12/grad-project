# Technical Execution Plan (Detailed)

> **Directive:** All tasks must be implemented with strict type-safety, explicit error handling for Isaac Sim edge cases, and VRAM awareness.

## Phase 1: Core Systems (Refinement)

### 1.1 Config & Initialization
- [ ] **Refine `config/generation_config.yaml`**
    - **Schema:**
        ```yaml
        output:
          base_dir: "output/dataset_v1"
          resolution: [1920, 1080]
          format: "png"
        assets:
          nucleus_server: "omniverse://localhost"
          worker_usd: "/NVIDIA/Assets/Characters/Reallusion/Worker_Standard.usd"
          prop_root: "/NVIDIA/Assets/DigitalTwin/Assets/Warehouse/Safety"
        camera:
          focal_length_range: [18.0, 85.0]
          orbit_radius: [5.0, 15.0]
          elevation_range: [15, 75]
        ```
    - **Logic Check:** Ensure path concatenation handles trailing slashes correctly (`os.path.join` vs manual string formatting).
    - **Validation:** Update `validate_environment.py` to parse this YAML and check connectivity to `nucleus_server` using `omni.client.stat`.

### 1.2 Asset Integration (Hardening)
- [ ] **Update `scripts/scene_builder.py` for Robust Asset Loading**
    - **Task:** Implement `add_asset_from_nucleus(path_suffix)` wrapper.
    - **Error Prevention:**
        - *Issue:* Nucleus server might be slow or disconnected.
        - *Fix:* Wrap `add_reference_to_stage` in a retry loop (3 attempts) with `time.sleep`.
        - *Issue:* Invalid USD paths cause silent failures or pink placeholders.
        - *Fix:* Use `omni.client.stat(url)` to verify file existence *before* attempting to reference it. Raise `FileNotFoundError` immediately if missing.

## Phase 2: Domain Randomization & Sensor Pipeline (New Modules)

### 2.1 Domain Randomizer (`scripts/domain_randomizer.py`)
- [ ] **Class Structure Implementation**
    - **Task:** Create `DomainRandomizer` class initialized with `Usd.Stage`.
    - **Method:** `randomize_lights(intensity_range: tuple, color_temp_range: tuple)`
        - *Logic:* Iterate over `UsdLux.DomeLight` and `UsdLux.DistantLight`.
        - *Constraint:* Do not set intensity < 0.
    - **Method:** `randomize_materials(prim_paths: List[str])`
        - *Logic:* Use `omni.replicator.core.randomizer.materials`.
        - *Pitfall:* Applying materials to Xforms instead of Mesh prims often fails in USD.
        - *Fix:* Recursively traverse children of `prim_paths` to find type `UsdGeom.Mesh` before applying material actions.
    - **Method:** `spawn_distractors(n=5)`
        - *Logic:* Create primitives (Cube, Sphere, Cone) in a specific "Distractor" scope.
        - *Physics:* Set `rigid_body_enabled=True` but `kinematic_enabled=True` so they float/rotate but don't fall.
        - *Cleanup:* Implement a `clear_distractors()` method to destroy these prims at the end of a frame to prevent VRAM accumulation (memory leak).

### 2.2 Data Writer (`scripts/data_writer.py`)
- [ ] **Replicator Writer Implementation**
    - **Task:** Create `SafetyDatasetWriter` inheriting from `omni.replicator.core.Writer`.
    - **Constructor:** Accept `output_dir`, `class_mapping` (dict).
    - **Annotators:**
        - Initialize `rgb`, `bounding_box_2d_tight`, `semantic_segmentation`.
        - *Pitfall:* Replicator annotators run asynchronously.
        - *Fix:* Ensure `rep.orchestrator.step()` is called in the main loop, not inside the writer.
    - **Serialization (Write to Disk):**
        - *Format:* Kitti-like text files or custom JSON.
        - *Coordinate System:* Normalize BBox (0-1) vs Pixel Coords (0-W, 0-H). **Decision: Use Pixel Coordinates.**
        - *Safety Check:* Verify BBox area > 0 before writing. Discard microscopic boxes (<5x5 px).
        - *Metadata:* Include `is_negative_sample`, `camera_pose`, `time_of_day`.
    - **Backend:** use `backend.write_data` standard pattern to prevent blocking the rendering thread.

## Phase 3: Orchestration & Main Loop

### 3.1 Headless Runner (`scripts/headless_runner.py`)
- [ ] **Main Entry Point Logic**
    - **Task:** Glue everything together.
    - **Flow:**
        1. Initialize `SimulationApp({"headless": True})`. **CRITICAL: Must be first import.**
        2. `from omni.isaac.core import World`.
        3. Instantiate `SceneBuilder`, build stage.
        4. Instantiate `ScenarioRunner`.
        5. Instantiate `DomainRandomizer`.
        6. Instantiate `DataWriter` (Replicator).
    - **Loop Structure:**
        ```python
        for i in range(total_frames):
            # 1. Physics Step
            scenario_runner.update(dt)
            world.step(render=False) 
            
            # 2. Logic Step (Hazard triggers)
            hazards = scenario_runner.check_hazards()
            
            # 3. Randomization Step
            domain_randomizer.randomize_frame()
            
            # 4. Render & Write
            # Force render logic for replicator
            rep.orchestrator.step() 
            
            # 5. Cleanup (Optional but recommended for long runs)
            if i % 100 == 0:
                gc.collect() # Python garbage collector
        ```
    - **Error Handling:** Wrap the loop in `try...except` to catch `CUDA out of memory` or `SegFaults`. Save progress/checkpoint on crash.

## Phase 4: Quality Control Scripting

### 4.1 Dataset Validation (`scripts/validate_dataset.py`)
- [ ] **Post-Process verification**
    - **Task:** Standalone script (no Isaac Sim dependency) to verify output.
    - **Checks:**
        1. **Pairing:** Every `.png` has a corresponding `.json` or `.txt`.
        2. **Bounds:** Load image and draw BBox. If BBox is outside image dimensions, flag error.
        3. **Empty Frames:** If `is_negative=False` but JSON has 0 objects -> ERROR.
        4. **Black Frames:** Compute mean pixel intensity. If < 5 (out of 255), flag as "Black Frame Error" (common rendering glitch).
