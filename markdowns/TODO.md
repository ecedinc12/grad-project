# Technical Implementation Plan (TODO)

> **Reference:** [task.md](./task.md) | [spec.md](./spec.md)

## 1. Infrastructure Initialization
- [ ] **Environment Validation**
    - Execute `isaac-sim.sh --headless` to verify headless boot.
    - Validate GPU access via `torch.cuda.is_available()` within the Isaac Sim Python environment.
    - Confirm `omni.isaac.core` and `omni.replicator.core` importability.
- [ ] **Project Skeleton Generation**
    - specific subdirectories: `scripts/`, `assets/environments`, `assets/characters`, `assets/props`, `config/`, `output/`.
    - Initialize `config/generation_config.yaml` with default parameters (resolution: 1920x1080, samples: 100).

## 2. Environment & Asset Pipeline
- [ ] **Base Scene Construction (`scripts/scene_builder.py`)**
    - Implement `create_stage()` using `omni.usr.get_context().new_stage()`.
    - Setup default lighting: Dome Light (HDRI) + distant light for shadows.
    - **Optimization:** Configure PhysicsScene for GPU dynamics (Broadphase: MBP, Solver: TGS).
- [ ] **Asset Ingestion & Optimization**
    - **Geometry:** Import industrial props. Sanitize mesh complexity (<50k tris).
    - **Materials:** Enforce MDL graph conversion.
    - **Instancing:** Implement `omni.isaac.core.prims.GeometryPrim` with `instancer_path` for repetitive assets (pallets, racking).
    - **Texture Compression:** Batch process textures to BC7/DDS using NVTT or equivalent.
- [ ] **Character Integration**
    - Import rigged characters (USD Skel).
    - Verify `SkelAnimation` bindings.
    - Setup "PPE Slots" as toggleable Xforms (parenting helmet/vest meshes to bone attach points).

## 3. Simulation Logic & Orchestration
- [ ] **Navigation System (`scripts/scenario_runner.py`)**
    - Implement `omni.isaac.motion_generation` or simple waypoint interpolation for worker movement.
    - Create `WorkerController` class to manage state: `IDLE`, `WALK`, `HAZARD_INTERACTION`.
- [ ] **Hazard Scripting**
    - **PPE Compliance:** Boolean toggles on PPE visibility attributes.
    - **Negative Samples:** Logic branch to spawn camera in empty zones or disable all actor spawning. Flag metadata `is_negative=True`.
    - **Geofence Breach:** use `omni.isaac.core.utils.prims.get_prim_at_path` to detect worker centroid vs. hazard zone volume.
- [ ] **Physics Triggers**
    - Setup Collision Callbacks for "Near Miss" or "Accident" events.

## 4. Sensor & Replicator Configuration (`scripts/data_writer.py`)
- [ ] **Camera Rigging**
    - Instantiate `CameraRig` class wrapping `omni.isaac.sensor.Camera`.
    - **Orbit Logic:** Implement spherical coordinate sampler (Radius: $R$, Theta: $\theta$, Phi: $\phi$) -> Cartesian ($x,y,z$) transformation for camera placement.
    - Focal Length Randomization: `camera.set_focal_length(random.uniform(18.0, 85.0))`.
- [ ] **Annotator Registry (Omni.Replicator)**
    - Register `bounding_box_2d_tight`, `semantic_segmentation`, `instance_segmentation`.
    - Map semantic labels: `class: worker`, `class: forklift`, `class: helmet`, `class: no_helmet`.
- [ ] **Writer Implementation**
    - Custom Writer inheriting from `omni.replicator.core.Writer`.
    - **Output Structure:**
        - RGB: `.png` (lossless).
        - Annotations: JSON (COCO style).
    - **VRAM Safety:** Implement `replicator.orchestrator.step(rt_subframes=N)` to clear buffers between writes.

## 5. Domain Randomization (DR) (`scripts/domain_randomizer.py`)
- [ ] **Visual DR**
    - **Lighting:** Randomize Dome Light intensity (500-3000 lux) and rotation.
    - **Materials:** `omni.replicator.core.randomizer.materials` on background props.
- [ ] **Scene DR**
    - **Distractors:** Spawn flying geometric primitives (cubes/spheres) with collision disabled to test occlusion robustness.
    - **Pose:** Randomize rotation/scale of static assets $\pm 10\%$.

## 6. Execution & Validation
- [ ] **Batch Runner**
    - CLI wrapper: `python scripts/headless_runner.py --config config/generation_config.yaml`.
    - Error handling: Try/Catch block around `step()` to catch CUDA OOM errors; auto-restart logic.
- [ ] **Quality Assurance**
    - Script `scripts/validate_dataset.py`:
        - Check JSON validity.
        - Check image readability.
        - Verify BBox coordinates $\in [0, W] \times [0, H]$.
