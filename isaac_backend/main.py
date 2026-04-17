"""
Isaac Sim 5.1 Industrial Safety SDG Pipeline — Main Entry Point

Bootstraps headless simulation, assembles the scene from SceneConfig JSON,
runs Replicator with CocoWriter, and outputs COCO-format dataset to /tmp/dataset.

CRITICAL: SimulationApp MUST be created BEFORE any omni.* or pxr.* imports.
"""

import os
import sys
import glob
import time
import random
import argparse
import subprocess


def _patch_fast_importer():
    """Patch Isaac Sim's fast_importer.py to handle None submodule_search_locations."""
    FAST_IMPORTER = "/isaac-sim/kit/kernel/py/omni/ext/_impl/fast_importer.py"
    if not os.path.isfile(FAST_IMPORTER):
        return
    with open(FAST_IMPORTER, "r") as f:
        src = f.read()
    if "submodule_search_locations or []" in src:
        return
    patched = src.replace(
        "for p in spec_default.submodule_search_locations:",
        "for p in (spec_default.submodule_search_locations or []):",
    )
    with open(FAST_IMPORTER, "w") as f:
        f.write(patched)
    _progress("Patched fast_importer.py for None submodule_search_locations")


def _patch_kit_anim_schema():
    """Patch kit to include animation graph schema for character USD resolution."""
    KIT_FILE = "/isaac-sim/apps/isaacsim.exp.base.python.kit"
    if not os.path.isfile(KIT_FILE):
        return
    with open(KIT_FILE, "r") as f:
        src = f.read()
    if '"omni.anim.graph.schema"' in src:
        return
    patched = src.replace(
        '"isaacsim.exp.base" = {}',
        '"isaacsim.exp.base" = {}\n"omni.anim.graph.core" = {}\n"omni.anim.graph.schema" = {}',
    )
    with open(KIT_FILE, "w") as f:
        f.write(patched)
    _progress("Patched kit file with omni.anim.graph.core and omni.anim.graph.schema")


def _progress(msg):
    print(f"[PROGRESS] [{time.strftime('%H:%M:%S')}] {msg}")
    sys.stdout.flush()


_patch_fast_importer()
_patch_kit_anim_schema()

from isaacsim import SimulationApp

simulation_app = SimulationApp({
    "headless": True,
    "renderer": "RayTracedLighting",
    "extension_remote_config": True,
    "extensions": [
        "omni.isaac.core",
        "omni.isaac.generic",
        "omni.anim.people",
        "omni.anim.graph.core",
        "omni.anim.graph.schema",
        "omni.anim.graph.ui",
        "omni.anim.navigation.core",
        "omni.anim.navigation.schema",
        "isaacsim.replicator.agent.core",
        "isaacsim.replicator.behavior",
    ],
    "disabled_extensions": [
        "omni.kit.window.property",
    ],
})

import carb
import omni.replicator.core as rep
import omni.usd
import omni.timeline
from isaacsim.core.api import World
from pxr import Usd, UsdGeom, Sdf

from isaac_backend.config_loader import load_config
from isaac_backend.camera import (
    positions_for_angles, pick_indoor_position, clamp_to_warehouse,
    pick_look_at_target, pick_camera_placement, compute_ground_visible_area,
    fit_camera_to_entities,
)
from isaac_backend.lighting import setup_camera_and_lighting
from isaac_backend.semantics import clear_unwanted_warehouse_semantics
from isaac_backend.spawner import get_geofenced_spawner, spawn_hazard_zones, spawn_at_fixed_position, resolve_anchor_zone_bounds
from isaac_backend.warehouse import spawn_warehouse_layout, hide_driver_prims
from isaac_backend.workers import spawn_workers
from isaac_backend.animation import (
    enable_behavior_extensions,
    bake_navmesh,
    setup_all_behaviors_async,
    ensure_biped_setup,
    link_workers_to_animation_graph,
    inject_commands_after_play,
    reinject_random_commands,
    VehicleAnimator,
)

