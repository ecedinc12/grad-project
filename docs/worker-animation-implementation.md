# Worker Animation Implementation — Anti T-Pose

This document captures the working implementation that prevents workers from T-posing during Isaac Sim dataset generation.

## Overview

Workers are animated using Isaac Sim's IRA (Intelligent Robotic Agent) system with built-in `character_behavior.py` from `omni.anim.people`. The animation pipeline has two phases: **pre-play** (ScriptingAPI + AnimationGraphAPI attachment) and **post-play** (AgentManager command injection).

## Kit Patches (Critical)

Two runtime patches are applied **before** `SimulationApp` is created. Without these, workers will T-pose.

### Patch 1: `fast_importer.py` — None `submodule_search_locations`

**File:** `/isaac-sim/kit/kernel/py/omni/ext/_impl/fast_importer.py`

**Problem:** Isaac Sim's extension importer iterates over `spec.submodule_search_locations` which can be `None` for some extensions, causing a `TypeError` crash at startup.

**Fix:** Guard the iteration with `or []`:

```python
# Before:
for p in spec_default.submodule_search_locations:

# After:
for p in (spec_default.submodule_search_locations or []):
```

**Applied in:** `main.py:_patch_fast_importer()` (line 20–35)

### Patch 2: `isaacsim.exp.base.python.kit` — Animation Graph Schema Extensions

**File:** `/isaac-sim/apps/isaacsim.exp.base.python.kit`

**Problem:** The base kit configuration does not include `omni.anim.graph.core` or `omni.anim.graph.schema` as dependencies. Without these, `AnimationGraphAPI` cannot be resolved on worker USDs and characters remain in T-pose.

**Fix:** Inject the two extension entries into the kit file:

```
"isaacsim.exp.base" = {}
"omni.anim.graph.core" = {}
"omni.anim.graph.schema" = {}
```

**Applied in:** `main.py:_patch_kit_anim_schema()` (line 38–59)

## Animation Pipeline

### Phase 1: Pre-Play Setup (before `timeline.play()`)

#### 1a. Enable Behavior Extensions
```python
enable_behavior_extensions(simulation_app=simulation_app)
```
Enables all required extensions: `omni.kit.scripting`, `isaacsim.replicator.behavior`, `isaacsim.replicator.agent.core`, `omni.anim.graph.core`, `omni.anim.graph.schema`, `omni.anim.people`, `omni.anim.navigation.schema`. Then ticks 30 updates for extension loading.

**File:** `animation.py:enable_behavior_extensions()` (line 74–98)

#### 1b. Spawn Workers
```python
spawned_worker_names = spawn_workers(workers, worker_behaviors, asset_library, stage, simulation_app)
```
- Creates `/World/Characters` Xform
- For each worker entity, creates an Xform prim at `/World/Characters/worker_NN` and adds a USD reference to the character asset
- Sets initial position from the first `GoTo` command in behavior config
- Applies `person` semantic label
- **Polls for SkelRoot resolution** — S3-hosted USD assets load asynchronously. `_wait_for_skelroot()` ticks `simulation_app.update()` until the SkelRoot descendant appears inside the referenced character USD (up to 240 ticks).

**File:** `workers.py:spawn_workers()` (line 54–111)

#### 1c. Load Biped_Setup
```python
ensure_biped_setup(simulation_app=simulation_app)
```
Calls `CharacterUtil.load_default_biped_to_stage()` which creates `/World/Characters/Biped_Setup` with a shared AnimationGraph prim and walk/sit/idle animations. Falls back to manual USD reference if CharacterUtil fails.

**File:** `animation.py:ensure_biped_setup()` (line 102–139)

#### 1d. Attach Behavior Scripts
```python
attached, failed = setup_all_behaviors_async(spawned_worker_names, worker_behaviors, stage)
```
For each worker:
1. Finds the SkelRoot under `/World/Characters/{worker_name}`
2. Calls `CharacterUtil.setup_python_scripts_to_character([skelroot], script_path)` — applies `ScriptingAPI` and sets `omni:scripting:scripts` to IRA's built-in `character_behavior.py`
3. Fallback: manually applies `ScriptingAPI` via `omni.kit.commands.execute("ApplyScriptingAPICommand", ...)` and sets the script path attribute

**File:** `animation.py:setup_all_behaviors_async()` (line 299–343)

