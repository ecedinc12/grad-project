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

def _build_orbit_positions(n=30, radius_min=3, radius_max=6,
                            azimuth_deg=(0, 360), elevation_deg=(20, 70)):
    """Pre-compute n camera positions on a hemisphere — all at safe distance from origin."""
    positions = []
    for i in range(n):
        az = math.radians(azimuth_deg[0] + (azimuth_deg[1] - azimuth_deg[0]) * i / n)
        el = math.radians(elevation_deg[0] + (elevation_deg[1] - elevation_deg[0]) * (i % 5) / 4)
        r  = radius_min + (radius_max - radius_min) * (i % 3) / 2
        x  = r * math.cos(el) * math.cos(az)
        y  = r * math.cos(el) * math.sin(az)
        z  = r * math.sin(el)   # Isaac Sim is Z-up
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

def apply_semantics(prim_path, class_name):
    """
    Applies semantic class to a given prim path using Replicator.
    """
    with rep.get.prims(path_pattern=prim_path):
        rep.modify.semantics([("class", class_name)])

def get_geofenced_spawner(asset_path, num_instances=1, bounds_min=(-10, -10), bounds_max=(10, 10)):
    """Spawn an entity at a random XY position on the floor within the given bounds."""
    def spawn_in_bounds():
        prims = rep.create.from_usd(asset_path, count=num_instances)
        with prims:
            rep.modify.pose(
                position=rep.distribution.uniform(
                    (bounds_min[0], bounds_min[1], 0),
                    (bounds_max[0], bounds_max[1], 0)
                ),
                rotation=rep.distribution.uniform((0, 0, 0), (0, 0, 360))
            )
        return prims
    
    rep.randomizer.register(spawn_in_bounds)
    return spawn_in_bounds

# --- Warehouse Layout Spawner ---
#
# Top-down layout (Z-up, Y = depth into warehouse):
#
#  Y= 7  ██ rack ██ rack ██ rack ██ rack ██ rack ██   ← back wall row
#  Y= 7  ░░pallet░░ pallet ░░ pallet ░░ pallet ░░
#
#  Y= 3  ██ rack ██ rack ██ rack ██ rack ██ rack ██   ← row A
#         ─────────── aisle (Y = 0) ───────────────
#  Y=-3  ██ rack ██ rack ██ rack ██ rack ██ rack ██   ← row B (mirrored)
#  Y=-3  ░░pallet░░ pallet ░░ pallet ░░ pallet ░░
#
#  Y=-6  [ boxes / barrels / cones scattered ]        ← staging / entry area
#
#  X positions: -6  -3   0   3   6

def spawn_warehouse_layout(asset_library):
    """Build an organised warehouse interior: rack rows, pallet staging, aisle clutter."""
    stage = omni.usd.get_context().get_stage()
    _idx = [0]
    spawned = 0

    def place(asset_id, x, y, z=0, rot_z=0):
        nonlocal spawned
        usd = asset_library.get(asset_id)
        if not usd:
            return
        path = f"/World/Layout/{asset_id}_{_idx[0]}"
        _idx[0] += 1
        omni.kit.commands.execute(
            "CreateReferenceCommand",
            usd_context=omni.usd.get_context(),
            path_to=path,
            asset_path=usd,
            instanceable=False,
        )
        prim = stage.GetPrimAtPath(path)
        if not prim.IsValid():
            return
        xf = UsdGeom.XformCommonAPI(prim)
        xf.SetTranslate(Gf.Vec3d(x, y, z))
        xf.SetRotate(Gf.Vec3f(0, 0, rot_z), UsdGeom.XformCommonAPI.RotationOrderXYZ)
        apply_semantics(path, "Clutter")
        spawned += 1

    rack_xs = [-6, -3, 0, 3, 6]

    # Back wall rack row + pallets in front of each bay
    for x in rack_xs:
        place("rack",   x,    7.0, rot_z=90)
        place("pallet", x,    5.8, rot_z=random.uniform(-20, 20))

    # Interior row A — faces inward (toward aisle)
    for x in rack_xs:
        place("rack", x, 3.0, rot_z=90)

    # Interior row B — mirrored across the center aisle
    for x in rack_xs:
        place("rack",   x,   -3.0, rot_z=270)
        place("pallet", x,   -1.8, rot_z=random.uniform(-20, 20))

    # Pallet staging cluster in the center aisle (Y ≈ 0)
    for dx, dy in [(-1.0, 0.0), (0.5, 0.2), (2.0, -0.3), (-2.5, 0.1)]:
        place("pallet", dx, dy, rot_z=random.uniform(0, 90))

    # Small clutter scattered through the center aisle and entry area
    small = ["box"] * 6 + ["barrel"] * 4 + ["cone"] * 4
    random.shuffle(small)
    # Center aisle band (Y = -1.5 → 1.5, full X width)
    for prop in small[:8]:
        place(prop,
              random.uniform(-5.5, 5.5),
              random.uniform(-1.5, 1.5),
              rot_z=random.uniform(0, 360))
    # Entry / staging area (Y = -4 → -6)
    for prop in small[8:]:
        place(prop,
              random.uniform(-5.0, 5.0),
              random.uniform(-6.0, -4.2),
              rot_z=random.uniform(0, 360))

    print(f"[INFO] Spawned {spawned} layout props.")


