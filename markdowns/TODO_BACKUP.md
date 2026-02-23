# Technical Implementation Plan (TODO)

> **Reference:** [task.md](./task.md) | [spec.md](./spec.md)

## 1. Infrastructure Initialization
- [x] **Environment Validation** (`scripts/validate_environment.py`)
    - [x] Execute `isaac-sim.sh --headless` to verify headless boot.
    - [x] Validate GPU access via `torch.cuda.is_available()`.
    - [x] Confirm `omni.isaac.core` and `omni.replicator.core` importability.
- [x] **Project Skeleton Generation**
    - [x] Generate directory structure (scripts/, assets/, config/, output/).
    - [x] Initialize `config/generation_config.yaml`.

## 2. Environment & Asset Pipeline
- [x] **Base Scene Construction (`scripts/scene_builder.py`)**
    - [x] Implement `create_stage()`.
    - [x] Setup default lighting: Dome Light + Distant Light.
    - [x] Configure PhysicsScene for GPU dynamics (MBP/TGS).
    - [x] Implement `create_industrial_floor()` with collisions.
- [ ] **Asset Ingestion & Optimization**
    - [ ] **Map Default Nucleus Assets:** Identify paths for built-in Isaac Sim assets (e.g., `omniverse://localhost/NVIDIA/Assets/DigitalTwin/Assets/Warehouse/`).
    - [ ] **Instancing Strategy:** Verify `SceneBuilder.add_asset_instance` handles Nucleus paths correctly.
    - [ ] **Character Integration:**
        - [x] `WorkerController` class structure defined.
        - [ ] Link actual `UsdSkel` assets to the controller.
        - [ ] Verify PPE toggle logic against actual asset hierarchy (`Helmet`, `Vest` Xforms).

## 3. Simulation Logic & Orchestration
- [x] **Navigation System (`scripts/scenario_runner.py`)**
    - [x] Create `WorkerController` class (States: `IDLE`, `WALK`).
    - [x] Implement basic linear movement logic.
- [x] **Hazard Scripting**
    - [x] **PPE Compliance:** Boolean toggles implemented in `WorkerController`.
    - [x] **Geofence Breach:** `ScenarioRunner` checks worker coordinates against hazard bounds.
- [ ] **Negative Sample Generator**
    - [ ] Implement `spawn_empty_variant()`: Logic to disable workers/hazards for 10-15% of frames.
    - [ ] Inject `{"is_negative": True}` into annotation metadata.
- [ ] **Physics Triggers**
    - [ ] Setup Collision Callbacks for "Near Miss" events (using `omni.isaac.core.physics`).

## 4. Sensor & Replicator Configuration (URGENT: Missing `scripts/data_writer.py`)
- [ ] **Sensor Configuration**
    - [ ] **RGB:** Configure `omni.isaac.sensor.Camera` for standard output.
- [ ] **Camera Rigging**
    - [ ] Instantiate `CameraRig` class.
    - [ ] **Orbit Logic:** Implement spherical coordinate sampler ($R, \theta, \phi$).
    - [ ] Randomize Focal Length (18mm - 85mm).
- [ ] **Annotator Registry (Omni.Replicator)**
    - [ ] Register `bounding_box_2d_tight`, `semantic_segmentation`.
    - [ ] Map semantic labels: `class: worker`, `class: forklift`, `class: helmet`, `class: no_helmet`.
- [ ] **Writer Implementation**
    - [ ] Create `scripts/data_writer.py`.
    - [ ] Implement custom Writer inheriting from `omni.replicator.core.Writer`.
    - [ ] Ensure VRAM safety (step clearing).

## 5. Domain Randomization (URGENT: Missing `scripts/domain_randomizer.py`)
- [ ] **Visual DR**
    - [ ] **Lighting:** Randomize Dome Light intensity/rotation.
    - [ ] **Materials:** `omni.replicator.core.randomizer.materials` on background props.
- [ ] **Scene DR**
    - [ ] **Distractors:** Spawn flying primitives (cubes/spheres) to test occlusion.
    - [ ] **Pose:** Randomize rotation/scale of static assets.

## 6. Execution & Validation
- [ ] **Batch Runner**
    - [ ] CLI wrapper: `python scripts/headless_runner.py` (Main Entry Point).
    - [ ] Integration: Connect `SceneBuilder`, `ScenarioRunner`, and `DataWriter`.
- [ ] **Quality Assurance**
    - [ ] Script `scripts/validate_dataset.py` to check output JSON/PNG.
    - [ ] Verify BBox coordinates and class balance.
