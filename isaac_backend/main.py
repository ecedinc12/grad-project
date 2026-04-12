import os
import sys
import json
import random
import argparse
import glob
import time
import subprocess

# CRITICAL: Start SimulationApp BEFORE any omni/pxr imports
from isaacsim import SimulationApp
simulation_app = SimulationApp({"headless": True})

import carb
import omni.replicator.core as rep
import omni.kit.app
import omni.timeline
import omni.usd
from omni.isaac.core import World
from pxr import Usd, UsdGeom

from isaac_backend.config_loader import load_config
from isaac_backend.camera import positions_for_angles
from isaac_backend.lighting import setup_camera_and_lighting
from isaac_backend.semantics import clear_unwanted_warehouse_semantics, apply_semantics
from isaac_backend.spawner import get_geofenced_spawner, spawn_hazard_zones
from isaac_backend.warehouse import spawn_warehouse_layout, hide_driver_prims
from isaac_backend.workers import spawn_workers
from isaac_backend.people import (
    enable_extensions,
    setup_navmesh,
    setup_people_simulation,
    write_command_file,
)


def _progress(msg):
    print(f"[PROGRESS] [{time.strftime('%H:%M:%S')}] {msg}")
    sys.stdout.flush()

def _apply_scene_semantics(stage, spawned_asset_ids, workers):
    """Walk the stage and apply USD-level semantics to all prims that need them.

    This ensures BasicWriter can resolve semantic data and generate the JSON
    mapping files (semantic_id_to_labels.json, instance_segmentation_colors.json).
    """
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
    """Walk /World/Characters, /World/Layout, and /Replicator prims to find the average XY position."""
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
    parser.add_argument("--commands", type=str, default="/tmp/people_commands.txt", help="Output path for generated people_commands.txt")
    parser.add_argument("--anim-mode", type=str, default="people", choices=["people", "direct"],
                        help="Animation mode: 'people' uses omni.anim.people, 'direct' uses CharacterAnimator API")
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

    _progress("Setting up navmesh...")
    navmesh_ok = setup_navmesh(bounds_min=(-10, -10), bounds_max=(10, 10))

    _progress("Setting up camera and lighting...")
    camera, render_product = setup_camera_and_lighting(scene_config)
    for _ in range(5):
        simulation_app.update()

    hazard_zones = scene_config.get("hazard_zones", [])
    if hazard_zones:
        _progress("Spawning hazard zones...")
        spawn_hazard_zones(hazard_zones, stage)

    workers = [e for e in scene_config.get("entities", []) if e.get("type") == "worker"]
    others  = [e for e in scene_config.get("entities", []) if e.get("type") != "worker"]
    worker_behaviors = scene_config.get("worker_behaviors", [])

    if workers and worker_behaviors:
        _progress("Enabling people extension BEFORE spawning workers...")
        enable_extensions()
        for _ in range(10):
            simulation_app.update()

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

        _progress("Waiting for S3 worker assets to resolve...")
        for _ in range(15):
            simulation_app.update()
        _progress("Asset resolution complete.")

    if worker_behaviors:
        _progress("Writing people command file...")
        write_command_file(worker_behaviors, args.commands, worker_names=spawned_worker_names or None)
    else:
        _progress("No worker_behaviors in config.")

    _progress("Hiding driver prims...")
    hide_driver_prims(stage)

    _progress("Applying USD-level semantics to all scene prims...")
    _apply_scene_semantics(stage, spawned_asset_ids, workers)

    _progress("Computing scene centroid for camera framing...")
    look_at_target = compute_scene_centroid(stage)

    if workers and worker_behaviors:
        if args.anim_mode == "people":
            _progress("Setting up people simulation (command file mode)...")
            setup_people_simulation(args.commands, navmesh_enabled=navmesh_ok)
            for _ in range(15):
                simulation_app.update()
            _progress("Starting timeline for behavior scripts...")
            omni.timeline.get_timeline_interface().play()
            for _ in range(60):
                simulation_app.update()

            # Verify behavior scripts initialized
            behavior_count = 0
            for prim in stage.Traverse():
                path = str(prim.GetPath())
                if path.startswith("/World/Characters/") and prim.HasAttribute("omni:scripting:scripts"):
                    behavior_count += 1
            _progress(f"Behavior scripts attached to {behavior_count} character(s).")

        elif args.anim_mode == "direct":
            _progress("Setting up direct-mode animations...")
            omni.timeline.get_timeline_interface().play()
            for _ in range(15):
                simulation_app.update()
            from isaac_backend.animator import play_idle
            for prim in stage.Traverse():
                path = str(prim.GetPath())
                if path.startswith("/World/Characters/"):
                    play_idle(path, stage)
            for _ in range(15):
                simulation_app.update()
            _progress("Direct-mode animations active.")
    elif workers:
        _progress("No worker_behaviors — starting timeline for idle animations...")
        omni.timeline.get_timeline_interface().play()
        for _ in range(15):
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

    entity_positions = []
    for prim in stage.Traverse():
        path = str(prim.GetPath())
        if not (path.startswith("/World/Characters/") or path.startswith("/World/Layout/") or path.startswith("/Replicator/")):
            continue
        xf = UsdGeom.Xformable(prim)
        if xf:
            mat = xf.ComputeLocalToWorldTransform(Usd.TimeCode.Default())
            pos = mat.ExtractTranslation()
            entity_positions.append((pos[0], pos[1]))

    scene_positions = positions_for_angles(angle_hints, hazard_zones=hazard_zones, entity_positions=entity_positions)
    
    from isaac_backend.camera import orbit_distribution
    camera_pos_dist = orbit_distribution(scene_positions)
    _progress(f"camera_angles={angle_hints}  →  {len(scene_positions)} orbit positions, radius range: {min(p[0]**2+p[1]**2+p[2]**2 for p in scene_positions)**0.5:.1f}-{max(p[0]**2+p[1]**2+p[2]**2 for p in scene_positions)**0.5:.1f}m")

    _progress("Setting up frame trigger...")
    with rep.trigger.on_frame(num_frames=NUM_FRAMES):
        with camera:
            rep.modify.pose(
                position=camera_pos_dist,
                look_at=look_at_target
            )

    _progress("Running simulation loop: 1000 frames...")
    for step in range(NUM_FRAMES):
        if step % 100 == 0:
            _progress(f"Frame {step}/{NUM_FRAMES}")
        world.step(render=False)
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

    _progress("=== DATASET DEBUG ===")
    for ftype in ["rgb_", "bounding_box_2d_tight_", "semantic_segmentation_", "instance_segmentation_"]:
        count = len(glob.glob(f"/tmp/dataset/{ftype}*"))
        _progress(f"  {ftype}* files: {count}")
    sid_path = "/tmp/dataset/semantic_id_to_labels.json"
    if os.path.exists(sid_path):
        _progress(f"  semantic_id_to_labels.json: {json.load(open(sid_path))}")
    else:
        _progress("  semantic_id_to_labels.json: MISSING")
    isc_path = "/tmp/dataset/instance_segmentation_colors.json"
    if os.path.exists(isc_path):
        _progress(f"  instance_segmentation_colors.json: present")
        _progress(f"    content: {json.load(open(isc_path))}")
    else:
        _progress("  instance_segmentation_colors.json: MISSING")
    _progress("=== END DATASET DEBUG ===")

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