#### 1e. Link AnimationGraph
```python
linked, link_failed = link_workers_to_animation_graph(spawned_worker_names, stage, simulation_app)
```
For each worker's SkelRoot:
1. Calls `CharacterUtil.setup_animation_graph_to_character(skelroots, anim_graph_prim)` — removes any existing `AnimationGraphAPI`, applies fresh `AnimationGraphAPI`, and sets the `animationGraph` relationship to point at the shared AnimationGraph
2. Fallback: uses `omni.kit.commands` (`RemoveAnimationGraphAPICommand`, `ApplyAnimationGraphAPICommand`)

**File:** `animation.py:link_workers_to_animation_graph()` (line 213–271)

#### 1f. Warm-Up
```python
for _ in range(120):
    simulation_app.update()
```
120 update ticks to let the ScriptingAPI + AnimationGraphAPI propagate through the scene graph.

**File:** `main.py` (line 403–405)

### Phase 2: Post-Play Setup (after `timeline.play()`)

#### 2a. Start Timeline
```python
omni.timeline.get_timeline_interface().play()
```
Timeline must be playing for character animations to execute.

**File:** `main.py` (line 418)

#### 2b. Step World for Agent Registration
```python
for _ in range(100):
    world.step(render=True)
```
100 simulation steps to allow the behavior scripts to initialize and register agents with `AgentManager`.

**File:** `main.py` (line 420–421)

#### 2c. Inject Commands
```python
injected, inj_failed = inject_commands_after_play(
    spawned_worker_names, worker_behaviors, simulation_app=simulation_app
)
```
For each registered agent:
1. Retrieves `AgentManager` instance via `AgentManager.get_instance()`
2. Checks `agent_registered(worker_name)`
3. Builds command list from behavior config: `GoTo x y z rot`, `Idle duration`, `LookAround duration`
4. Calls `agent_manager.inject_command(agent_name, command_list, force_inject=True, instant=True)`

**File:** `animation.py:inject_commands_after_play()` (line 376–428)

## SDG Settings

```python
settings.set("/rtx/post/dlss/execMode", 2)           # DLSS Quality mode
settings.set("/exts/isaacsim.core.throttling/enable_async", False)  # Prevent frame skipping
settings.set("/app/animation/update_all_animations", True)         # Update all animations each frame
rep.orchestrator.set_capture_on_play(False)                         # Manual capture control
```

**File:** `main.py:_configure_sdg_settings()` (line 203–211)

## Orchestration Sequence

```
1.  _patch_fast_importer()                          # Kit patch #1
2.  _patch_kit_anim_schema()                        # Kit patch #2
3.  SimulationApp(headless=True, extensions=[...])  # Must include anim extensions
4.  World(stage_units_in_meters=1.0)
5.  _configure_sdg_settings()
6.  Load warehouse zone
7.  Spawn warehouse layout + other entities
8.  enable_behavior_extensions()                     # Phase 1a
9.  spawn_workers()                                  # Phase 1b (waits for SkelRoot)
10. ensure_biped_setup()                             # Phase 1c
11. setup_all_behaviors_async()                      # Phase 1d
12. link_workers_to_animation_graph()                 # Phase 1e
13. Warm-up: 120 × simulation_app.update()          # Phase 1f
14. timeline.play()                                  # Phase 2a
15. 100 × world.step(render=True)                    # Phase 2b (agent registration)
16. inject_commands_after_play()                      # Phase 2c
17. CocoWriter setup + camera trigger
18. Simulation loop: world.step() + rep.orchestrator.step()
19. Teardown: orchestrator.stop() → writer.detach() → world.clear() → simulation_app.close() → os._exit(0)
```

## Key Gotchas

- **`SimulationApp` must be created before any `omni.*` / `pxr.*` imports.**
- **SkelRoot polling is required** — S3 USD references resolve asynchronously.
- **`timeline.play()` must be called before command injection** — animations don't run without it.
- **`rep.orchestrator.set_capture_on_play(False)`** — manual capture prevents premature frame writes.
- **DLSS must be set to Quality mode** (`execMode=2`) to avoid rendering artifacts at low resolutions.
- **Throttling must be disabled** (`enable_async=False`) to prevent frame skipping during Replicator runs.
- **`update_all_animations=True`** ensures all character animations update each simulation step.
- **`force_inject=True` and `instant=True`** on `AgentManager.inject_command()` — bypasses queuing, applies immediately.