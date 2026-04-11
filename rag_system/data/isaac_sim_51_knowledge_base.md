# Isaac Sim 5.1 RAG Knowledge Base
# Auto-curated documentation for the project's RAG system.
# Source: docs.isaacsim.omniverse.nvidia.com/5.1.0 (Isaac Sim 5.1+ ONLY)

## SimulationApp Headless Startup

CRITICAL RULE: In ALL Isaac Sim scripts, `SimulationApp({"headless": True})` must be
instantiated BEFORE any `omni.*` or `pxr.*` imports. This is the first two lines of any
standalone application:

```python
from isaacsim import SimulationApp
simulation_app = SimulationApp({"headless": True})
# NOW safe to import omni/pxr
import omni.replicator.core as rep
import omni.usd
from isaacsim.core.api import World
from pxr import Gf, UsdGeom, Sdf
```

The SimulationApp object controls the lifecycle of the simulation. When running headlessly
(on a RunPod GPU container), always use `headless=True`.


## Replicator Core API — Overview

Isaac Sim Replicator provides tools for synthetic data generation (SDG) through the
`omni.replicator.core` module (imported as `rep`). Key concepts:

- **Writers**: Serialize annotated data to disk (BasicWriter, KittiWriter, custom)
- **Annotators**: Capture ground-truth data (rgb, bounding_box_2d_tight,
  semantic_segmentation, instance_segmentation, distance_to_camera, etc.)
- **Randomizers**: Domain randomization (pose, color, light, camera position)
- **Triggers**: Control when randomizations fire (`on_frame`, `on_custom_event`)
- **Orchestrator**: Manages the SDG loop (step, run, wait_until_complete)


## BasicWriter Configuration

The BasicWriter is the most common writer for COCO-format output:

```python
writer = rep.WriterRegistry.get("BasicWriter")
writer.initialize(
    output_dir="/tmp/dataset",
    rgb=True,
    bounding_box_2d_tight=True,
    semantic_segmentation=True,
    semantic_segmentation_params={"write_semantic_id_to_labels": True},
    distance_to_camera=True,
    instance_segmentation=True,
    instance_segmentation_params={"write_instance_segmentation_colors": True},
)
writer.attach([render_product])
```

CRITICAL: Write output to `/tmp/dataset` (fast NVMe), not `/workspace` (slow persistent storage).
After generation, compress and move: `tar -czf /workspace/dataset.tar.gz -C /tmp dataset/`


## Camera and Render Product Setup

```python
camera = rep.create.camera(position=(0, 5, 10), look_at=(0, 0, 0))
render_product = rep.create.render_product(camera, (1024, 1024))
```

The render_product is required for attaching writers. Resolution is set at render_product
creation time as `(width, height)`.

### Camera Position Distribution

For synthetic data with varying viewpoints:

```python
with rep.trigger.on_frame(num_frames=200):
    with camera:
        rep.modify.pose(
            position=rep.distribution.uniform((min_x, min_y, min_z), (max_x, max_y, max_z)),
            look_at=(0, 0, 0)
        )
```

You can use `rep.distribution.sequence()` for deterministic camera positions or
`rep.distribution.uniform()` for random sampling within bounds.


## Semantic Labeling

Semantic labels are required for bounding boxes and segmentation outputs. Two approaches:

### Python API (Replicator)

```python
# At spawn time
with prims:
    rep.modify.semantics([("class", "vehicle")])

# After spawning
prims = rep.get.prims(path_pattern="/World/Forklift")
with prims:
    rep.modify.semantics([("class", "forklift")])
```

### USD-Level (pxr API)

```python
from pxr import Sdf

def set_semantic(prim, class_name):
    data_attr = "semantic:Semantics:params:semanticData"
    type_attr = "semantic:Semantics:params:semanticType"
    if not prim.HasAttribute(data_attr):
        prim.CreateAttribute(data_attr, Sdf.ValueTypeNames.Token, True).Set(class_name)
    else:
        prim.GetAttribute(data_attr).Set(class_name)
    if not prim.HasAttribute(type_attr):
        prim.CreateAttribute(type_attr, Sdf.ValueTypeNames.Token, True).Set("class")
    else:
        prim.GetAttribute(type_attr).Set("class")
```

