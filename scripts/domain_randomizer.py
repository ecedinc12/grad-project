"""
Domain Randomization Module for Industrial Safety Synthetic Data Pipeline.

This module handles visual and scene randomization to improve model generalization.
"""

from typing import List, Tuple, Optional, Dict, Any
import random
import numpy as np

from pxr import Usd, UsdGeom, UsdLux, Gf, Sdf, UsdPhysics
import omni.replicator.core as rep
from omni.isaac.core.utils.prims import create_prim, delete_prim


class DomainRandomizer:
    """
    Applies domain randomization to the USD stage.
    """
    
    def __init__(self, stage: Usd.Stage):
        """
        Initialize with a USD stage.
        
        Args:
            stage: The USD stage to randomize.
        """
        self.stage = stage
        self.distractor_paths: List[str] = []
        
    def randomize_lights(self, 
                        intensity_range: Tuple[float, float] = (0.5, 2.0),
                        color_temp_range: Tuple[float, float] = (3000, 6500)) -> None:
        """
        Randomize intensity and color temperature of all lights in the scene.
        
        Args:
            intensity_range: Min and max intensity multiplier.
            color_temp_range: Min and max color temperature in Kelvin.
        """
        # Iterate through all prims to find lights
        for prim in self.stage.Traverse():
            if prim.IsA(UsdLux.Light):
                light = UsdLux.Light(prim)
                
                # Randomize intensity
                if light.GetIntensityAttr():
                    base_intensity = light.GetIntensityAttr().Get()
                    if base_intensity is not None:
                        multiplier = random.uniform(*intensity_range)
                        new_intensity = max(0.0, base_intensity * multiplier)
                        light.GetIntensityAttr().Set(new_intensity)
                
                # Randomize color temperature if supported
                if prim.HasAttribute("inputs:colorTemperature"):
                    temp = random.uniform(*color_temp_range)
                    prim.GetAttribute("inputs:colorTemperature").Set(temp)
                
                print(f"[DomainRandomizer] Randomized light: {prim.GetPath()}")
    
    def randomize_materials(self, prim_paths: List[str]) -> None:
        """
        Randomize materials on specified prims using Replicator's material randomizer.
        
        Args:
            prim_paths: List of prim paths to randomize materials on.
        """
        try:
            # Get the material randomizer
            material_randomizer = rep.randomizer.materials()
            
            # Collect mesh prims from the specified paths
            mesh_prims = []
            for prim_path in prim_paths:
                prim = self.stage.GetPrimAtPath(prim_path)
                if not prim:
                    continue
                    
                # Recursively find all mesh prims under this path
                for child_prim in prim.GetAllChildren():
                    if child_prim.IsA(UsdGeom.Mesh):
                        mesh_prims.append(child_prim.GetPath().pathString)
            
            if not mesh_prims:
                print("[DomainRandomizer] No mesh prims found for material randomization")
                return
            
            # Create a replicator scope for the randomizer
            with rep.randomizer.materials():
                for mesh_path in mesh_prims:
                    # Apply random material
                    rep.randomizer.materials().apply(
                        prim_paths=[mesh_path],
                        materials=rep.randomizer.materials().get_materials()
                    )
            
            print(f"[DomainRandomizer] Randomized materials on {len(mesh_prims)} meshes")
            
        except Exception as e:
            print(f"[DomainRandomizer] Error randomizing materials: {e}")
    
    def spawn_distractors(self, n: int = 5) -> List[str]:
        """
        Spawn floating distractor primitives to test occlusion.
        
        Args:
            n: Number of distractors to spawn.
            
        Returns:
            List of paths to created distractor prims.
        """
        self.clear_distractors()  # Clear any existing distractors
        
        primitive_types = ["Cube", "Sphere", "Cone"]
        
        for i in range(n):
            prim_type = random.choice(primitive_types)
            prim_path = f"/World/Distractors/Distractor_{i}"
            
            # Create the primitive
            create_prim(
                prim_path=prim_path,
                prim_type=prim_type,
                attributes={
                    "size": random.uniform(0.2, 1.0),
                    "purpose": "render"
                }
            )
            
            # Set random position (above floor, within bounds)
            position = Gf.Vec3f(
                random.uniform(-8, 8),
                random.uniform(-8, 8),
                random.uniform(2, 6)  # Above floor
            )
            
            # Set random rotation
            rotation = Gf.Vec3f(
                random.uniform(0, 360),
                random.uniform(0, 360),
                random.uniform(0, 360)
            )
            
            # Set transform
            prim = self.stage.GetPrimAtPath(prim_path)
            if prim:
                xform = UsdGeom.Xformable(prim)
                xform.ClearXformOpOrder()
                
                translate_op = xform.AddTranslateOp()
                rotate_op = xform.AddRotateXYZOp()
                
                translate_op.Set(position)
                rotate_op.Set(Gf.Vec3f(
                    np.radians(rotation[0]),
                    np.radians(rotation[1]),
                    np.radians(rotation[2])
                ))
            
            # Make it kinematic (floating, not affected by gravity)
            if prim:
                # Enable rigid body but make it kinematic
                rigid_body_api = UsdPhysics.RigidBodyAPI.Apply(prim)
                rigid_body_api.CreateKinematicEnabledAttr().Set(True)
                rigid_body_api.CreateRigidBodyEnabledAttr().Set(True)
                
                # Add collision
                UsdPhysics.CollisionAPI.Apply(prim)
            
            self.distractor_paths.append(prim_path)
        
        print(f"[DomainRandomizer] Spawned {n} distractor primitives")
        return self.distractor_paths
    
    def clear_distractors(self) -> None:
        """
        Remove all distractor prims to prevent VRAM accumulation.
        """
        for path in self.distractor_paths:
            try:
                delete_prim(path)
            except Exception as e:
                print(f"[DomainRandomizer] Error deleting distractor {path}: {e}")
        
        self.distractor_paths.clear()
        print("[DomainRandomizer] Cleared all distractor prims")
    
    def randomize_frame(self) -> None:
        """
        Apply a full set of randomizations for a single frame.
        This is meant to be called each frame during data generation.
        """
        # Randomize lights with moderate ranges
        self.randomize_lights(
            intensity_range=(0.7, 1.5),
            color_temp_range=(3500, 5500)
        )
        
        # Randomly spawn or clear distractors (30% chance to change)
        if random.random() < 0.3:
            if self.distractor_paths:
                self.clear_distractors()
            else:
                self.spawn_distractors(n=random.randint(2, 5))
        
        print("[DomainRandomizer] Applied frame randomization")