COCO_CATEGORIES = {
    "person": {"name": "person", "id": 1, "supercategory": "worker", "color": (220, 20, 60)},
    "vehicle": {"name": "vehicle", "id": 2, "supercategory": "equipment", "color": (255, 165, 0)},
    "hardhat": {"name": "hardhat", "id": 15, "supercategory": "ppe", "color": (255, 255, 0)},
    "vest": {"name": "vest", "id": 16, "supercategory": "ppe", "color": (0, 255, 127)},
    "rack": {"name": "rack", "id": 3, "supercategory": "warehouse", "color": (139, 69, 19)},
    "pallet": {"name": "pallet", "id": 4, "supercategory": "warehouse", "color": (210, 180, 140)},
    "box": {"name": "box", "id": 5, "supercategory": "warehouse", "color": (188, 143, 143)},
    "barrel": {"name": "barrel", "id": 6, "supercategory": "warehouse", "color": (128, 0, 128)},
    "cone": {"name": "cone", "id": 7, "supercategory": "safety", "color": (255, 140, 0)},
    "fire_extinguisher": {"name": "fire_extinguisher", "id": 8, "supercategory": "safety", "color": (255, 0, 0)},
    "cart": {"name": "cart", "id": 9, "supercategory": "warehouse", "color": (160, 82, 45)},
    "sign": {"name": "sign", "id": 10, "supercategory": "safety", "color": (255, 255, 0)},
    "pillar": {"name": "pillar", "id": 11, "supercategory": "structure", "color": (169, 169, 169)},
    "hazard_zone_warning": {"name": "hazard_zone_warning", "id": 12, "supercategory": "zone", "color": (255, 255, 0)},
    "hazard_zone_restricted": {"name": "hazard_zone_restricted", "id": 13, "supercategory": "zone", "color": (255, 165, 0)},
    "hazard_zone_critical": {"name": "hazard_zone_critical", "id": 14, "supercategory": "zone", "color": (255, 0, 0)},
}

NUM_FRAMES = 200
SIM_STEPS_PER_FRAME = 2
REINJECT_INTERVAL = 80
CAMERA_RANDOMIZE_INTERVAL = 20


# --- Helpers ---

def _tick(n):
    """Process n simulation app updates (loads assets, resolves references, no physics)."""
    for _ in range(n):
        simulation_app.update()


def intersect_bounds(spawn_min, spawn_max, visible_bounds):
    """Intersect spawn bounds with camera visible bounds.

    Args:
        spawn_min: (x_min, y_min) of the warehouse spawn area.
        spawn_max: (x_max, y_max) of the warehouse spawn area.
        visible_bounds: (min_x, max_x, min_y, max_y) of the camera's ground visible area.

    Returns:
        ((x_min, y_min), (x_max, y_max)) of the intersection.
    """
    v_min_x, v_max_x, v_min_y, v_max_y = visible_bounds
    return (
        (max(spawn_min[0], v_min_x), max(spawn_min[1], v_min_y)),
        (min(spawn_max[0], v_max_x), min(spawn_max[1], v_max_y)),
    )


def compute_scene_centroid(stage, known_positions=None):
    """Compute average position of scene entities and collect positions for camera framing.

    known_positions is an optional list of (x, y) tuples for entities whose
    USD positions may not be resolved yet (e.g. Replicator-randomized prims).

    Returns ((cx, cy, cz), entity_positions, worker_positions).
    """
    known_positions = known_positions or []
    xs, ys, zs = [], [], []
    entity_positions, worker_positions = [], []

    for px, py in known_positions:
        xs.append(px)
        ys.append(py)
        zs.append(0.0)
        entity_positions.append((px, py))

    for prim in stage.Traverse():
        path = str(prim.GetPath())
        if not (path.startswith("/World/Characters/") or path.startswith("/World/Entities/") or path.startswith("/Replicator/")):
            continue
        xf = UsdGeom.Xformable(prim)
        if not xf:
            continue
        mat = xf.ComputeLocalToWorldTransform(Usd.TimeCode.Default())
        pos = mat.ExtractTranslation()
        dup = any(abs(pos[0] - ex) < 0.1 and abs(pos[1] - ey) < 0.1 for ex, ey in known_positions)
        if dup:
            continue
        xs.append(pos[0])
        ys.append(pos[1])
        zs.append(pos[2])
        entity_positions.append((pos[0], pos[1]))
        if path.startswith("/World/Characters/"):
            worker_positions.append((pos[0], pos[1]))

    if not xs:
        _progress("[WARN] No entities for centroid, defaulting to (0, 0, 1.2)")
        return (0.0, 0.0, 1.2), entity_positions, worker_positions
    cx, cy, cz = sum(xs) / len(xs), sum(ys) / len(ys), sum(zs) / len(zs)
    _progress(f"Scene centroid: ({cx:.2f}, {cy:.2f}, {cz:.2f}) from {len(xs)} entities")
    return (cx, cy, cz), entity_positions, worker_positions


