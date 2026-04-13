# Phase 7: Complete Rewrite — Isaac Sim 5.1 Extension & Library Update

## Approach: Full Rewrite From Scratch

Every file in `isaac_backend/` is rewritten from a clean slate using correct Isaac Sim 5.1 APIs.
No legacy code, no deprecated imports, no dead paths. Each file is designed 5.1-first.

## Deprecated APIs → Replacements

| Old (deprecated) | New (Isaac Sim 5.1) |
|---|---|
| `from omni.isaac.core import World` | `from isaacsim.core.api import World` |
| `BasicWriter` | `CocoWriter` + `coco_categories` dict |
| `omni.anim.people` + `omni.anim.navigation` | `isaacsim.replicator.behavior` (IRA only) |
| `omni.behavior.scripting.core` (explicit enable) | Pulled in by `isaacsim.replicator.behavior` |
| Missing DLSS quality mode | `carb.settings.set("/rtx/post/dlss/execMode", 2)` |
| Missing capture_on_play disable | `rep.orchestrator.set_capture_on_play(False)` |
| Missing async rendering flag | `--/exts/isaacsim.core.throttling/enable_async=false` in pipeline |

## Deleted Files (Phase 7.1)

- [x] `isaac_backend/people.py` — omni.anim.people integration
- [x] `isaac_backend/animator.py` — direct-mode CharacterAnimator API
- [x] `scripts/test_people_walk.py` — omni.anim.people test
- [x] `references/omni_anim_people/` — obsolete reference code

## Rewrite Specifications

### Task 7.2: `isaac_backend/main.py` — Full Rewrite

**What it does:** Bootstraps headless Isaac Sim, assembles scene from SceneConfig, runs Replicator SDG loop with CocoWriter, outputs to `/tmp/dataset`.

**Key changes from old version:**
- `from isaacsim.core.api import World` (not `omni.isaac.core`)
- No `people.py` imports at all — IRA is the only animation path
- `_configure_sdg_settings()` — sets DLSS Quality mode + disables capture_on_play
- `_setup_coco_writer()` — CocoWriter with 14 explicit `coco_categories` (including 3 hazard zone types)
- `_configure_camera_trigger()` — extracted from inline code, handles indoor/orbit modes
- `_collect_entity_positions()` — extracted helper for camera framing
- `_teardown()` — extracted clean teardown function
- `world.step(render=False)` — explicit render=False since we use Replicator for rendering
- `--/exts/isaacsim.core.throttling/enable_async=false` added to pipeline script (not in code)

**Structure:**
```
_patch_fast_importer()
_progress()
SimulationApp({"headless": True, "renderer": "RayTracedLighting"})
[omni/pxr/isaacsim imports]
COCO_CATEGORIES constant
_apply_scene_semantics()
compute_scene_centroid()
_configure_sdg_settings()
_setup_coco_writer()
_collect_entity_positions()
_configure_camera_trigger()
main() → orchestrates all steps
_teardown() → clean exit
```

### Task 7.3: `isaac_backend/animation.py` — Full Rewrite

**What it does:** Enables IRA behavior extensions, attaches behavior scripts (patrol/idle) to worker prims.

**Key changes from old version:**
- Extension list: `["omni.kit.scripting", "isaacsim.replicator.behavior", "omni.anim.graph.core"]`
  - Removed `omni.behavior.scripting.core` (auto-pulled dependency)
- Import `add_behavior_script_with_parameters_async` from `isaacsim.replicator.behavior.utils.behavior_utils`
- Import `EXPOSED_ATTR_NS` from `isaacsim.replicator.behavior.global_variables`
- Fallback: if IRA unavailable, use direct USD `omni:scripting:scripts` attribute + exposed attr creation
- Cleaner separation: `_attach_patrol_async()`, `_attach_idle_pose_async()`, `_attach_patrol_fallback_async()`, `_attach_idle_pose_fallback_async()`
- `enable_behavior_extensions()` takes `simulation_app` param, does 30 app.update() cycles

**Structure:**
```
[imports with try/except for IRA availability]
enable_behavior_extensions(simulation_app)
_extract_waypoints(worker_behavior)
_attach_patrol_async(prim, waypoints, ...)
_attach_idle_pose_async(prim, ...)
_set_exposed_attr(prim, namespace, attr_name, value, attr_type)
_apply_scripting_api_fallback(prim_path)
_attach_behavior_script_fallback(prim, script_path)
_attach_patrol_fallback_async(prim, waypoints, ...)
_attach_idle_pose_fallback_async(prim, ...)
setup_all_behaviors_async(spawned_worker_names, worker_behaviors, stage)
```