if __name__ == "__main__":
    """
    Test the DomainRandomizer module.
    """
    print("=== DomainRandomizer Module Test ===")
    
    # Create a simple stage for testing
    import omni.usd
    context = omni.usd.get_context()
    stage = context.new_stage()
    
    if stage is None:
        print("ERROR: Failed to create stage")
        exit(1)
    
    print(f"Stage created: {stage.GetRootLayer().identifier}")
    
    # Create a simple light for testing
    from omni.isaac.core.utils.prims import create_prim
    create_prim(
        prim_path="/World/TestLight",
        prim_type="DomeLight",
        attributes={"inputs:intensity": 1.0}
    )
    
    # Create a simple mesh for material testing
    create_prim(
        prim_path="/World/TestMesh",
        prim_type="Cube",
        attributes={"size": 2.0}
    )
    
    # Initialize randomizer
    randomizer = DomainRandomizer(stage)
    
    # Test light randomization
    print("\n1. Testing light randomization...")
    randomizer.randomize_lights()
    
    # Test material randomization
    print("\n2. Testing material randomization...")
    randomizer.randomize_materials(["/World/TestMesh"])
    
    # Test distractor spawning
    print("\n3. Testing distractor spawning...")
    paths = randomizer.spawn_distractors(n=3)
    print(f"   Created {len(paths)} distractors")
    
    # Test distractor clearing
    print("\n4. Testing distractor clearing...")
    randomizer.clear_distractors()
    
    # Test full frame randomization
    print("\n5. Testing full frame randomization...")
    randomizer.randomize_frame()
    
    print("\n=== Test completed successfully ===")
    print("Note: Material randomization requires Replicator to be properly initialized.")