def _configure_sdg_settings():
    """Apply recommended settings for synthetic data generation."""
    settings = carb.settings.get_settings()
    settings.set("/rtx/post/dlss/execMode", 2)
    settings.set("/exts/isaacsim.core.throttling/enable_async", False)
    settings.set("/app/animation/update_all_animations", True)
    rep.orchestrator.set_capture_on_play(False)
    _progress("SDG settings configured: DLSS=Quality, capture_on_play=False, async=False")


def _setup_coco_writer():
    """Initialize and return a CocoWriter with all category definitions."""
    writer = rep.WriterRegistry.get("CocoWriter")
    writer.initialize(
        output_dir="/tmp/dataset",
        rgb=True,
        bounding_box_2d_tight=True,
        semantic_segmentation=True,
        instance_segmentation=True,
        coco_categories=COCO_CATEGORIES,
    )
    _progress("CocoWriter initialized with 16 categories (incl. hardhat, vest)")
    return writer


def _configure_camera_trigger(camera, scene_config, cam_pos, look_at_target):
    """Set up the frame trigger with either fixed indoor position or orbit distribution.

    cam_pos and look_at_target are pre-computed from pick_camera_placement().
    """
    angle_hints = scene_config.get("camera_angles", [])
    hazard_zones = scene_config.get("hazard_zones", [])
    camera_mode = scene_config.get("camera_mode", "indoor")

    if camera_mode == "indoor":
        _progress(f"Camera indoor: ({cam_pos[0]:.2f}, {cam_pos[1]:.2f}, {cam_pos[2]:.2f}), "
                  f"look_at=({look_at_target[0]:.2f}, {look_at_target[1]:.2f}, {look_at_target[2]:.2f})")

        with rep.trigger.on_frame(num_frames=NUM_FRAMES, interval=CAMERA_RANDOMIZE_INTERVAL):
            with camera:
                rep.modify.pose(position=cam_pos, look_at=look_at_target)
    else:
        scene_positions = positions_for_angles(
            angle_hints, hazard_zones=hazard_zones,
            entity_positions=None,
            worker_positions=None,
            mode="orbit",
        )
        from isaac_backend.camera import orbit_distribution
        camera_pos_dist = orbit_distribution(scene_positions)
        _progress(f"Camera orbit: {len(scene_positions)} positions")

        with rep.trigger.on_frame(num_frames=NUM_FRAMES, interval=CAMERA_RANDOMIZE_INTERVAL):
            with camera:
                rep.modify.pose(position=camera_pos_dist, look_at=look_at_target)


def _teardown(rep, writer, world, simulation_app):
    """Clean teardown in the correct order to avoid crashes."""
    for step in [
        lambda: rep.orchestrator.stop(),
        lambda: writer.detach(),
        lambda: world.clear(),
    ]:
        try:
            step()
        except Exception as e:
            print(f"[WARN] teardown step failed: {e}", file=sys.stderr)

    simulation_app.close()
    _progress("Generation complete. Data saved to /tmp/dataset.")
    sys.stdout.flush()
    os._exit(0)


# --- Pipeline phases ---