The `semantic_id_to_labels.json` and `instance_segmentation_colors.json` files are written by
BasicWriter based on these USD-level semantics attributes.


## Asset Spawning with Replicator

### Spawning from USD

```python
prims = rep.create.from_usd(asset_path, count=num_instances)
with prims:
    rep.modify.pose(
        position=rep.distribution.uniform(
            (bounds_min[0], bounds_min[1], 0),
            (bounds_max[0], bounds_max[1], 0)
        ),
        rotation=rep.distribution.uniform((0, 0, 0), (0, 0, 360))
    )
```

Assets can be local USD files or remote HTTP URLs (S3-hosted NVIDIA assets).

### Creating Lights

```python
# Dome light (ambient/environment)
rep.create.light(light_type="Dome", intensity=1000, color=(1.0, 0.98, 0.95))

# Distant light (directional/sun)
rep.create.light(light_type="Distant", intensity=800, color=(1.0, 0.55, 0.20))

# Sphere light (point light)
rep.create.light(
    light_type="Sphere",
    intensity=400,
    color=(1.0, 0.85, 0.60),
    position=(x, y, z),
    scale=0.15,
)
```

Light types: "Dome", "Distant", "Sphere", "Rect", "Disk", "Cylinder"


## Orchestrator Step Function

The orchestrator controls the SDG pipeline:

```python
# Run simulation and capture frames
for step in range(NUM_FRAMES):
    world.step(render=False)
    rep.orchestrator.step()

# Wait for all writers to flush
rep.orchestrator.wait_until_complete()
rep.orchestrator.stop()
```

`rep.orchestrator.step()` triggers data capture. It does NOT trigger randomization
by default — randomizations on `on_frame` triggers fire automatically, but custom event
randomizations need `rep.utils.send_og_event()`.


## Trigger Types

```python
# Per-frame randomization (fires every N frames)
with rep.trigger.on_frame(num_frames=100):
    with camera:
        rep.modify.pose(position=rep.distribution.uniform(...))

# Custom event (manually triggered)
with rep.trigger.on_custom_event(event_name="randomize_lights"):
    rep.create.light(light_type="Dome", color=rep.distribution.uniform(...))

# Trigger it manually
rep.utils.send_og_event(event_name="randomize_lights")
```

For Isaac Sim workflows, `trigger.on_frame` is used for camera randomization and
`trigger.on_custom_event` for physics/animation randomization.


## Scene-Based SDG Workflow

The recommended pattern for scene-based synthetic data generation:

1. Create SimulationApp (headless)
2. Create World
3. Load environment USD
4. Spawn assets with `rep.create.from_usd()`
5. Apply semantic labels with `rep.modify.semantics()`
6. Set up camera and render_product
7. Initialize BasicWriter and attach to render_product
8. Define frame trigger with camera randomization
9. Run simulation loop: `world.step()` + `rep.orchestrator.step()`
10. Wait for completion and flush writers


## Object-Based SDG with Randomization

For domain randomization:

```python
# Register randomizers
def randomize_colors():
    prims = rep.get.prims(path_pattern="Cube")
    with prims:
        rep.randomizer.color(colors=rep.distribution.uniform((0, 0, 0), (1, 1, 1)))
    return prims.node

def randomize_lights():
    lights = rep.create.light(
        light_type="Sphere",
        color=rep.distribution.uniform((0, 0, 0), (1, 1, 1)),
        intensity=rep.distribution.normal(35000, 5000),
        position=rep.distribution.uniform(min_pos, max_pos),
        count=3,
    )
    return lights.node

# Register with orchestrator
rep.randomizer.register(randomize_colors)
rep.randomizer.register(randomize_lights)
```


## Randomization Snippets — Isaac Sim

### Randomizing Light Sources

```python
import numpy as np
import omni.replicator.core as rep
from pxr import Gf, Sdf, UsdGeom

# Create lights and randomize attributes over frames
for i in range(NUM_LIGHTS):
    light = rep.create.light(
        light_type="Sphere",
        position=rep.distribution.uniform((-5, -5, 3), (5, 5, 8)),
    )

with rep.trigger.on_frame(num_frames=NUM_FRAMES):
    with rep.get.prims(path_pattern="SphereLight"):
        rep.randomizer.intensity(rep.distribution.uniform(100, 2000))
        rep.randomizer.rotation(rep.distribution.uniform((0, 0, 0), (360, 360, 360)))
```

