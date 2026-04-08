import os
import sys
import json
import random
import argparse
import glob
import time
import subprocess
import asyncio

from isaacsim import SimulationApp
simulation_app = SimulationApp({
    "headless": True,
    "argv": [
        "--/exts/semantics.schema.editor/enabled=false",
        "--/exts/semantics.schema.property/enabled=false",
    ],
})

import carb
import omni.replicator.core as rep
import omni.kit.app
import omni.usd
from omni.isaac.core import World

from isaac_backend.config_loader import load_config
from isaac_backend.camera import positions_for_angles
from isaac_backend.lighting import setup_camera_and_lighting
from isaac_backend.semantics import clear_unwanted_warehouse_semantics
from isaac_backend.spawner import get_geofenced_spawner, spawn_hazard_zones
from isaac_backend.warehouse import spawn_warehouse_layout, hide_driver_prims
from isaac_backend.workers import spawn_workers
from isaac_backend.people import (
    enable_extensions,
    setup_navmesh,
    setup_people_simulation,
    write_command_file,
)


def main():
    parser = argparse.ArgumentParser(description="Run Isaac Sim Headless Generation")
    parser.add_argument("--config", type=str, default="configs/current_scene.json", help="Path to the SceneConfig JSON")
    parser.add_argument("--library", type=str, default="assets/library.json", help="Path to the asset library JSON")
    parser.add_argument("--commands", type=str, default="/tmp/people_commands.txt", help="Output path for generated people_commands.txt")
    args = parser.parse_args()

    scene_config, asset_library = load_config(args.config, args.library)

    enable_extensions()

    rep.create.from_usd(asset_library["zone"])
    clear_unwanted_warehouse_semantics()
    spawn_warehouse_layout(asset_library)
    setup_navmesh()

    camera, render_product = setup_camera_and_lighting(scene_config)
    stage = omni.usd.get_context().get_stage()

    hazard_zones = scene_config.get("hazard_zones", [])
    if hazard_zones:
        spawn_hazard_zones(hazard_zones)

    world = World(stage_units_in_meters=1.0)
    asyncio.get_event_loop().run_until_complete(world.initialize_simulation_context_async())

    workers = [e for e in scene_config.get("entities", []) if e.get("type") == "worker"]
    others  = [e for e in scene_config.get("entities", []) if e.get("type") != "worker"]

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
        semantic_class = "vehicle" if asset_type == "vehicle" else "zone"
        with prims:
            rep.modify.semantics([("class", semantic_class)])

    worker_behaviors = scene_config.get("worker_behaviors", [])
    if workers:
        spawn_workers(workers, worker_behaviors, asset_library, stage)

        print("[INFO] Waiting for S3 worker assets to fully resolve...")
        for _ in range(15):
            simulation_app.update()
        print("[INFO] Asset resolution complete.")

    if worker_behaviors:
        write_command_file(worker_behaviors, args.commands)
    else:
        print("[INFO] No worker_behaviors in config — people_commands.txt not written.")

    hide_driver_prims()

    if workers and worker_behaviors:
        setup_people_simulation(args.commands)

    writer = rep.WriterRegistry.get("BasicWriter")
    writer.initialize(
        output_dir="/tmp/dataset",
        rgb=True,
        bounding_box_2d_tight=True,
        semantic_segmentation=True,
    )
    writer.attach([render_product])

    NUM_FRAMES = 1000
    angle_hints = scene_config.get("camera_angles", [])
    scene_positions = positions_for_angles(angle_hints)
    
    chosen_position = random.choice(scene_positions)
    print(f"[INFO] camera_angles={angle_hints}  →  {len(scene_positions)} orbit positions")
    print(f"[INFO] Chosen static camera position for sequence: {chosen_position}")

    with rep.trigger.on_frame(num_frames=NUM_FRAMES):
        with camera:
            rep.modify.pose(
                position=chosen_position,
                look_at=(0, 0, 1.2)
            )

    rep.orchestrator.run_async()

    for _ in range(5):
        simulation_app.update()

    world.reset()

    print(f"[INFO] Running simulation loop: {NUM_FRAMES} frames...")
    for step in range(NUM_FRAMES):
        world.step(render=True)

    wait_start = time.time()
    while rep.orchestrator.get_status() == "running":
        if time.time() - wait_start > 10:
            print("[WARN] Timed out waiting for orchestrator to stop running.")
            break
        simulation_app.update()

    deadline = time.time() + 60
    while len(glob.glob("/tmp/dataset/bounding_box_2d_tight_*.npy")) < NUM_FRAMES:
        if time.time() > deadline:
            found = len(glob.glob("/tmp/dataset/bounding_box_2d_tight_*.npy"))
            print(f"[WARNING] Timed out waiting for writer flush ({found}/{NUM_FRAMES} files written).")
            break
        simulation_app.update()

    result = subprocess.run(
        ["find", "/tmp/dataset", "-type", "f"],
        capture_output=True, text=True
    )
    print(f"[DEBUG] Files written to /tmp/dataset:\n{result.stdout[:2000] or '  (none)'}")

    try:
        rep.orchestrator.stop()
    except Exception as e:
        print(f"[WARN] teardown step failed: {e}", file=sys.stderr)

    for _ in range(3):
        simulation_app.update()

    try:
        writer.detach()
    except Exception as e:
        print(f"[WARN] teardown step failed: {e}", file=sys.stderr)

    try:
        world.clear()
    except Exception as e:
        print(f"[WARN] teardown step failed: {e}", file=sys.stderr)

    simulation_app.close()
    print("Generation complete. Data saved to /tmp/dataset.")
    sys.stdout.flush()
    os._exit(0)

if __name__ == "__main__":
    main()