def _spawn_entities(scene_config, asset_library, stage, spawn_bounds_min, spawn_bounds_max, visible_bounds=None):
    """Spawn non-worker entities and return (spawned_asset_ids, known_positions).

    Strategy:
    - Vehicles (type='vehicle') are ALWAYS placed at a fixed position.
      If anchor_zone is set, placed at the matching hazard zone center.
      If no anchor_zone, placed near the visible area center.
      Vehicle positions are clamped toward the visible area.
    - All other non-worker entities use Replicator random spawning,
      constrained to the intersection of spawn bounds and visible bounds.
    """
    others = [e for e in scene_config.get("entities", []) if e.get("type") != "worker"]
    hazard_zones = scene_config.get("hazard_zones", [])
    spawned_asset_ids = []
    known_positions = []

    constrained_min, constrained_max = spawn_bounds_min, spawn_bounds_max
    if visible_bounds is not None:
        constrained_min, constrained_max = intersect_bounds(spawn_bounds_min, spawn_bounds_max, visible_bounds)
        _progress(f"Spawn bounds constrained to visible area: ({constrained_min[0]:.2f},{constrained_min[1]:.2f}) to ({constrained_max[0]:.2f},{constrained_max[1]:.2f})")

    for entity in others:
        asset_id = entity.get("asset_id", "")
        if asset_id == "zone":
            continue
        usd_path = asset_library.get(asset_id)
        if usd_path is None:
            print(f"[WARNING] Unknown asset_id '{asset_id}'. Skipping.")
            continue

        asset_type = entity.get("type", "")
        semantic_class = "vehicle" if asset_type == "vehicle" else asset_id
        anchor_zone = entity.get("anchor_zone")

        if asset_type == "vehicle":
            vehicle_count = sum(1 for a, _ in spawned_asset_ids if a == asset_id)
            prim_name = f"{asset_id}_{vehicle_count + 1:02d}"

            # Check if there is a behavior with a first GoTo command to use as spawn pos
            spawn_x, spawn_y = None, None
            for vb in scene_config.get("vehicle_behaviors", []):
                if vb.get("vehicle_id") == prim_name:
                    for cmd in vb.get("commands", []):
                        if cmd.get("command") == "GoTo":
                            spawn_x, spawn_y = cmd.get("x"), cmd.get("y")
                            break
                    break
            
            if spawn_x is not None and spawn_y is not None:
                cx, cy = spawn_x, spawn_y
            else:
                zone_bounds = resolve_anchor_zone_bounds(anchor_zone, hazard_zones)
                if zone_bounds is not None:
                    bmin, bmax = zone_bounds
                    cx = (bmin[0] + bmax[0]) / 2.0
                    cy = (bmin[1] + bmax[1]) / 2.0
                    cx += random.uniform(-0.5, 0.5)
                    cy += random.uniform(-0.5, 0.5)
                else:
                    if visible_bounds is not None:
                        cx = random.uniform(visible_bounds[0], visible_bounds[1])
                        cy = random.uniform(visible_bounds[2], visible_bounds[3])
                    else:
                        cx, cy = random.uniform(-3.0, 3.0), random.uniform(-3.0, 3.0)
                    print(f"[INFO] Vehicle '{asset_id}' has no anchor_zone, placing at ({cx:.2f}, {cy:.2f})")

                if visible_bounds is not None:
                    cx = max(visible_bounds[0], min(visible_bounds[1], cx))
                    cy = max(visible_bounds[2], min(visible_bounds[3], cy))

            prim_path, spawn_pos = spawn_at_fixed_position(
                usd_path, position=(cx, cy, 0.0), semantic_class=semantic_class, prim_name=prim_name
            )
            known_positions.append(spawn_pos)
            _progress(f"Vehicle '{prim_name}' anchored to '{anchor_zone}' at ({cx:.2f}, {cy:.2f})")
        else:
            _progress(f"Spawning '{asset_id}' (type={asset_type}) with random placement")
            spawner = get_geofenced_spawner(
                usd_path, num_instances=1,
                bounds_min=constrained_min, bounds_max=constrained_max,
            )
            prims = spawner()
            with prims:
                rep.modify.semantics([("class", semantic_class)])

        spawned_asset_ids.append((asset_id, semantic_class))

    _progress(f"Spawned {len(spawned_asset_ids)} non-worker entities ({len(known_positions)} fixed-position)")
    return spawned_asset_ids, known_positions


