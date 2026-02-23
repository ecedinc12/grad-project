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