def hide_driver_prims():
    """Hide baked-in driver/operator meshes inside vehicle assets."""
    stage = omni.usd.get_context().get_stage()
    hidden = 0
    for prim in stage.Traverse():
        if "driver" in prim.GetName().lower():
            UsdGeom.Imageable(prim).MakeInvisible()
            print(f"[INFO] Hid driver prim: {prim.GetPath()}")
            hidden += 1
    if hidden == 0:
        print("[INFO] No driver prims found (forklift not in scene, or prim name differs).")


# --- Worker USD selector based on PPE state ---
def _select_worker_usd(ppe_state, asset_library):
    """Return the worker USD path based on whether PPE is worn."""
    if ppe_state.get("hardhat", False) or ppe_state.get("vest", False):
        return asset_library["worker_with_ppe"]
    return asset_library["worker_no_ppe"]

# Ceiling lamp grid positions (x, y) — warehouse interior approx ±6m
_CEILING_LAMP_XY = [(-4, -4), (0, -4), (4, -4), (-4, 0), (0, 0), (4, 0), (-4, 4), (0, 4), (4, 4)]
_CEILING_Z = 5.5  # approximate ceiling lamp height in metres

def setup_camera_and_lighting(config):
    condition = config.get("lighting_conditions", "daylight")
    params = LIGHTING_MAP.get(condition, LIGHTING_MAP["daylight"])
    print(f"[INFO] lighting_conditions={condition!r}  →  intensity={params['intensity']}, color={params['color']}")
    rep.create.light(light_type="Dome", intensity=params["intensity"], color=params["color"])

    if condition == "night":
        # Night = dark sky dome + artificial ceiling fixtures (warm white LED look)
        for x, y in _CEILING_LAMP_XY:
            rep.create.light(
                light_type="Sphere",
                intensity=600,
                color=(1.0, 0.97, 0.88),
                position=(x, y, _CEILING_Z),
                scale=0.15,
            )

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

    # Build organised warehouse interior layout
    spawn_warehouse_layout(asset_library)

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

        # Spawn entities in the center aisle / entry zone — clear of rack rows
        b_min, b_max = (-5, -2), (5, 2)

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

    # Hide baked-in driver meshes in vehicle assets
    hide_driver_prims()

    # Initialize BasicWriter for COCO format
    writer = rep.WriterRegistry.get("BasicWriter")
    writer.initialize(
        output_dir="/tmp/dataset",
        rgb=True,
        bounding_box_2d_tight=True,
        semantic_segmentation=True,
    )
    writer.attach([render_product])

    NUM_FRAMES = 1000
    # Build camera positions from LLM-provided angle hints
    angle_hints = scene_config.get("camera_angles", [])
    scene_positions = _positions_for_angles(angle_hints)
    print(f"[INFO] camera_angles={angle_hints}  →  {len(scene_positions)} orbit positions")

    with rep.trigger.on_frame(num_frames=NUM_FRAMES):
        with camera:
            rep.modify.pose(
                position=rep.distribution.choice(scene_positions),
                look_at=(0, 0, 1.2)   # human torso height (Z-up) — keeps workers centered
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
