# Tasks

> **Related Documentation:** [spec.md](./spec.md) | [instructions.md](./instructions.md)

## Project Directory Structure
```
grad-project/
├── scripts/
│   ├── scene_builder.py      # Environment construction
│   ├── scenario_runner.py    # Hazard event orchestration  
│   ├── domain_randomizer.py  # DR configuration
│   └── data_writer.py        # Annotation export
├── assets/
│   ├── environments/         # USD scene files
│   ├── characters/           # Worker models + animations
│   └── props/                # Industrial assets (machinery, PPE)
├── config/
│   └── generation_config.yaml
├── output/                   # Generated datasets (gitignored)
├── spec.md
├── task.md
└── instructions.md
```

---

## Task Checklist

### Infrastructure Setup
> **Dependency:** None (start here)

- [ ] **Verify Isaac Sim / Omniverse environment**
    - *Acceptance:* Isaac Sim 4.2+ launches successfully, GPU detected in console
- [ ] **Set up Python environment and dependencies**
    - *Acceptance:* `import omni.isaac.core` succeeds without errors
- [ ] **Create basic project structure**
    - *Acceptance:* All directories in structure above exist

---

### Environment & Assets
> **Dependency:** Infrastructure Setup complete

- [ ] **Construct base industrial environment (walls, floor, lighting)**
    - *Acceptance:* Scene renders without errors, basic shadows visible
- [ ] **Import industrial assets (machinery, racking)**
    - *Acceptance:* ≥5 unique asset types placed, <50k tris each
- [ ] **[OPTIMIZATION] Convert assets to USD Point Instances**
    - *Acceptance:* Repetitive objects (pallets, crates) use instancing, VRAM <4GB for scene
- [ ] **[OPTIMIZATION] Downscale textures to 2K/1K and compress to DDS**
    - *Acceptance:* No texture >2048px, all textures BC7/DDS compressed
- [ ] **Import worker characters and PPE assets (helmets, vests)**
    - *Acceptance:* Character visible with toggleable PPE equipment prims

---

### Simulation Logic
> **Dependency:** Environment & Assets complete

- [ ] **Implement worker navigation/animation graph**
    - *Acceptance:* Character walks predefined path, animation blends correctly
- [ ] **Script PPE compliance toggles (equip/unequip)**
    - *Acceptance:* Script can show/hide helmet/vest prims on command
- [ ] **[ML-CRITICAL] Script "Negative Sample" generator**
    - *Approach:* 
        1. Spawn empty scene variant (no workers/hazards)
        2. Randomize camera position within scene bounds
        3. Capture N frames with `is_negative=True` metadata flag
    - *Acceptance:* Generated images contain zero annotated objects, metadata correctly flagged
- [ ] **Script hazard scenarios (collision, breach)**
    - *Acceptance:* Physics simulation triggers on collision, geofence breach logged

---

### Sensor & Data Pipeline
> **Dependency:** Simulation Logic complete

- [ ] **Configure RGB and Depth cameras**
    - *Acceptance:* Both sensors output to separate directories, correct resolutions per spec
- [ ] **[ML-CRITICAL] Implement Hemispherical/Orbit Camera randomization**
    - *Approach:* Sample camera positions on hemisphere centered on scene, randomize azimuth (0-360°) and elevation (15-75°)
    - *Acceptance:* 100 test frames show diverse viewpoints, no fixed camera angles
- [ ] **Implement Basic Writer (COCO/KITTI format)**
    - *Acceptance:* Output matches COCO JSON schema, bounding boxes validate against ground truth
- [ ] **Test Domain Randomization (lighting, pose)**
    - *Acceptance:* 50 frames show visible lighting variation, asset pose randomization confirmed

---

### Production Run
> **Dependency:** Sensor & Data Pipeline complete

- [ ] **Validate dataset quality**
    - *Quantitative Checks:*
        - [ ] Annotation coverage: >95% of visible objects annotated
        - [ ] Negative sample ratio: 10-15% of dataset
        - [ ] Resolution consistency: All outputs match spec
        - [ ] No corrupt/black frames
    - *Acceptance:* All quantitative checks pass, 10 random samples visually verified
- [ ] **Run full batch generation**
    - *Target:* 10,000 frames across all scenarios
    - *Acceptance:* Generation completes without crash, output size matches expectations
