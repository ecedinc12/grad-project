# Codebase Logic Updates & Bug Fixes

## 1. Data Writer (`scripts/data_writer.py`)

- [ ] **Fix Blocking I/O:** The `write()` method performs synchronous disk I/O (image saving, JSON dumping) inside the simulation loop.
    - *Impact:* severe performance degradation (FPS drop).
    - *Fix:* Offload writing to a separate `ThreadPoolExecutor` or queue system.
- [ ] **Dynamic Resolution Handling:** `_write_kitti_annotations` defaults to 1920x1080 if width/height are missing from annotator data.
    - *Impact:* Bounding box clamping will be incorrect if the user changes resolution in `generation_config.yaml`.
    - *Fix:* Extract resolution from the corresponding RGB image shape dynamically.
- [ ] **Backend Data Access:** The script assumes `rgb_data["data"]` is a numpy array.
    - *Impact:* specific Replicator backends return GPU tensors or pointers.
    - *Fix:* Implement `BackendDispatch` pattern or explicitly ensure data is moved to CPU/Numpy before processing.
- [ ] **KITTI Format Compliance:** Hardcoded string formatting might miss specific float precision requirements for some parsers.
    - *Fix:* Standardize formatting.

## 2. Domain Randomizer (`scripts/domain_randomizer.py`)

- [ ] **Replicator Graph Memory Leak:** `randomize_materials` creates a new Replicator graph node every time it is called inside the simulation loop.
    - *Impact:* Exploding memory usage (Graph bloat) causing crash after few hundred frames.
    - *Fix:* Refactor to define the Replicator graph *once* during initialization with a `rep.trigger.on_frame` trigger, or use direct USD API calls for material swapping if imperative logic is required.
- [ ] **Distractor Instantiation Overhead:** `spawn_distractors` creates and deletes primitives repeatedly.
    - *Impact:* Performance hitches and potential Physics engine crashes due to deleting rigid bodies during simulation.
    - *Fix:* Implement "Object Pooling" (create N distractors at startup, toggle `visibility` or move to infinity when not needed).
- [ ] **Kinematic Static Logic:** Distractors are set to `Kinematic=True` but never moved after spawning.
    - *Impact:* They act as static walls rather than dynamic visual noise.
    - *Fix:* Apply random velocity or keyframed motion, or switch to dynamic rigid bodies with 0 gravity.
