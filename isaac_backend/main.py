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
from isaac_backend.camera import positions_for_angles, pick_indoor_position, clamp_to_warehouse
from isaac_backend.lighting import setup_camera_and_lighting
from isaac_backend.semantics import clear_unwanted_warehouse_semantics, apply_scene_semantics
from isaac_backend.spawner import get_geofenced_spawner, spawn_hazard_zones
from isaac_backend.warehouse import spawn_warehouse_layout, hide_driver_prims
from isaac_backend.workers import spawn_workers
from isaac_backend.animation import (
    enable_behavior_extensions,
    setup_all_behaviors_async,
    ensure_biped_setup,
    link_workers_to_animation_graph,
    inject_commands_after_play,
)

COCO_CATEGORIES = {
    "person": {"name": "person", "id": 1, "supercategory": "worker"},
    "vehicle": {"name": "vehicle", "id": 2, "supercategory": "equipment"},
    "rack": {"name": "rack", "id": 3, "supercategory": "warehouse"},
    "pallet": {"name": "pallet", "id": 4, "supercategory": "warehouse"},
    "box": {"name": "box", "id": 5, "supercategory": "warehouse"},
    "barrel": {"name": "barrel", "id": 6, "supercategory": "warehouse"},
    "cone": {"name": "cone", "id": 7, "supercategory": "safety"},
    "fire_extinguisher": {"name": "fire_extinguisher", "id": 8, "supercategory": "safety"},
    "cart": {"name": "cart", "id": 9, "supercategory": "warehouse"},
    "sign": {"name": "sign", "id": 10, "supercategory": "safety"},
    "pillar": {"name": "pillar", "id": 11, "supercategory": "structure"},
    "hazard_zone_warning": {"name": "hazard_zone_warning", "id": 12, "supercategory": "zone"},
    "hazard_zone_restricted": {"name": "hazard_zone_restricted", "id": 13, "supercategory": "zone"},
    "hazard_zone_critical": {"name": "hazard_zone_critical", "id": 14, "supercategory": "zone"},
}

NUM_FRAMES = 200


# --- Helpers ---

def _tick(n):
    """Process n simulation app updates (loads assets, resolves references, no physics)."""
    for _ in range(n):
        simulation_app.update()


def compute_scene_centroid(stage):
    """Compute average position of scene entities and collect positions for camera framing.

    Returns ((cx, cy, cz), entity_positions, worker_positions).
    """
    xs, ys, zs = [], [], []
    entity_positions, worker_positions = [], []
    for prim in stage.Traverse():
        path = str(prim.GetPath())
        if not (path.startswith("/World/Characters/") or path.startswith("/World/Layout/") or path.startswith("/Replicator/")):
            continue
        xf = UsdGeom.Xformable(prim)
        if not xf:
            continue
        mat = xf.ComputeLocalToWorldTransform(Usd.TimeCode.Default())
        pos = mat.ExtractTranslation()
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
    _progress("CocoWriter initialized with 14 categories")
    return writer


def _configure_camera_trigger(camera, scene_config, look_at_target, entity_positions, worker_positions):
    """Set up the frame trigger with either fixed indoor position or orbit distribution."""
    angle_hints = scene_config.get("camera_angles", [])
    hazard_zones = scene_config.get("hazard_zones", [])
    camera_mode = scene_config.get("camera_mode", "indoor")
    camera_position_override = scene_config.get("camera_position")

    if camera_mode == "indoor":
        if camera_position_override:
            cam_x, cam_y, cam_z = clamp_to_warehouse(*camera_position_override)
            _progress(f"Camera override clamped to ({cam_x:.2f}, {cam_y:.2f}, {cam_z:.2f})")
        else:
            cam_x, cam_y, cam_z = pick_indoor_position(
                angle_hints, hazard_zones=hazard_zones,
                entity_positions=entity_positions,
                worker_positions=worker_positions or None,
            )
        camera_pos = (cam_x, cam_y, cam_z)
        _progress(f"Camera indoor: ({cam_x:.2f}, {cam_y:.2f}, {cam_z:.2f})")

        with rep.trigger.on_frame(num_frames=NUM_FRAMES):
            with camera:
                rep.modify.pose(position=camera_pos, look_at=look_at_target)
    else:
        scene_positions = positions_for_angles(
            angle_hints, hazard_zones=hazard_zones,
            entity_positions=entity_positions,
            worker_positions=worker_positions or None,
            mode="orbit",
        )
        from isaac_backend.camera import orbit_distribution
        camera_pos_dist = orbit_distribution(scene_positions)
        _progress(f"Camera orbit: {len(scene_positions)} positions")

        with rep.trigger.on_frame(num_frames=NUM_FRAMES):
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

