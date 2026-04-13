"""
Isaac Sim 5.1 Industrial Safety SDG Pipeline — Main Entry Point

Bootstraps headless simulation, assembles the scene from SceneConfig JSON,
runs Replicator with CocoWriter, and outputs COCO-format dataset to /tmp/dataset.

CRITICAL: SimulationApp MUST be created BEFORE any omni.* or pxr.* imports.
"""

import os
import sys
import json
import glob
import time
import asyncio
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


def _progress(msg):
    print(f"[PROGRESS] [{time.strftime('%H:%M:%S')}] {msg}")
    sys.stdout.flush()


_patch_fast_importer()

from isaacsim import SimulationApp

simulation_app = SimulationApp({
    "headless": True,
    "renderer": "RayTracedLighting",
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
from isaac_backend.semantics import clear_unwanted_warehouse_semantics, apply_usd_semantics
from isaac_backend.spawner import get_geofenced_spawner, spawn_hazard_zones
from isaac_backend.warehouse import spawn_warehouse_layout, hide_driver_prims
from isaac_backend.workers import spawn_workers
from isaac_backend.animation import enable_behavior_extensions, setup_all_behaviors_async, _wait_for_async, _run_with_app_pumps

COCO_CATEGORIES = {
    "person": {"name": "person", "id": 1, "supercategory": "worker", "color": [255, 0, 0, 255], "isthing": 1},
    "vehicle": {"name": "vehicle", "id": 2, "supercategory": "equipment", "color": [0, 255, 0, 255], "isthing": 1},
    "rack": {"name": "rack", "id": 3, "supercategory": "warehouse", "color": [0, 0, 255, 255], "isthing": 1},
    "pallet": {"name": "pallet", "id": 4, "supercategory": "warehouse", "color": [255, 255, 0, 255], "isthing": 1},
    "box": {"name": "box", "id": 5, "supercategory": "warehouse", "color": [255, 0, 255, 255], "isthing": 1},
    "barrel": {"name": "barrel", "id": 6, "supercategory": "warehouse", "color": [0, 255, 255, 255], "isthing": 1},
    "cone": {"name": "cone", "id": 7, "supercategory": "safety", "color": [255, 128, 0, 255], "isthing": 1},
    "fire_extinguisher": {"name": "fire_extinguisher", "id": 8, "supercategory": "safety", "color": [255, 0, 128, 255], "isthing": 1},
    "cart": {"name": "cart", "id": 9, "supercategory": "warehouse", "color": [128, 255, 0, 255], "isthing": 1},
    "sign": {"name": "sign", "id": 10, "supercategory": "safety", "color": [128, 0, 255, 255], "isthing": 1},
    "pillar": {"name": "pillar", "id": 11, "supercategory": "structure", "color": [0, 128, 255, 255], "isthing": 1},
    "hazard_zone_warning": {"name": "hazard_zone_warning", "id": 12, "supercategory": "zone", "color": [255, 255, 0, 128], "isthing": 0},
    "hazard_zone_restricted": {"name": "hazard_zone_restricted", "id": 13, "supercategory": "zone", "color": [255, 128, 0, 128], "isthing": 0},
    "hazard_zone_critical": {"name": "hazard_zone_critical", "id": 14, "supercategory": "zone", "color": [255, 0, 0, 128], "isthing": 0},
}


def _apply_scene_semantics(stage, spawned_asset_ids, workers):
    """Walk the stage and apply USD-level semantics to all prims that need them."""

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

    applied = 0

    for asset_id, semantic_class in spawned_asset_ids:
        target_name = os.path.basename(asset_id)
        for prim in stage.Traverse():
            path = str(prim.GetPath())
            if not prim.IsValid():
                continue
            if target_name in path:
                parent = prim
                found = False
                while parent and parent.IsValid():
                    if parent.HasAttribute("semantic:Semantics:params:semanticData"):
                        found = True
                        break
                    parent = parent.GetParent()
                if not found and not prim.HasAttribute("semantic:Semantics:params:semanticData"):
                    set_semantic(prim, semantic_class)
                    applied += 1
                    print(f"[INFO] Applied USD semantics '{semantic_class}' to {path}")
                    break

    if workers:
        for prim in stage.Traverse():
            path = str(prim.GetPath())
            if path.startswith("/World/Characters/") and prim.GetTypeName() == "Xform":
                if not prim.HasAttribute("semantic:Semantics:params:semanticData"):
                    set_semantic(prim, "person")
                    applied += 1
                    print(f"[INFO] Applied USD semantics 'person' to {path}")

    _progress(f"Applied USD-level semantics to {applied} prims.")


def compute_scene_centroid(stage):
    """Walk /World/Characters, /World/Layout, and /Replicator prims to find average position."""
    xs, ys, zs = [], [], []
    for prim in stage.Traverse():
        path = str(prim.GetPath())
        if not (path.startswith("/World/Characters/") or path.startswith("/World/Layout/") or path.startswith("/Replicator/")):
            continue
        xf = UsdGeom.Xformable(prim)
        if xf:
            mat = xf.ComputeLocalToWorldTransform(Usd.TimeCode.Default())
            pos = mat.ExtractTranslation()
            xs.append(pos[0])
            ys.append(pos[1])
            zs.append(pos[2])
    if not xs:
        _progress("[WARN] No entities found for centroid calculation, defaulting to (0, 0, 1.2)")
        return (0.0, 0.0, 1.2)
    cx = sum(xs) / len(xs)
    cy = sum(ys) / len(ys)
    cz = sum(zs) / len(zs)
    _progress(f"Scene centroid computed: ({cx:.2f}, {cy:.2f}, {cz:.2f}) from {len(xs)} entities")
    return (cx, cy, cz)


def _configure_sdg_settings():
    """Apply recommended settings for synthetic data generation."""
    settings = carb.settings.get_settings()
    settings.set("/rtx/post/dlss/execMode", 2)
    settings.set("/exts/isaacsim.core.throttling/enable_async", False)
    rep.orchestrator.set_capture_on_play(False)
    _progress("SDG settings configured: DLSS=Quality, capture_on_play=False, throttling_async=False")


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
    _progress("CocoWriter initialized with 14 categories (including hazard zones)")
    return writer


def _collect_entity_positions(stage):
    """Gather all entity and worker positions for camera framing."""
    entity_positions = []
    worker_positions = []
    for prim in stage.Traverse():
        path = str(prim.GetPath())
        if not (path.startswith("/World/Characters/") or path.startswith("/World/Layout/") or path.startswith("/Replicator/")):
            continue
        xf = UsdGeom.Xformable(prim)
        if xf:
            mat = xf.ComputeLocalToWorldTransform(Usd.TimeCode.Default())
            pos = mat.ExtractTranslation()
            entity_positions.append((pos[0], pos[1]))
            if path.startswith("/World/Characters/"):
                worker_positions.append((pos[0], pos[1]))
    return entity_positions, worker_positions


def _configure_camera_trigger(camera, scene_config, look_at_target):
    """Set up the frame trigger with either fixed indoor position or orbit distribution."""
    num_frames = 200
    angle_hints = scene_config.get("camera_angles", [])
    hazard_zones = scene_config.get("hazard_zones", [])
    camera_mode = scene_config.get("camera_mode", "indoor")
    camera_position_override = scene_config.get("camera_position")

    stage = omni.usd.get_context().get_stage()
    entity_positions, worker_positions = _collect_entity_positions(stage)

    if camera_mode == "indoor":
        if camera_position_override:
            cam_x, cam_y, cam_z = clamp_to_warehouse(*camera_position_override)
            _progress(f"camera_position_override={camera_position_override} clamped to ({cam_x:.2f}, {cam_y:.2f}, {cam_z:.2f})")
        else:
            cam_x, cam_y, cam_z = pick_indoor_position(
                angle_hints, hazard_zones=hazard_zones,
                entity_positions=entity_positions,
                worker_positions=worker_positions or None,
            )
        camera_pos = (cam_x, cam_y, cam_z)
        _progress(f"camera_mode=indoor  camera_angles={angle_hints}  camera=({cam_x:.2f}, {cam_y:.2f}, {cam_z:.2f})  look_at=({look_at_target[0]:.2f}, {look_at_target[1]:.2f}, {look_at_target[2]:.2f})")

        with rep.trigger.on_frame(num_frames=num_frames):
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
        _progress(f"camera_mode=orbit  camera_angles={angle_hints}  ->  {len(scene_positions)} positions")

        with rep.trigger.on_frame(num_frames=num_frames):
            with camera:
                rep.modify.pose(position=camera_pos_dist, look_at=look_at_target)

    return num_frames


def _teardown(rep, writer, world, simulation_app):
    """Clean teardown in the correct order to avoid crashes."""
    try:
        rep.orchestrator.stop()
    except Exception as e:
        print(f"[WARN] teardown step failed: {e}", file=sys.stderr)

    try:
        writer.detach()
    except Exception as e:
        print(f"[WARN] teardown step failed: {e}", file=sys.stderr)

    try:
        world.clear()
    except Exception as e:
        print(f"[WARN] teardown step failed: {e}", file=sys.stderr)

    simulation_app.close()
    _progress("Generation complete. Data saved to /tmp/dataset.")
    sys.stdout.flush()
    os._exit(0)


def main():
    parser = argparse.ArgumentParser(description="Run Isaac Sim Headless Generation")
    parser.add_argument("--config", type=str, default="configs/current_scene.json", help="Path to the SceneConfig JSON")
    parser.add_argument("--library", type=str, default="assets/library.json", help="Path to the asset library JSON")
    args = parser.parse_args()

    _progress("Loading configs...")
    scene_config, asset_library = load_config(args.config, args.library)

    _progress("Creating World...")
    world = World(stage_units_in_meters=1.0)
    for _ in range(5):
        simulation_app.update()

    stage = omni.usd.get_context().get_stage()

    _progress("Configuring SDG settings...")
    _configure_sdg_settings()

    _progress("Loading warehouse zone...")
    rep.create.from_usd(asset_library["zone"])
    for _ in range(5):
        simulation_app.update()

    _progress("Clearing semantics and spawning warehouse layout...")
    clear_unwanted_warehouse_semantics(stage)
    spawn_warehouse_layout(asset_library, stage)
    for _ in range(10):
        simulation_app.update()

    _progress("Setting up camera and lighting...")
    camera, render_product = setup_camera_and_lighting(scene_config)
    for _ in range(5):
        simulation_app.update()

    hazard_zones = scene_config.get("hazard_zones", [])
    if hazard_zones:
        _progress("Spawning hazard zones...")
        spawn_hazard_zones(hazard_zones, stage)

    workers = [e for e in scene_config.get("entities", []) if e.get("type") == "worker"]
    others = [e for e in scene_config.get("entities", []) if e.get("type") != "worker"]
    worker_behaviors = scene_config.get("worker_behaviors", [])

    _progress(f"Spawning {len(others)} non-worker entities...")
    spawned_asset_ids = []
    for entity in others:
        asset_id = entity.get("asset_id", "")
        if asset_id == "zone":
            continue
        usd_path = asset_library.get(asset_id)
        if usd_path is None:
            print(f"[WARNING] Unknown asset_id '{asset_id}'. Skipping.")
            continue

        b_min, b_max = (-5, -2), (5, 2)
        spawner = get_geofenced_spawner(usd_path, num_instances=1, bounds_min=b_min, bounds_max=b_max)
        prims = spawner()
        asset_type = entity.get("type", "")
        semantic_class = "vehicle" if asset_type == "vehicle" else asset_id
        print(f"[INFO] Spawning {asset_id} with semantic class '{semantic_class}'")
        with prims:
            rep.modify.semantics([("class", semantic_class)])
        spawned_asset_ids.append((asset_id, semantic_class))
    _progress("Non-worker entities spawned.")

    if workers:
        _progress("Enabling behavior extensions...")
        enable_behavior_extensions(simulation_app=simulation_app)

    spawned_worker_names = set()
    if workers:
        _progress(f"Spawning {len(workers)} workers...")
        spawned_worker_names = spawn_workers(workers, worker_behaviors, asset_library, stage)

    if workers:
        _progress("Attaching IRA behavior scripts to workers...")
        attached, failed = _wait_for_async(
            setup_all_behaviors_async(spawned_worker_names, worker_behaviors, stage),
            simulation_app,
        )
        _progress(f"IRA behaviors: {attached} attached, {failed} failed")

    _progress("Hiding driver prims...")
    hide_driver_prims(stage)

    _progress("Applying USD-level semantics to all scene prims...")
    _apply_scene_semantics(stage, spawned_asset_ids, workers)

    _progress("Computing scene centroid for camera framing...")
    centroid = compute_scene_centroid(stage)
    look_at_target = (centroid[0], centroid[1], 1.0)

    _progress("Starting timeline for behavior scripts...")
    omni.timeline.get_timeline_interface().play()
    for _ in range(30):
        simulation_app.update()

    _progress("Initializing CocoWriter...")
    writer = _setup_coco_writer()
    writer.attach([render_product])

    _progress("Configuring camera trigger...")
    num_frames = _configure_camera_trigger(camera, scene_config, look_at_target)

    _progress("Running simulation loop...")
    for step in range(num_frames):
        if step % 100 == 0:
            _progress(f"Frame {step}/{num_frames}")
        world.step(render=False)
        rep.orchestrator.step()

    _progress("Waiting for orchestrator to finish...")
    rep.orchestrator.wait_until_complete()

    _progress("Waiting for writer flush...")
    deadline = time.time() + 60
    while len(glob.glob("/tmp/dataset/bounding_box_2d_tight_*.npy")) < num_frames:
        if time.time() > deadline:
            found = len(glob.glob("/tmp/dataset/bounding_box_2d_tight_*.npy"))
            print(f"[WARNING] Timed out waiting for writer flush ({found}/{num_frames} files written).")
            break
        time.sleep(0.1)
        simulation_app.update()

    result = subprocess.run(
        ["find", "/tmp/dataset", "-type", "f"],
        capture_output=True, text=True
    )
    _progress(f"Files written to /tmp/dataset: {len(result.stdout.strip().splitlines()) if result.stdout.strip() else 0}")

    _teardown(rep, writer, world, simulation_app)


if __name__ == "__main__":
    main()
