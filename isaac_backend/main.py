import os
import sys
import json
import math
import random
import argparse
import glob
import time
import subprocess

# CRITICAL: Start SimulationApp BEFORE any omni/pxr imports
from isaacsim import SimulationApp
simulation_app = SimulationApp({"headless": True})

# Now it is safe to import omni, pxr, replicator
import omni.replicator.core as rep
from pxr import UsdGeom, Gf
import omni.usd
import omni.kit.commands
from isaacsim.storage.native import get_assets_root_path

def _build_orbit_positions(n=30, radius_min=10, radius_max=14,
                            azimuth_deg=(0, 360), elevation_deg=(20, 70)):
    """Pre-compute n camera positions on a hemisphere — all at safe distance from origin."""
    positions = []
    for i in range(n):
        az = math.radians(azimuth_deg[0] + (azimuth_deg[1] - azimuth_deg[0]) * i / n)
        el = math.radians(elevation_deg[0] + (elevation_deg[1] - elevation_deg[0]) * (i % 5) / 4)
        r  = radius_min + (radius_max - radius_min) * (i % 3) / 2
        x  = r * math.cos(el) * math.cos(az)
        z  = r * math.cos(el) * math.sin(az)
        y  = r * math.sin(el)   # Y-up; if stage is Z-up, swap y and z
        positions.append((x, y, z))
    return positions

ORBIT_POSITIONS = _build_orbit_positions()

ANGLE_ELEVATION_MAP = {
    "overhead":   (65, 85),
    "high_angle": (45, 65),
    "eye_level":  (15, 35),
    "low_angle":  (5,  20),
}

def _positions_for_angles(angle_hints):
    """Return orbit positions filtered to the requested elevation bands.
    Falls back to the full default hemisphere if hints are empty/unknown."""
    known = [h for h in angle_hints if h in ANGLE_ELEVATION_MAP]
    if not known:
        return ORBIT_POSITIONS
    el_min = min(ANGLE_ELEVATION_MAP[h][0] for h in known)
    el_max = max(ANGLE_ELEVATION_MAP[h][1] for h in known)
    return _build_orbit_positions(elevation_deg=(el_min, el_max))

LIGHTING_MAP = {
    "daylight": {"intensity": 1000, "color": (1.0,  0.98, 0.95)},
    "overcast": {"intensity":  500, "color": (0.85, 0.88, 0.95)},
    "dusk":     {"intensity":  300, "color": (1.0,  0.60, 0.30)},
    "night":    {"intensity":   50, "color": (0.20, 0.25, 0.40)},
}

# --- TASK 3.2: Config Ingestion ---
def load_config(config_path="configs/current_scene.json", library_path="assets/library.json"):
    try:
        with open(config_path, "r") as f:
            scene_config = json.load(f)
        with open(library_path, "r") as f:
            asset_library = json.load(f)
        return scene_config, asset_library
    except Exception as e:
        print(f"Failed to load configs from {config_path} or {library_path}: {e}")
        simulation_app.close() # Ensure we close the app so it doesn't hang!
        sys.exit(1)

# --- TASK 4.1: Semantics Applicator ---
def apply_semantics(prim_path, class_name):
    """
    Applies semantic class to a given prim path using Replicator.
    """
    with rep.get.prims(path_pattern=prim_path):
        rep.modify.semantics([("class", class_name)])

# --- TASK 4.2: Geofence Bounds ---
def get_geofenced_spawner(asset_path, num_instances=1, bounds_min=(-10, -10), bounds_max=(10, 10)):
    """
    Spawns entities strictly within bounded areas (Hazard Zones).
    Uses rep.randomizer.scatter_2d.
    """
    def spawn_in_bounds():
        prims = rep.create.from_usd(asset_path, count=num_instances)
        with prims:
            rep.randomizer.scatter_2d(
                surface_prims=None, # Usually requires a plane/surface, using default bounds
                seed=random.randint(0, 10000)
            )
            # Alternatively use randomizer for translation directly:
            rep.modify.pose(
                position=rep.distribution.uniform(
                    (bounds_min[0], 0, bounds_min[1]), 
                    (bounds_max[0], 0, bounds_max[1])
                ),
                rotation=rep.distribution.uniform((0, 0, 0), (0, 360, 0))
            )
        return prims
    
    rep.randomizer.register(spawn_in_bounds)
    return spawn_in_bounds