def _spawn_entities(scene_config, asset_library, stage, spawn_bounds_min, spawn_bounds_max):
    """Spawn non-worker entities and return spawned_asset_ids."""
    others = [e for e in scene_config.get("entities", []) if e.get("type") != "worker"]
    spawned_asset_ids = []

    for entity in others:
        asset_id = entity.get("asset_id", "")
        if asset_id == "zone":
            continue
        usd_path = asset_library.get(asset_id)
        if usd_path is None:
            print(f"[WARNING] Unknown asset_id '{asset_id}'. Skipping.")
            continue

        spawner = get_geofenced_spawner(
            usd_path, num_instances=1,
            bounds_min=spawn_bounds_min, bounds_max=spawn_bounds_max,
        )
        prims = spawner()
        asset_type = entity.get("type", "")
        semantic_class = "vehicle" if asset_type == "vehicle" else asset_id
        print(f"[INFO] Spawning {asset_id} with semantic class '{semantic_class}'")
        with prims:
            rep.modify.semantics([("class", semantic_class)])
        spawned_asset_ids.append((asset_id, semantic_class))

    _progress(f"Spawned {len(spawned_asset_ids)} non-worker entities")
    return spawned_asset_ids


def _setup_workers(scene_config, asset_library, stage):
    """Spawn workers, set up animation, and return (spawned_worker_names, worker_behaviors)."""
    workers = [e for e in scene_config.get("entities", []) if e.get("type") == "worker"]
    worker_behaviors = scene_config.get("worker_behaviors", [])

    if not workers:
        return set(), worker_behaviors

    _progress("Enabling behavior extensions...")
    enable_behavior_extensions(simulation_app=simulation_app)

    _progress(f"Spawning {len(workers)} workers...")
    spawned_names = spawn_workers(workers, worker_behaviors, asset_library, stage, simulation_app)

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
    rep.create.from_usd(asset_library["zone"])
    _tick(5)

    _progress("Clearing semantics and spawning warehouse layout...")
    clear_unwanted_warehouse_semantics(stage)
    spawn_bounds_min, spawn_bounds_max = spawn_warehouse_layout(scene_config, asset_library, stage)
    _tick(10)

    _progress("Setting up camera and lighting...")
    camera, render_product = setup_camera_and_lighting(scene_config)
    _tick(5)

    hazard_zones = scene_config.get("hazard_zones", [])
    if hazard_zones:
        _progress("Spawning hazard zones...")
        spawn_hazard_zones(hazard_zones, stage)

    spawned_asset_ids = _spawn_entities(scene_config, asset_library, stage, spawn_bounds_min, spawn_bounds_max)

    spawned_worker_names, worker_behaviors = _setup_workers(scene_config, asset_library, stage)
    workers = [e for e in scene_config.get("entities", []) if e.get("type") == "worker"]

    _progress("Hiding driver prims...")
    hide_driver_prims(stage)

    _progress("Applying USD-level semantics to all scene prims...")
    apply_scene_semantics(stage, spawned_asset_ids, workers)

    _progress("Computing scene centroid for camera framing...")
    centroid, entity_positions, worker_positions = compute_scene_centroid(stage)
    look_at_target = (centroid[0], centroid[1], 1.0)

    _progress("Starting timeline for behavior scripts...")
    omni.timeline.get_timeline_interface().play()
    for _ in range(100):
        world.step(render=True)

    _progress("Injecting commands via AgentManager...")
    injected, inj_failed = inject_commands_after_play(
        spawned_worker_names, worker_behaviors, simulation_app=simulation_app
    )
    _progress(f"Command injection: {injected} succeeded, {inj_failed} failed")

    _progress("Initializing CocoWriter...")
    writer = _setup_coco_writer()
    writer.attach([render_product])

    _progress("Configuring camera trigger...")
    _configure_camera_trigger(camera, scene_config, look_at_target, entity_positions, worker_positions)

    _progress("Running simulation loop...")
    for step in range(NUM_FRAMES):
        if step % 100 == 0:
            _progress(f"Frame {step}/{NUM_FRAMES}")
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