def _setup_workers(scene_config, asset_library, stage, visible_bounds=None):
    """Spawn workers, set up animation, and return (spawned_worker_names, worker_behaviors).

    visible_bounds constrains worker initial positions to the camera's visible area.
    """
    workers = [e for e in scene_config.get("entities", []) if e.get("type") == "worker"]
    worker_behaviors = scene_config.get("worker_behaviors", [])

    if not workers:
        return set(), worker_behaviors

    _progress("Enabling behavior extensions...")
    enable_behavior_extensions(simulation_app=simulation_app)

    _progress(f"Spawning {len(workers)} workers...")
    spawned_names = spawn_workers(workers, worker_behaviors, asset_library, stage, simulation_app, visible_bounds=visible_bounds)

    _progress("Loading Biped_Setup for AnimationGraph...")
    ensure_biped_setup(simulation_app=simulation_app)

    _progress("Attaching IRA behavior scripts to workers...")
    attached, failed = setup_all_behaviors_async(spawned_names, worker_behaviors, stage)
    _progress(f"IRA behaviors: {attached} attached, {failed} failed")

    _progress("Linking workers to AnimationGraph...")
    linked, link_failed = link_workers_to_animation_graph(spawned_names, stage, simulation_app)
    _progress(f"AnimationGraph linking: {linked} linked, {link_failed} failed")

    _progress("Warming up simulation to apply ScriptingAPI + AnimationGraphAPI...")
    _tick(120)

    return spawned_names, worker_behaviors


# --- Main ---