### Task 7.4: `isaac_backend/behaviors/worker_patrol.py` — Full Rewrite

**What it does:** IRA BehaviorScript subclass — waypoint lerping with walk/idle/look_around state machine + skeletal animation blending.

**Key changes from old version:**
- `from omni.behavior.scripting.core import BehaviorScript` with clean fallback stub
- `from omni.anim.graph.core as ag` with clean fallback flag
- Same state machine logic (walking → idle → look_around → next waypoint)
- Same animation blending (walk anim while moving, idle anim while stopped)
- Cleaner `_parse_params()` that reads from exposed USD attributes
- `BEHAVIOR_NS = "workerPatrol"` for attribute namespace

**Structure:**
```
[imports with fallbacks]
class WorkerPatrolBehavior(BehaviorScript):
    BEHAVIOR_NS = "workerPatrol"
    on_init() → state variables
    _parse_params() → read waypoints:csv, speed, idleDuration, lookAroundDuration
    on_play() → reset state, play idle anim
    on_update(current_time, delta_time) → state machine
    on_stop() → stop anims
    on_destroy() → stop anims
    _get_position() → UsdGeom.Xformable transform
    _set_translate_and_rotateY() → modify USD xform ops
    _find_skel_animation() → walk USD for SkelAnimation prim
    _find_walk_animation() → prefer "walk"/"move" in name
    _try_play_idle_anim() → ag.get_character_animator + ag.load_animation
    _try_play_walk_anim() → blend from idle to walk
    _stop_walk_anim() / _stop_idle_anim()
```

### Task 7.5: `isaac_backend/behaviors/worker_idle_pose.py` — Full Rewrite

**What it does:** IRA BehaviorScript subclass — periodic Y-rotation randomization + idle animation.

**Key changes from old version:**
- Same import pattern as worker_patrol.py
- Simpler state: just frame counter + interval-based rotation change
- `BEHAVIOR_NS = "workerIdlePose"`
- Reads `interval` and `rotationRange:csv` from exposed attributes

**Structure:**
```
[imports with fallbacks]
class WorkerIdlePoseBehavior(BehaviorScript):
    BEHAVIOR_NS = "workerIdlePose"
    on_init() → interval, rotation_range, frame_count, anim_id
    on_play() → parse params, play idle anim
    on_update(current_time, delta_time) → every N frames, randomize Y rotation
    on_stop() / on_destroy() → stop idle anim
    _parse_params() → read interval, rotationRange:csv
    _set_y_rotation() → modify USD xform ops
    _find_skel_animation()
    _try_play_idle_anim() / _stop_idle_anim()
```

### Task 7.6: `isaac_backend/workers.py` — Full Rewrite

**What it does:** Spawn worker characters as Xform prims with USD references + semantics.

**Key changes from old version:**
- No `attach_character_behavior()` — behavior scripts attached separately by `animation.py`
- No `AnimGraphSchema` dependency
- No `omni.kit.commands` usage
- Clean: Xform → AddReference → SetTranslate → apply semantics → done
- PPE selection: `worker_with_ppe`, `worker_with_ppe_alt`, `worker_no_ppe` from asset_library

**Structure:**
```
[imports: random, pxr, omni.usd, omni.replicator.core, semantics]
_PPE_KEYS / _NO_PPE_KEYS constants
select_worker_usd(ppe_state, asset_library)
spawn_workers(workers, worker_behaviors, asset_library, stage)
  → /World/Characters Xform parent
  → for each worker: Xform + AddReference + Translate + semantics
  → returns set of spawned names
```

### Task 7.7: `isaac_backend/semantics.py` — Full Rewrite

**What it does:** Apply/clear USD semantic attributes for Replicator writers.

**Key changes from old version:**
- `apply_usd_semantics(prim_path, class_name)` — renamed from `apply_semantics` for clarity
- `clear_unwanted_warehouse_semantics(stage)` — strips semantics from warehouse structural prims, keeps rack/pallet
- `KEEP_SEMANTICS` constant unchanged
- Same USD attribute pattern: `semantic:Semantics:params:semanticData` + `semantic:Semantics:params:semanticType`

**Structure:**
```
[imports: omni.usd, pxr.Sdf]
KEEP_SEMANTICS constant
apply_usd_semantics(prim_path, class_name)
clear_unwanted_warehouse_semantics(stage)
_clear_semantics_if_needed(prim)
```

### Task 7.8: `isaac_backend/warehouse.py` — Full Rewrite

**What it does:** Procedurally spawn warehouse layout (racks, pallets, boxes, barrels, cones) + hide driver prims.