### Randomizing Object Materials/Colors

```python
with rep.trigger.on_frame(num_frames=NUM_FRAMES):
    with rep.get.prims(path_pattern=".*Cube.*"):
        rep.randomizer.color(colors=rep.distribution.uniform((0.1, 0.1, 0.1), (0.9, 0.9, 0.9)))
        rep.randomizer.texture(textures=rep.distribution.choice(texture_paths))
```


## Annotator and Custom Writer Data from Multiple Cameras

You can capture data from multiple cameras in a single scene:

```python
from omni.replicator.core import AnnotatorRegistry, Writer

class MyWriter(Writer):
    def __init__(self, rgb=True):
        self._frame_id = 0
        self.annotators = []
        if rgb:
            self.annotators.append(AnnotatorRegistry.get_annotator("rgb"))

    def write(self, data):
        for annotator in self.annotators:
            annotator_data = annotator.get_data()
            # Process annotator_data...
        self._frame_id += 1
```

Register custom writer:
```python
rep.WriterRegistry.register(MyWriter)
writer = rep.WriterRegistry.get("MyWriter")
```


## World and Simulation Stepping

```python
from isaacsim.core.api import World

world = World(stage_units_in_meters=1.0)

# Step simulation (physics-only, no render)
for _ in range(NUM_FRAMES):
    world.step(render=False)

# Render + capture
for _ in range(NUM_FRAMES):
    world.step(render=False)
    rep.orchestrator.step()

# After all frames
rep.orchestrator.wait_until_complete()
rep.orchestrator.stop()
world.clear()
simulation_app.close()
```


## People Simulation (omni.anim.people)

Characters are spawned using people simulation extension. Key steps:

1. Enable extensions before spawning
2. Create navmesh for pathfinding
3. Write command files (GoTo, Idle, LookAround)
4. Start timeline for behavior scripts

```python
# Enable people simulation
from isaac_backend.people import enable_extensions, setup_navmesh, setup_people_simulation

enable_extensions()
setup_navmesh()
setup_people_simulation(command_file_path)

# Start timeline
import omni.timeline
omni.timeline.get_timeline_interface().play()
```

Worker behavior commands:
- GoTo: `GoTo x y rotation` — character walks to (x, y) facing `rotation` degrees
- Idle: `Idle duration` — character stands still for `duration` seconds
- LookAround: `LookAround duration` — character looks around for `duration` seconds


## Hazard Zones (Invisible USD Volumes)

Create invisible collision volumes with semantic labels for zone detection:

```python
from pxr import UsdGeom, Gf, Sdf

stage.DefinePrim("/World/HazardZones", "Xform")
prim = stage.DefinePrim(f"/World/HazardZones/{name}", "Cube")
xf = UsdGeom.Xformable(prim)
xf.ClearXformOpOrder()
xf.AddTranslateOp().Set(Gf.Vec3d(cx, cy, 0.5))
xf.AddScaleOp().Set(Gf.Vec3d(sx, sy, 1.0))
UsdGeom.Imageable(prim).MakeInvisible()
prim.CreateAttribute("semantic:Semantics:params:semanticData", Sdf.ValueTypeNames.Token, True).Set(f"hazard_zone_{danger}")
prim.CreateAttribute("semantic:Semantics:params:semanticType", Sdf.ValueTypeNames.Token, True).Set("class")
```


## Project Architecture Notes

This project has two Python environments:

1. **Standard Python** (llm_pipeline/): Uses `instructor` + `openai` for structured LLM extraction
   with Gemini API. Generates SceneConfig JSON. Runs on CPU.

2. **Isaac Sim Python** (`/isaac-sim/python.sh`): Uses omni.replicator, pxr, isaacsim APIs.
   Generates synthetic data. Runs on GPU.

Pipeline:
   User prompt -> LLM (Gemini) -> SceneConfig JSON -> Isaac Sim -> COCO dataset -> YOLO

Asset library (assets/library.json) maps asset_id strings to USD paths on S3.
All Isaac Sim 5.1 assets use the 5.1 path prefix:
  https://omniverse-content-production.s3-us-west-2.amazonaws.com/Assets/Isaac/5.1/...