def main():
    parser = argparse.ArgumentParser(description="Run Isaac Sim Headless Generation")
    parser.add_argument("--config", type=str, default="configs/current_scene.json")
    parser.add_argument("--library", type=str, default="assets/library.json")
    args = parser.parse_args()

    _progress("Loading configs...")
    scene_config, asset_library = load_config(args.config, args.library)
    _progress(f"Layout: {scene_config.get('layout', 'standard_warehouse')}")

    _progress("Creating World...")
    world = World(stage_units_in_meters=1.0)
    _tick(5)
    stage = omni.usd.get_context().get_stage()

    _progress("Configuring SDG settings...")
    _configure_sdg_settings()

    _progress("Loading warehouse zone...")
    warehouse_prim = rep.create.from_usd(asset_library["zone"])
    with warehouse_prim:
        rep.modify.pose(scale=(1.7, 1.7, 2.0))
    _tick(5)

    _progress("Spawning warehouse layout...")
    spawn_bounds_min, spawn_bounds_max = spawn_warehouse_layout(scene_config, asset_library, stage)
    _tick(10)

    _progress("Baking navmesh for obstacle avoidance...")
    bake_navmesh(simulation_app=simulation_app)

    _progress("Computing camera placement (camera-first)...")
    hazard_zones = scene_config.get("hazard_zones", [])
    cam_pos, look_at_target, focal_length, chosen_mount = pick_camera_placement(scene_config, hazard_zones=hazard_zones)
    visible_bounds = compute_ground_visible_area(cam_pos, look_at_target, focal_length=focal_length)
    _progress(f"Camera position: ({cam_pos[0]:.2f}, {cam_pos[1]:.2f}, {cam_pos[2]:.2f})")
    _progress(f"Camera look_at: ({look_at_target[0]:.2f}, {look_at_target[1]:.2f}, {look_at_target[2]:.2f})")
    _progress(f"Visible spawn area: x=[{visible_bounds[0]:.2f}, {visible_bounds[1]:.2f}] y=[{visible_bounds[2]:.2f}, {visible_bounds[3]:.2f}]")

    _progress("Setting up camera and lighting...")
    camera, render_product = setup_camera_and_lighting(scene_config)
    _tick(5)

    if hazard_zones:
        _progress("Spawning hazard zones...")
        spawn_hazard_zones(hazard_zones, stage)

    spawned_asset_ids, entity_known_positions = _spawn_entities(
        scene_config, asset_library, stage, spawn_bounds_min, spawn_bounds_max,
        visible_bounds=visible_bounds,
    )

    spawned_worker_names, worker_behaviors = _setup_workers(
        scene_config, asset_library, stage, visible_bounds=visible_bounds,
    )
    workers = [e for e in scene_config.get("entities", []) if e.get("type") == "worker"]

    _worker_known_positions = []
    for wb in worker_behaviors:
        wid = wb.get("worker_id", "")
        for cmd in wb.get("commands", []):
            if cmd.get("command") == "GoTo":
                wx = cmd.get("x", 0.0)
                wy = cmd.get("y", 0.0)
                _worker_known_positions.append((wid, wx, wy))
                break

    for wid, wx, wy in _worker_known_positions:
        _progress(f"  Worker {wid} initial position: ({wx:.2f}, {wy:.2f})")

    for ent in scene_config.get("entities", []):
        _progress(f"  Entity: type={ent.get('type')}, asset_id={ent.get('asset_id')}, anchor_zone={ent.get('anchor_zone')}")

    _progress("Hiding driver prims...")
    hide_driver_prims(stage)

    _progress("Adjusting camera look_at to center on all spawned entities...")
    all_known_positions = entity_known_positions + [(wx, wy) for _, wx, wy in _worker_known_positions]
    _, post_entity_positions, post_worker_positions = compute_scene_centroid(
        stage, known_positions=all_known_positions
    )
    cam_pos, _ = pick_indoor_position(
        scene_config.get("camera_angles", []),
        hazard_zones=hazard_zones,
        entity_positions=post_entity_positions,
        worker_positions=post_worker_positions,
        preferred_mount=chosen_mount,
    )
    look_at_target = pick_look_at_target(post_entity_positions, post_worker_positions, hazard_zones)
    cam_pos, focal_length = fit_camera_to_entities(
        cam_pos, look_at_target, all_known_positions, focal_length=focal_length
    )
    visible_bounds = compute_ground_visible_area(cam_pos, look_at_target, focal_length=focal_length)
    _progress(f"Adjusted camera position: ({cam_pos[0]:.2f}, {cam_pos[1]:.2f}, {cam_pos[2]:.2f})")
    _progress(f"Adjusted look_at: ({look_at_target[0]:.2f}, {look_at_target[1]:.2f}, {look_at_target[2]:.2f})")
    _progress(f"Adjusted visible area: x=[{visible_bounds[0]:.2f}, {visible_bounds[1]:.2f}] y=[{visible_bounds[2]:.2f}, {visible_bounds[3]:.2f}]")

    _progress("Starting timeline for behavior scripts...")
    omni.timeline.get_timeline_interface().play()
    _progress("Warming up simulation for behavior initialization (300 steps)...")
    for _ in range(300):
        world.step(render=True)

    _progress("Injecting commands via AgentManager...")
    injected, inj_failed = inject_commands_after_play(
        spawned_worker_names, worker_behaviors, simulation_app=simulation_app,
        visible_bounds=visible_bounds,
    )
    _progress(f"Command injection: {injected} succeeded, {inj_failed} failed")

    _progress("Clearing unwanted semantics before generation...")
    clear_unwanted_warehouse_semantics(stage)

    _progress("Final semantic sync (60 steps)...")
    for _ in range(60):
        world.step(render=True)

    _progress("Initializing CocoWriter...")
    writer = _setup_coco_writer()
    writer.attach([render_product])

    _progress("Configuring camera trigger...")
    _configure_camera_trigger(camera, scene_config, cam_pos, look_at_target)

    _progress("Initializing vehicle animator...")
    vehicle_animator = VehicleAnimator(scene_config.get("vehicle_behaviors", []), stage, fps=30)

    _progress("Running simulation loop...")
    for step in range(NUM_FRAMES):
        if step % 100 == 0:
            _progress(f"Frame {step}/{NUM_FRAMES}")
        if step > 0 and step % REINJECT_INTERVAL == 0 and spawned_worker_names:
            reinject_random_commands(spawned_worker_names, visible_bounds=visible_bounds)
        vehicle_animator.update(step, NUM_FRAMES)
        for _ in range(SIM_STEPS_PER_FRAME):
            world.step(render=False)
        rep.orchestrator.step()

    _progress("Waiting for orchestrator to finish...")
    rep.orchestrator.wait_until_complete()

    _progress("Waiting for writer flush...")
    deadline = time.time() + 60
    while len(glob.glob("/tmp/dataset/Replicator/rgb_*.png")) < NUM_FRAMES:
        if time.time() > deadline:
            found = len(glob.glob("/tmp/dataset/Replicator/rgb_*.png"))
            print(f"[WARNING] Timed out waiting for writer flush ({found}/{NUM_FRAMES} files written).")
            break
        time.sleep(0.1)
        simulation_app.update()

    result = subprocess.run(["find", "/tmp/dataset", "-type", "f"], capture_output=True, text=True)
    _progress(f"Files written to /tmp/dataset: {len(result.stdout.strip().splitlines()) if result.stdout.strip() else 0}")

    _teardown(rep, writer, world, simulation_app)


if __name__ == "__main__":
    main()