**Key changes from old version:**
- Uses `omni.kit.commands.execute("CreateReferenceCommand", ...)` for spawning
- Uses `UsdGeom.XformCommonAPI` for transforms
- `apply_usd_semantics()` from semantics module
- Same layout logic: 5 rack rows, pallet staging, aisle clutter, small props
- `hide_driver_prims()` — traverse stage, MakeInvisible on "driver" meshes

**Structure:**
```
[imports: random, pxr, omni.usd, omni.kit.commands, semantics]
spawn_warehouse_layout(asset_library, stage)
  → place() inner function: CreateReferenceCommand + XformCommonAPI + semantics
  → rack rows at x=[-6,-3,0,3,6], y=[7, 3, -3]
  → pallets near racks + center staging
  → small props (box/barrel/cone) scattered in aisles
hide_driver_prims(stage)
```

### Task 7.9: `isaac_backend/spawner.py` — Full Rewrite

**What it does:** Geofenced random entity spawning + hazard zone creation.

**Key changes from old version:**
- `get_geofenced_spawner()` — returns a callable that creates prims with `rep.distribution.uniform` position/rotation
- `rep.randomizer.register()` for Replicator graph integration
- `spawn_hazard_zones()` — invisible USD Cubes with hazard_zone semantics
- Same hazard zone logic: center + scale from bounds_min/bounds_max, MakeInvisible

**Structure:**
```
[imports: random, omni.replicator.core, pxr, omni.usd]
get_geofenced_spawner(asset_path, num_instances, bounds_min, bounds_max)
  → inner spawn_in_bounds() → rep.create.from_usd + rep.modify.pose
  → rep.randomizer.register(spawn_in_bounds)
  → returns spawn_in_bounds
spawn_hazard_zones(hazard_zones, stage)
  → /World/HazardZones Xform parent
  → for each zone: Cube prim + Translate + Scale + MakeInvisible + semantics
```

### Task 7.10: `isaac_backend/camera.py` — Full Rewrite

**What it does:** Camera positioning logic — indoor fixed position + orbit distribution.

**Key changes from old version:**
- No API changes needed (pure Python, no Isaac Sim imports except `rep.distribution`)
- `clamp_to_warehouse()` — constrain to interior bounds
- `pick_indoor_position()` — centroid-based placement with angle-aware height
- `positions_for_angles()` — indoor or orbit mode
- `orbit_distribution()` — `rep.distribution.uniform` over position bounds
- `ANGLE_HEIGHT_MAP` / `ANGLE_ELEVATION_MAP` constants

**Structure:**
```
[imports: math, random, omni.replicator.core (in orbit_distribution only)]
WAREHOUSE_INTERIOR_X/Y, INTERIOR_MARGIN, CEILING_Z, FLOOR_Z constants
ANGLE_HEIGHT_MAP / DEFAULT_HEIGHT_RANGE
ANGLE_ELEVATION_MAP
clamp_to_warehouse(x, y, z)
pick_indoor_position(angle_hints, hazard_zones, entity_positions, worker_positions)
_build_orbit_positions(n, radius_min, radius_max, azimuth_deg, elevation_deg)
_compute_scene_radius(hazard_zones, entity_positions)
positions_for_angles(angle_hints, hazard_zones, entity_positions, worker_positions, mode)
orbit_distribution(scene_positions)
```

### Task 7.11: `isaac_backend/lighting.py` — Full Rewrite

**What it does:** Create dome + distant + sphere lights based on lighting condition + camera + render product.

**Key changes from old version:**
- No API changes needed (uses `rep.create.light`, `rep.create.camera`, `rep.create.render_product`)
- `LIGHTING_MAP` — daylight/overcast/dusk/night intensity + color
- Condition-specific: daylight gets distant light, dusk/night get ceiling sphere lights
- Returns `(camera, render_product)` tuple

**Structure:**
```
[imports: omni.replicator.core]
LIGHTING_MAP constant
_CEILING_LAMP_XY / _CEILING_Z constants
setup_camera_and_lighting(config)
  → dome light from LIGHTING_MAP
  → condition-specific additional lights
  → camera + render_product(1024, 1024)
  → return (camera, render_product)
```

### Task 7.12: `isaac_backend/config_loader.py` — Full Rewrite

**What it does:** Load SceneConfig JSON + asset library JSON.

**Key changes from old version:**
- No changes needed — pure Python, no Isaac Sim dependencies
- Kept minimal and clean

**Structure:**
```
[imports: sys, json]
load_config(config_path, library_path, simulation_app=None)
  → try/except → return (scene_config, asset_library)
  → on failure: close simulation_app + sys.exit(1)
```

### Task 7.13: `isaac_backend/__init__.py` — Update

**What it does:** Package exports.