# --- Static Clutter Spawner ---
CLUTTER_ASSET_IDS = ["box", "barrel", "cone"]

def spawn_clutter(asset_library, count=15):
    """Scatter clutter objects on the floor at random positions."""
    stage = omni.usd.get_context().get_stage()
    available = [aid for aid in CLUTTER_ASSET_IDS if asset_library.get(aid)]
    if not available:
        print("[WARNING] No clutter assets in library — skipping clutter.")
        return

    spawned = 0
    for i in range(count):
        asset_id = random.choice(available)
        prim_path = f"/World/Clutter/{asset_id}_{i}"
        omni.kit.commands.execute(
            "CreateReferenceCommand",
            usd_context=omni.usd.get_context(),
            path_to=prim_path,
            asset_path=asset_library[asset_id],
            instanceable=False,
        )
        prim = stage.GetPrimAtPath(prim_path)
        if not prim.IsValid():
            continue
        xform = UsdGeom.XformCommonAPI(prim)
        xform.SetTranslate(Gf.Vec3d(random.uniform(-6, 6), 0, random.uniform(-6, 6)))
        xform.SetRotate(
            Gf.Vec3f(0, random.uniform(0, 360), 0),
            UsdGeom.XformCommonAPI.RotationOrderXYZ,
        )
        apply_semantics(prim_path, "Clutter")
        spawned += 1

    print(f"[INFO] Spawned {spawned} clutter objects.")


# --- Worker USD selector based on PPE state ---
def _select_worker_usd(ppe_state, asset_library):
    """Return the worker USD path based on whether PPE is worn."""
    if ppe_state.get("hardhat", False) or ppe_state.get("vest", False):
        return asset_library["worker_with_ppe"]
    return asset_library["worker_no_ppe"]

def setup_camera_and_lighting(config):
    condition = config.get("lighting_conditions", "daylight")
    params = LIGHTING_MAP.get(condition, LIGHTING_MAP["daylight"])
    print(f"[INFO] lighting_conditions={condition!r}  →  intensity={params['intensity']}, color={params['color']}")
    rep.create.light(light_type="Dome", intensity=params["intensity"], color=params["color"])

    camera = rep.create.camera(position=(0, 5, 10), look_at=(0, 0, 0))
    render_product = rep.create.render_product(camera, (1024, 1024))
    return camera, render_product


