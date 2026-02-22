# Project Specification: Synthetic Data Generation Pipeline

> **Related Documentation:** [instructions.md](./instructions.md) | [task.md](./task.md)

## Overview
Develop a high-fidelity synthetic data generation pipeline for industrial safety applications using NVIDIA Isaac Sim / Omniverse. The system will generate labeled datasets for training computer vision models to detect hazardous events and PPE compliance.

## Core Objectives
- **Photorealism:** Minimize sim-to-real gap through high-quality assets and rendering.
- **Physics Fidelity:** Realistic rigid/soft body dynamics for accident simulation.
- **Scalability:** Procedural generation of environments and scenarios.
- **Auto-Labeling:** Precise ground truth generation (Bounding Boxes, Segmentation, Keypoints).

---

## Technical Architecture

### 1. Environment (Digital Twin)
- **Format:** USD (Universal Scene Description)
- **Assets:** Industrial machinery, warehouse racking, forklifts, workers, safety barriers.
- **Zones:**
    - Factory Floor
    - Logistics/Warehouse Hub
    - Construction Zone

### 2. Scenario Scripting (Python/Omni.kit)
- **Hazardous Events:**
    - PPE Non-compliance (e.g., Worker without helmet/vest)
    - Geofence Breaches (Human in hazardous machine zone)
    - Vehicle-Pedestrian proximity (Forklift collision near-miss)
    - Falling Objects
- **Dynamics:** Physics-based interactions (collisions, gravity).

### 3. Domain Randomization (DR)
- **Visual:** Lighting conditions, texture variations, camera noise/blur.
- **Scene:** Asset position/rotation/scale, distractor objects.

### 4. Sensor Configuration

| Sensor | Resolution | FPS | FOV | Notes |
|--------|------------|-----|-----|-------|
| RGB Camera | 1920×1080 | 30 | 60° horizontal | Primary detection sensor |

**Focal Length Range:** 18mm - 85mm (35mm full-frame equivalent)

### 5. Data Output
- **Annotation Formats:** KITTI, COCO, VOC, or custom JSON.
- **Output Directory Structure:**
```
output/
├── rgb/
│   └── {scene_id}_{frame_id}.png
├── depth/
│   └── {scene_id}_{frame_id}.exr
├── annotations/
│   ├── coco_annotations.json
│   └── kitti/
│       └── {scene_id}_{frame_id}.txt
└── metadata/
    └── generation_config.json
```

---

## Dataset Composition Strategy (ML Training Optimization)

To ensure robust model generalization and minimize false positives:

| Category | Target % | Description |
|----------|----------|-------------|
| Negative Samples | 10-15% | Empty scenes, no target objects |
| Easy (100% visible) | 40-50% | Clear, unoccluded targets |
| Hard (60-80% occluded) | 30-40% | Partially hidden by machinery/racking |
| Edge Cases | 5-10% | Unusual angles, lighting extremes |

**Multi-Scale & Resolution:**
- Randomize camera focal length (18mm - 85mm, 35mm equivalent) to simulate varied sensor qualities.
- Primary output: 1080p. Augmentation resizing during training.

**Viewpoint Diversity:** Hemispherical Sampling (Orbit Camera) to prevent viewpoint overfitting.

---

## Hardware Optimization Strategy (RTX 3070 Ti - 8GB VRAM)

**Constraint:** 8GB VRAM is tight for photorealistic industrial twins.

### Estimated VRAM Budget

| Component | Estimated VRAM | Notes |
|-----------|----------------|-------|
| Base Scene | 1.5 - 2.0 GB | Environment geometry |
| Textures (compressed) | 1.5 - 2.5 GB | 2K max, DDS/BC7 compression |
| Character Models | 0.5 - 1.0 GB | Per active worker |
| Ray Tracing Buffers | 1.0 - 2.0 GB | BVH + denoising |
| Render Targets | 0.5 - 1.0 GB | RGB + Depth framebuffers |
| **Headroom** | **~1 GB** | For stability |

### Mitigation Protocol
- **Asset Hygiene:** Use "Game-Ready" assets (<50k tris). Texture Compression (DDS/BC7). Max texture resolution: 2K.
- **Instancing:** Heavily utilize USD Point Instancing for repetitive objects (pallets, screws, racking).
- **Rendering:**
    - Prioritize **RTX Real-Time** mode for standard checks.
    - Use **Interactive Path Tracing** only for final ground truth, with aggressive denoising (OptiX).
    - **Sequential Sensor Capture:** If VRAM saturates, toggle sensors on/off sequentially.
- **Execution:** Mandatory **Headless Mode** (no GUI) for all data generation scripts.

---

## Dependencies & Requirements

### Software Requirements

| Component | Version | Notes |
|-----------|---------|-------|
| NVIDIA Isaac Sim | 4.2.0+ | Primary simulation engine |
| Omniverse Launcher | Latest | For Isaac Sim installation |
| Python | 3.10.x | Isaac Sim embedded Python |
| CUDA | 12.x | GPU acceleration |
| Driver | 535+ | NVIDIA GPU driver |

### Python Packages (via Isaac Sim)
```
omni.isaac.core
omni.isaac.sensor
omni.replicator.core
omni.isaac.kit
numpy>=1.24.0
pillow>=9.0.0
```

### Asset Sources
| Source | URL | Asset Types |
|--------|-----|-------------|
| NVIDIA Omniverse Assets | [NVIDIA Assets](https://developer.nvidia.com/omniverse) | Characters, industrial props |
| Sketchfab | [Sketchfab](https://sketchfab.com) | Machinery, environment props |
| TurboSquid | [TurboSquid](https://turbosquid.com) | High-quality industrial assets |
| Mixamo | [Mixamo](https://mixamo.com) | Character animations |

---

## Milestones

> **Note:** Detailed task tracking in [task.md](./task.md)

1. Basic Scene Setup & Asset Ingestion
2. Character & Animation Integration
3. Hazard Scenario Scripting
4. Domain Randomization Implementation
5. Sensor Configuration & Writer Implementation
6. Batch Generation & Validation