**Changes:** Remove any references to deleted modules (people.py, animator.py). Already clean.

### Task 7.14: `scripts/run_pipeline.sh` — Update

**Changes:**
- Add `--/exts/isaacsim.core.throttling/enable_async=false` to Isaac Sim invocation
- Keep fast_importer.py patch
- All 8 steps unchanged otherwise

### Task 7.15: `scripts/coco_to_yolo.py` — Update

**Changes:**
- Update argparse help text: "BasicWriter" → "CocoWriter"
- `CLASS_MAP` already includes hazard zone classes — no changes needed
- Logic unchanged — reads `bounding_box_2d_tight_*.npy` + `semantic_id_to_labels.json` which CocoWriter also produces

### Task 7.16: `AGENTS.md` — Update

**Sections to update:**
- "Isaac Sim Gotchas" — add CocoWriter, isaacsim.core.api, DLSS, async flag, IRA-only
- Architecture diagram — remove people.py/animator.py, note CocoWriter
- Pipeline steps — unchanged (still 8 steps)
- Two Python Environments table — unchanged

### Task 7.17: `TODO.md` — Update

**Changes:** Add Phase 7 entry tracking this rewrite.

### Task 7.18: RAG Index Rebuild

- Run `python3 -m rag_system.build_index` on the pod after all files are written
- This re-crawls docs + re-indexes updated source code

### Task 7.19: Syntax Validation

- `python3 -m py_compile` on every isaac_backend/ Python file
- `python3 -m py_compile` on every scripts/ Python file
- `python3 llm_pipeline/generator.py --prompt "test" --output /dev/null` (validates llm_pipeline imports)

## CocoWriter Categories (14 total)

| ID | Name | Supercategory | isthing |
|---|---|---|---|
| 1 | person | worker | 1 |
| 2 | vehicle | equipment | 1 |
| 3 | rack | warehouse | 1 |
| 4 | pallet | warehouse | 1 |
| 5 | box | warehouse | 1 |
| 6 | barrel | warehouse | 1 |
| 7 | cone | safety | 1 |
| 8 | fire_extinguisher | safety | 1 |
| 9 | cart | warehouse | 1 |
| 10 | sign | safety | 1 |
| 11 | pillar | structure | 1 |
| 12 | hazard_zone_warning | zone | 0 |
| 13 | hazard_zone_restricted | zone | 0 |
| 14 | hazard_zone_critical | zone | 0 |

## Asset Library Status

All paths in `assets/library.json` already use Isaac Sim 5.1 S3 prefix. No changes needed.

## Execution Order

1. **7.1** — Delete deprecated files (DONE)
2. **7.2** — Rewrite `main.py`
3. **7.3** — Rewrite `animation.py`
4. **7.4** — Rewrite `behaviors/worker_patrol.py`
5. **7.5** — Rewrite `behaviors/worker_idle_pose.py`
6. **7.6** — Rewrite `workers.py`
7. **7.7** — Rewrite `semantics.py`
8. **7.8** — Rewrite `warehouse.py`
9. **7.9** — Rewrite `spawner.py`
10. **7.10** — Rewrite `camera.py`
11. **7.11** — Rewrite `lighting.py`
12. **7.12** — Rewrite `config_loader.py`
13. **7.13** — Update `__init__.py`
14. **7.14** — Update `run_pipeline.sh`
15. **7.15** — Update `coco_to_yolo.py`
16. **7.16** — Update `AGENTS.md`
17. **7.17** — Update `TODO.md`
18. **7.18** — Rebuild RAG index (on pod)
19. **7.19** — Syntax validation

## Testing Plan (Run on RunPod)

```bash
# Syntax checks
python3 -m py_compile isaac_backend/main.py
python3 -m py_compile isaac_backend/animation.py
python3 -m py_compile isaac_backend/behaviors/worker_patrol.py
python3 -m py_compile isaac_backend/behaviors/worker_idle_pose.py
python3 -m py_compile isaac_backend/workers.py
python3 -m py_compile isaac_backend/semantics.py
python3 -m py_compile isaac_backend/warehouse.py
python3 -m py_compile isaac_backend/spawner.py
python3 -m py_compile isaac_backend/camera.py
python3 -m py_compile isaac_backend/lighting.py
python3 -m py_compile isaac_backend/config_loader.py
python3 -m py_compile scripts/coco_to_yolo.py

# Full pipeline test
./scripts/run_pipeline.sh "A worker with hardhat patrols near a forklift in a warehouse"

# Verify output
ls /tmp/dataset/
cat /tmp/dataset/semantic_id_to_labels.json
python3 scripts/coco_to_yolo.py --dir /tmp/dataset --masks
```
