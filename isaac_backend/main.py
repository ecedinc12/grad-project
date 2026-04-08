import os
import sys
import json
import random
import argparse
import glob
import time
import subprocess
import asyncio
import threading

from isaacsim import SimulationApp
simulation_app = SimulationApp({"headless": True})

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


def _progress(msg):
    print(f"[PROGRESS] [{time.strftime('%H:%M:%S')}] {msg}")
    sys.stdout.flush()

def main():
    parser = argparse.ArgumentParser(description="Run Isaac Sim Headless Generation")
    parser.add_argument("--config", type=str, default="configs/current_scene.json", help="Path to the SceneConfig JSON")
    parser.add_argument("--library", type=str, default="assets/library.json", help="Path to the asset library JSON")
    parser.add_argument("--commands", type=str, default="/tmp/people_commands.txt", help="Output path for generated people_commands.txt")
    args = parser.parse_args()

    _progress("Loading configs...")
    scene_config, asset_library = load_config(args.config, args.library)

    _progress("Creating World and initializing simulation context...")
    world = World(stage_units_in_meters=1.0)

    _init_error = []
    _init_done = threading.Event()

    def _run_init():
        _loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_loop)
        try:
            _loop.run_until_complete(world.initialize_simulation_context_async())
        except Exception as e:
            _init_error.append(e)
        finally:
            _loop.close()
            _init_done.set()

    _t = threading.Thread(target=_run_init, daemon=True)
    _t.start()
    while not _init_done.is_set():
        simulation_app.update()
    _t.join()
    if _init_error:
        raise _init_error[0]
    _progress("Simulation context initialized.")

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
    setup_navmesh()

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

    _progress(f"Spawning {len(others)} non-worker entities...")
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
    _progress("Non-worker entities spawned.")

    worker_behaviors = scene_config.get("worker_behaviors", [])
    if workers:
        _progress(f"Spawning {len(workers)} workers...")
        spawn_workers(workers, worker_behaviors, asset_library, stage)

        _progress("Waiting for S3 worker assets to resolve...")
        for _ in range(10):
            simulation_app.update()
        _progress("Asset resolution complete.")

    if worker_behaviors:
        _progress("Writing people command file...")
        write_command_file(worker_behaviors, args.commands)
    else:
        _progress("No worker_behaviors in config.")

    _progress("Hiding driver prims...")
    hide_driver_prims(stage)

    if workers and worker_behaviors:
        _progress("Enabling extensions...")
        enable_extensions()
        _progress("Setting up people simulation...")
        setup_people_simulation(args.commands)

    _progress("Initializing BasicWriter...")
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
    _progress(f"camera_angles={angle_hints}  →  {len(scene_positions)} orbit positions, chosen: {chosen_position}")

    _progress("Setting up frame trigger...")
    with rep.trigger.on_frame(num_frames=NUM_FRAMES):
        with camera:
            rep.modify.pose(
                position=chosen_position,
                look_at=(0, 0, 1.2)
            )

    _progress("Starting orchestrator...")
    rep.orchestrator.run_async()

    _progress("Resetting world...")
    world.reset()

    _progress(f"Running simulation loop: {NUM_FRAMES} frames...")
    for step in range(NUM_FRAMES):
        if step % 100 == 0:
            _progress(f"Frame {step}/{NUM_FRAMES}")
        world.step(render=True)

    _progress("Waiting for orchestrator to finish...")
    wait_start = time.time()
    while rep.orchestrator.get_status() == "running":
        if time.time() - wait_start > 10:
            print("[WARN] Timed out waiting for orchestrator to stop running.")
            break
        simulation_app.update()

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
