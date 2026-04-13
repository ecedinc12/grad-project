import os
import sys
import json
import random
import argparse
import glob
import time
import subprocess


def _patch_fast_importer():
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
    print("[OK] Patched fast_importer.py for None submodule_search_locations")


_patch_fast_importer()

from isaacsim import SimulationApp
simulation_app = SimulationApp({"headless": True})

import omni.replicator.core as rep
import omni.usd
import omni.timeline
from omni.isaac.core import World
from pxr import Usd, UsdGeom

from isaac_backend.config_loader import load_config
from isaac_backend.camera import positions_for_angles, pick_indoor_position, clamp_to_warehouse
from isaac_backend.lighting import setup_camera_and_lighting
from isaac_backend.semantics import clear_unwanted_warehouse_semantics, apply_semantics
from isaac_backend.spawner import get_geofenced_spawner, spawn_hazard_zones
from isaac_backend.warehouse import spawn_warehouse_layout, hide_driver_prims
from isaac_backend.workers import spawn_workers
from isaac_backend.animation import setup_all_behaviors


def _progress(msg):
    print(f"[PROGRESS] [{time.strftime('%H:%M:%S')}] {msg}")
    sys.stdout.flush()

def _apply_scene_semantics(stage, spawned_asset_ids, workers):
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
    _progress("World created.")

    stage = omni.usd.get_context().get_stage()

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

    spawned_worker_names = set()
    if workers:
        _progress(f"Spawning {len(workers)} workers...")
        spawned_worker_names = spawn_workers(workers, worker_behaviors, asset_library, stage)

    if workers and worker_behaviors:
        _progress("Attaching IRA behavior scripts to workers...")
        attached, failed = setup_all_behaviors(
            spawned_worker_names, worker_behaviors, stage,
            simulation_app=simulation_app,
        )
        _progress(f"IRA behaviors: {attached} attached, {failed} failed")
    elif workers:
        _progress("Attaching idle-pose behaviors to workers (no commands)...")
        attached, failed = setup_all_behaviors(
            spawned_worker_names, [], stage,
            simulation_app=simulation_app,
        )
        _progress(f"IRA idle behaviors: {attached} attached, {failed} failed")

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

    _progress("Initializing BasicWriter...")
    writer = rep.WriterRegistry.get("BasicWriter")
    writer.initialize(
        output_dir="/tmp/dataset",
        rgb=True,
        bounding_box_2d_tight=True,
        semantic_segmentation=True,
        distance_to_camera=True,
        instance_segmentation=True,
    )
    writer.attach([render_product])

    NUM_FRAMES = 200
    angle_hints = scene_config.get("camera_angles", [])
    hazard_zones = scene_config.get("hazard_zones", [])
    camera_mode = scene_config.get("camera_mode", "indoor")
    camera_position_override = scene_config.get("camera_position")

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

    if camera_mode == "indoor":
        if camera_position_override:
            cam_x, cam_y, cam_z = clamp_to_warehouse(*camera_position_override)
            _progress(f"camera_positionOverride={camera_position_override} clamped to ({cam_x:.2f}, {cam_y:.2f}, {cam_z:.2f})")
        else:
            cam_x, cam_y, cam_z = pick_indoor_position(
                angle_hints, hazard_zones=hazard_zones,
                entity_positions=entity_positions,
                worker_positions=worker_positions or None,
            )
        camera_pos = (cam_x, cam_y, cam_z)
        _progress(f"camera_mode=indoor  camera_angles={angle_hints}  camera=({cam_x:.2f}, {cam_y:.2f}, {cam_z:.2f})  look_at=({look_at_target[0]:.2f}, {look_at_target[1]:.2f}, {look_at_target[2]:.2f})")

        _progress("Setting up frame trigger (fixed position)...")
        with rep.trigger.on_frame(num_frames=NUM_FRAMES):
            with camera:
                rep.modify.pose(position=camera_pos, look_at=look_at_target)
    else:
        scene_positions = positions_for_angles(angle_hints, hazard_zones=hazard_zones,
                                               entity_positions=entity_positions,
                                               worker_positions=worker_positions or None,
                                               mode="orbit")
        from isaac_backend.camera import orbit_distribution
        camera_pos_dist = orbit_distribution(scene_positions)
        _progress(f"camera_mode=orbit  camera_angles={angle_hints}  ->  {len(scene_positions)} positions")

        _progress("Setting up frame trigger (orbit distribution)...")
        with rep.trigger.on_frame(num_frames=NUM_FRAMES):
            with camera:
                rep.modify.pose(position=camera_pos_dist, look_at=look_at_target)

    _progress("Running simulation loop...")
    for step in range(NUM_FRAMES):
        if step % 100 == 0:
            _progress(f"Frame {step}/{NUM_FRAMES}")
        world.step()
        rep.orchestrator.step()

    _progress("Waiting for orchestrator to finish...")
    rep.orchestrator.wait_until_complete()

    _progress("Waiting for writer flush...")
    deadline = time.time() + 60
    while len(glob.glob("/tmp/dataset/bounding_box_2d_tight_*.npy")) < NUM_FRAMES:
        if time.time() > deadline:
            found = len(glob.glob("/tmp/dataset/bounding_box_2d_tight_*.npy"))
            print(f"[WARNING] Timed out waiting for writer flush ({found}/{NUM_FRAMES} files written).")
            break
        time.sleep(0.1)
        simulation_app.update()

    result = subprocess.run(
        ["find", "/tmp/dataset", "-type", "f"],
        capture_output=True, text=True
    )
    _progress(f"Files written to /tmp/dataset: {len(result.stdout.strip().splitlines()) if result.stdout.strip() else 0}")

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


if __name__ == "__main__":
    main()