def main():
    parser = argparse.ArgumentParser(description="Run Isaac Sim Headless Generation")
    parser.add_argument("--config", type=str, default="configs/current_scene.json", help="Path to the SceneConfig JSON")
    parser.add_argument("--library", type=str, default="assets/library.json", help="Path to the asset library JSON")
    args = parser.parse_args()

    scene_config, asset_library = load_config(args.config, args.library)

    # Always load the warehouse shell — provides floor, walls, ceiling, lighting
    rep.create.from_usd(asset_library["zone"])

    # Scatter static clutter on the floor
    spawn_clutter(asset_library)

    # Setup scene elements
    camera, render_product = setup_camera_and_lighting(scene_config)

    # Spawn Entities based on Config
    for idx, entity in enumerate(scene_config.get("entities", [])):
        asset_type = entity.get("type", "worker")
        asset_id = entity.get("asset_id", "")
        if asset_id == "zone":          # already loaded above
            continue

        if asset_type == "worker":
            ppe_state = entity.get("ppe_state") or {}
            usd_path = _select_worker_usd(ppe_state, asset_library)
        else:
            usd_path = asset_library.get(asset_id)
            if usd_path is None:
                print(f"[WARNING] Unknown asset_id '{asset_id}' at index {idx}. Skipping.")
                continue

        # Default bounds
        b_min, b_max = (-5, -5), (5, 5)

        spawner = get_geofenced_spawner(usd_path, num_instances=1, bounds_min=b_min, bounds_max=b_max)

        # Actually trigger the spawner to register it in Replicator
        prims = spawner()

        # Apply semantics
        if asset_type == "worker":
            semantics = [("class", "Person")]
            if ppe_state.get("hardhat", False):
                semantics.append(("class", "Hardhat"))
            if ppe_state.get("vest", False):
                semantics.append(("class", "Vest"))
            with prims:
                rep.modify.semantics(semantics)
            print(f"[INFO] Worker {idx} ppe_state={ppe_state}")
        else:
            semantic_class = "Vehicle" if asset_type == "vehicle" else "Zone"
            with prims:
                rep.modify.semantics([("class", semantic_class)])

    # --- TASK 3.3: Replicator Writer ---
    # Initialize BasicWriter for COCO format
    writer = rep.WriterRegistry.get("BasicWriter")
    writer.initialize(
        output_dir="/tmp/dataset",
        rgb=True,
        bounding_box_2d_tight=True,
        semantic_segmentation=True,
    )
    writer.attach([render_product])

    # --- TASK 5.1: The SDG Trigger ---
    NUM_FRAMES = 1000
    # Build camera positions from LLM-provided angle hints
    angle_hints = scene_config.get("camera_angles", [])
    scene_positions = _positions_for_angles(angle_hints)
    print(f"[INFO] camera_angles={angle_hints}  →  {len(scene_positions)} orbit positions")

    with rep.trigger.on_frame(num_frames=NUM_FRAMES):
        with camera:
            rep.modify.pose(
                position=rep.distribution.choice(scene_positions),
                look_at=(0, 1.2, 0)   # human torso height — keeps workers centered
            )

    print("Running Replicator generation...")
    rep.orchestrator.run()

    # Phase 0: wait for orchestrator to START (run() is non-blocking)
    print(f"[DEBUG] get_is_started() right after run(): {rep.orchestrator.get_is_started()}")
    t0 = time.time()
    while not rep.orchestrator.get_is_started():
        simulation_app.update()
        if time.time() - t0 > 30:
            print("[WARNING] Orchestrator never became started after 30s — check scene setup.")
            break
    print(f"[DEBUG] Orchestrator started (took {time.time()-t0:.1f}s). get_is_started()={rep.orchestrator.get_is_started()}")

    # Phase 1: wait for orchestrator to FINISH scheduling frames
    while rep.orchestrator.get_is_started():
        simulation_app.update()
    print("[DEBUG] Phase 1 done — orchestrator finished.")

    # Diagnostic: show what was actually written
    result = subprocess.run(
        ["find", "/tmp/dataset", "-type", "f"],
        capture_output=True, text=True
    )
    print(f"[DEBUG] Files written to /tmp/dataset:\n{result.stdout[:2000] or '  (none)'}")

    # Phase 2: wait for BasicWriter's async I/O to flush .npy files to disk
    deadline = time.time() + 60  # 1-minute safety timeout
    while len(glob.glob("/tmp/dataset/bounding_box_2d_tight_*.npy")) < NUM_FRAMES:
        if time.time() > deadline:
            found = len(glob.glob("/tmp/dataset/bounding_box_2d_tight_*.npy"))
            print(f"[WARNING] Timed out waiting for writer flush ({found}/{NUM_FRAMES} files written).")
            break
        simulation_app.update()

    simulation_app.close()
    print("Generation complete. Data saved to /tmp/dataset.")

if __name__ == "__main__":
    main()
