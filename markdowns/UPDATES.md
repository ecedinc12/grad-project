# Codebase Logic Updates & Bug Fixes

## 1. Data Writer (`scripts/data_writer.py`)

- [x] **Fix Blocking I/O:** The `write()` method performs synchronous disk I/O (image saving, JSON dumping) inside the simulation loop.
    - *Impact:* severe performance degradation (FPS drop).
    - *Fix:* Offload writing to a separate `ThreadPoolExecutor` or queue system.
- [x] **Dynamic Resolution Handling:** `_write_kitti_annotations` defaults to 1920x1080 if width/height are missing from annotator data.
    - *Impact:* Bounding box clamping will be incorrect if the user changes resolution in `generation_config.yaml`.
    - *Fix:* Extract resolution from the corresponding RGB image shape dynamically.
- [x] **Backend Data Access:** The script assumes `rgb_data["data"]` is a numpy array.
    - *Impact:* specific Replicator backends return GPU tensors or pointers.
    - *Fix:* Implement `BackendDispatch` pattern or explicitly ensure data is moved to CPU/Numpy before processing.
- [x] **KITTI Format Compliance:** Hardcoded string formatting might miss specific float precision requirements for some parsers.
    - *Fix:* Standardize formatting.

## 2. Domain Randomizer (`scripts/domain_randomizer.py`)

- [x] **Replicator Graph Memory Leak:** `randomize_materials` creates a new Replicator graph node every time it is called inside the simulation loop.
    - *Impact:* Exploding memory usage (Graph bloat) causing crash after few hundred frames.
    - *Fix:* Refactor to define the Replicator graph *once* during initialization with a `rep.trigger.on_frame` trigger, or use direct USD API calls for material swapping if imperative logic is required.
- [x] **Distractor Instantiation Overhead:** `spawn_distractors` creates and deletes primitives repeatedly.
    - *Impact:* Performance hitches and potential Physics engine crashes due to deleting rigid bodies during simulation.
    - *Fix:* Implement "Object Pooling" (create N distractors at startup, toggle `visibility` or move to infinity when not needed).
- [x] **Kinematic Static Logic:** Distractors are set to `Kinematic=True` but never moved after spawning.
    - *Impact:* They act as static walls rather than dynamic visual noise.
    - *Fix:* Apply random velocity or keyframed motion, or switch to dynamic rigid bodies with 0 gravity.

## 3. Scenario Runner (`scripts/scenario_runner.py`)

- [x] **Teleportation vs Physics:** `WorkerController.update` uses `set_world_pose` to move workers.
    - *Impact:* Breaks physics collisions (tunneling) and momentum calculations.
    - *Fix:* Implemented atomic `_set_transform` which resets rigid body velocities to prevent explosions during kinematic updates.
- [x] **Ghost Collisions (PPE):** `toggle_ppe` only changes visibility.
    - *Impact:* Invisible helmets/vests still have active colliders, causing objects to bounce off "thin air".
    - *Fix:* Toggles `UsdPhysics.CollisionAPI.collisionEnabled` alongside visibility.
- [x] **Transform Race Condition:** `_set_position` and `_set_rotation_z` independently query and set transforms.
    - *Impact:* Potential jitter or overriding of updates if called sequentially in the same frame.
    - *Fix:* Merged into single `_set_transform` call in update loop.

## 4. Scene Builder (`scripts/scene_builder.py`)

- [x] **Instance Tracking Logic:** `add_asset_from_nucleus` fails to append new instance paths to `self._asset_instances` after the first instance is created.
    - *Impact:* Incomplete registry of assets, making it impossible to randomize or manage instances later in the pipeline.
    - *Fix:* Add `self._asset_instances[full_url].append(prim_path)` in the instance creation block.
- [x] **Gravity vs Up-Axis Mismatch:** `setup_physics` defaults to Z-up gravity `(0,0,-9.81)` even if the stage is configured as Y-up.
    - *Impact:* Physics will pull objects "sideways" if the coordinate system doesn't match the default.
    - *Fix:* Dynamically check `UsdGeom.GetStageUpAxis` or enforce consistency.
- [x] **Fragile URL Parsing:** `split("/", 3)` on `omniverse://` URIs is unreliable for extracting path suffixes.
    - *Impact:* Asset loading failures if the Nucleus URL format varies slightly (e.g. localhost vs IP).
    - *Fix:* Use `omni.client.break_url` for safe parsing.

## 5. Headless Runner (`scripts/headless_runner.py`)

- [x] **Double Stepping Physics:** The main loop calls both `self.world.step(render=False)` and `rep.orchestrator.step()`.
    - *Impact:* Physics simulation advances twice per frame generation. `rep.orchestrator.step()` is designed to handle the stepping when data acquisition is active. This causes synchronization issues between the "physics state" (hazards) and the "rendered state" (images).
    - *Fix:* Use `rep.orchestrator.step()` as the primary stepping mechanism during data generation.
- [x] **Broken Frame Counter:** `self.frame_count` is never incremented inside the generation loop.
    - *Impact:* Final FPS and frame count statistics are 0.
    - *Fix:* Increment `self.frame_count` inside the loop.
- [x] **Global Side Effects:** `SimulationApp` is instantiated at the module level, and `shutdown()` closes it.
    - *Impact:* Difficult to unit test `HeadlessRunner` class without launching a full simulation instance.
    - *Fix:* Isolate `SimulationApp` lifecycle to the `main()` block or use a singleton pattern that respects existing instances.
