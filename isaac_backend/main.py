import os
import sys
import json
import random
import argparse

# CRITICAL: Start SimulationApp BEFORE any omni/pxr imports
from isaacsim import SimulationApp
simulation_app = SimulationApp({"headless": True})

# Now it is safe to import omni, pxr, replicator
import omni.replicator.core as rep
from pxr import UsdGeom, Gf, UsdPhysics, PhysxSchema, Sdf
import omni.usd
import omni.physx
import omni.kit.commands
from isaacsim.storage.native import get_assets_root_path

# --- TASK 3.2: Config Ingestion ---
def load_config(config_path="configs/current_scene.json", library_path="assets/library.json"):
    try:
        with open(config_path, "r") as f:
            scene_config = json.load(f)
        with open(library_path, "r") as f:
            asset_library = json.load(f)
        # Resolve omniverse://localhost/NVIDIA/Assets to the local assets root
        # Fall back to NVIDIA's public CDN if no Nucleus server is available
        NVIDIA_CDN = "https://omniverse-content-production.s3-us-west-2.amazonaws.com/Assets"
        _raw = get_assets_root_path()
        assets_root = _raw if (_raw and _raw.startswith("omniverse://")) else NVIDIA_CDN
        asset_library = {
            k: v.replace("omniverse://localhost/NVIDIA/Assets", assets_root)
            for k, v in asset_library.items()
        }
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

# --- TASK 4.3: PPE Physics Attacher ---
def attach_ppe(worker_prim_path, ppe_state, asset_library):
    """
    Attaches PPE (hardhat, vest) using physics FixedJoints.
    """
    stage = omni.usd.get_context().get_stage()
    worker_prim = stage.GetPrimAtPath(worker_prim_path)
    
    # Normally, you'd target a specific bone (e.g., 'Head'). 
    # For now, we connect to the worker's root or a generic attachment point.
    head_bone_path = f"{worker_prim_path}/Head" # Example path
    
    if ppe_state.get('hardhat', False):
        hardhat_asset = asset_library.get("hardhat", "")
        # Create a hardhat prim
        hardhat_prim_path = f"{worker_prim_path}_hardhat"
        omni.kit.commands.execute('CreateReferenceCommand',
            usd_context=omni.usd.get_context(),
            path_to=hardhat_prim_path,
            asset_path=hardhat_asset,
            instanceable=False)
        
        hardhat_prim = stage.GetPrimAtPath(hardhat_prim_path)
        
        # Create a FixedJoint between Worker Head and Hardhat
        joint_path = f"{hardhat_prim_path}/FixedJoint"
        joint = UsdPhysics.FixedJoint.Define(stage, joint_path)
        
        # Configure the joint targets
        if stage.GetPrimAtPath(head_bone_path).IsValid():
            joint.GetBody0Rel().SetTargets([Sdf.Path(head_bone_path)])
        else:
            joint.GetBody0Rel().SetTargets([Sdf.Path(worker_prim_path)])
            
        joint.GetBody1Rel().SetTargets([Sdf.Path(hardhat_prim_path)])
        
        # Semantics
        apply_semantics(hardhat_prim_path, "Hardhat")

    if ppe_state.get('vest', False):
        # Similar logic for vest, attached to Spine/Torso
        pass

def setup_camera_and_lighting(config):
    # Default lighting
    rep.create.light(light_type="Dome", intensity=1000)

    # Main camera
    camera = rep.create.camera(position=(0, 5, 10), look_at=(0,0,0))
    render_product = rep.create.render_product(camera, (1024, 1024))
    
    return camera, render_product


def main():
    parser = argparse.ArgumentParser(description="Run Isaac Sim Headless Generation")
    parser.add_argument("--config", type=str, default="configs/current_scene.json", help="Path to the SceneConfig JSON")
    parser.add_argument("--library", type=str, default="assets/library.json", help="Path to the asset library JSON")
    args = parser.parse_args()

    scene_config, asset_library = load_config(args.config, args.library)
    
    # Setup scene elements
    camera, render_product = setup_camera_and_lighting(scene_config)

    # Spawn Entities based on Config
    for idx, entity in enumerate(scene_config.get("entities", [])):
        asset_type = entity.get("type", "worker")
        asset_id = entity.get("asset_id", "")
        usd_path = asset_library.get(asset_id, asset_library.get("worker"))
        
        # Default bounds
        b_min, b_max = (-5, -5), (5, 5)
        
        spawner = get_geofenced_spawner(usd_path, num_instances=1, bounds_min=b_min, bounds_max=b_max)
        
        # Actually trigger the spawner to register it in Replicator
        prims = spawner()
        
        # Apply semantics
        semantic_class = "Person" if asset_type == "worker" else "Vehicle" if asset_type == "vehicle" else "Zone"
        # In Replicator, the semantics need to be applied to the prims created
        with prims:
            rep.modify.semantics([("class", semantic_class)])

        # TODO: Dynamically handle attach_ppe in the loop if needed
        # Since replicator handles randomization per frame, static physics joints
        # should be built post-spawn or via Omnigraph.

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
    with rep.trigger.on_frame(num_frames=1000):
        # Add a randomizer for camera pan
        with camera:
            rep.modify.pose(
                position=rep.distribution.uniform((-10, 5, -10), (10, 10, 10)),
                look_at=(0,0,0)
            )

    print("Running Replicator generation...")
    rep.orchestrator.run()
    
    # Wait until completed
    while rep.orchestrator.get_is_started():
        simulation_app.update()

    simulation_app.close()
    print("Generation complete. Data saved to /tmp/dataset.")

if __name__ == "__main__":
    main()
