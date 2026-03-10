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
        self._distractor_pool_size = 20
        self._pool_created = False
        
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
            if UsdLux.LightAPI(prim):
                light = UsdLux.LightAPI(prim)
                
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
        Randomize display color on specified prims (Direct USD version to avoid Graph bloat).
        
        Args:
            prim_paths: List of prim paths to randomize.
        """
        try:
            count = 0
            for prim_path in prim_paths:
                prim = self.stage.GetPrimAtPath(prim_path)
                if not prim:
                    continue
                    
                # Generate a random color
                color = Gf.Vec3f(random.random(), random.random(), random.random())
                
                # Apply to the prim itself if it's a mesh, or search children
                # Simplification: Apply to all meshes in the subtree
                for child in Usd.PrimRange(prim):
                    if child.IsA(UsdGeom.Mesh):
                        mesh = UsdGeom.Mesh(child)
                        # Set display color (diffuse)
                        mesh.GetDisplayColorAttr().Set([color])
                        count += 1
            
            # print(f"[DomainRandomizer] Randomized colors on {count} meshes")
            
        except Exception as e:
            print(f"[DomainRandomizer] Error randomizing materials: {e}")
    
    def _create_distractor_pool(self):
        """Initialize a pool of invisible distractors."""
        if self._pool_created:
            return

        primitive_types = ["Cube", "Sphere", "Cone"]
        parent_path = "/World/Distractors"
        
        for i in range(self._distractor_pool_size):
            prim_type = random.choice(primitive_types)
            prim_path = f"{parent_path}/Distractor_{i}"
            
            # Create the primitive
            create_prim(
                prim_path=prim_path,
                prim_type=prim_type,
                attributes={
                    "purpose": "render",
                    "visibility": "invisible"
                }
            )
            
            # Add physics (Dynamic Rigid Body)
            prim = self.stage.GetPrimAtPath(prim_path)
            if prim:
                # Transform ops
                xform = UsdGeom.Xformable(prim)
                xform.ClearXformOpOrder()
                xform.AddTranslateOp(UsdGeom.XformOp.PrecisionDouble)
                xform.AddOrientOp(UsdGeom.XformOp.PrecisionDouble)
                xform.AddScaleOp(UsdGeom.XformOp.PrecisionDouble)

                # Physics
                rigid_body_api = UsdPhysics.RigidBodyAPI.Apply(prim)
                rigid_body_api.CreateRigidBodyEnabledAttr().Set(True)
                # We want them to move with physics, so Kinematic=False
                rigid_body_api.CreateKinematicEnabledAttr().Set(False)
                
                # Add Mass API to ensure they have mass properties
                UsdPhysics.MassAPI.Apply(prim)
                
                UsdPhysics.CollisionAPI.Apply(prim)
            
            self.distractor_paths.append(prim_path)
        
        self._pool_created = True
        print(f"[DomainRandomizer] Created pool of {self._distractor_pool_size} distractors")

    def spawn_distractors(self, n: int = 5) -> List[str]:
        """
        Activate N distractors from the pool with random transforms.
        
        Args:
            n: Number of distractors to activate.
            
        Returns:
            List of paths to active distractor prims.
        """
        if not self._pool_created:
            self._create_distractor_pool()
            
        # Hide all first
        self.clear_distractors()
        
        # Pick N random indices
        indices = random.sample(range(self._distractor_pool_size), min(n, self._distractor_pool_size))
        active_paths = []
        
        for idx in indices:
            path = self.distractor_paths[idx]
            prim = self.stage.GetPrimAtPath(path)
            if not prim:
                continue
                
            # Randomize Transform
            position = Gf.Vec3f(
                random.uniform(-8, 8),
                random.uniform(-8, 8),
                random.uniform(2, 6)
            )
            rotation = Gf.Vec3f(
                random.uniform(0, 360),
                random.uniform(0, 360),
                random.uniform(0, 360)
            )
            scale = random.uniform(0.2, 1.0)
            
            xform = UsdGeom.Xformable(prim)
            # We know the op order because we set it in create
            # 0: translate, 1: rotate, 2: scale
            ops = xform.GetOrderedXformOps()
            if len(ops) >= 3:
                ops[0].Set(Gf.Vec3d(position[0], position[1], position[2]))
                rx = Gf.Rotation(Gf.Vec3d(1,0,0), rotation[0])
                ry = Gf.Rotation(Gf.Vec3d(0,1,0), rotation[1])
                rz = Gf.Rotation(Gf.Vec3d(0,0,1), rotation[2])
                q = (rz * ry * rx).GetQuat()
                ops[1].Set(Gf.Quatd(q.GetReal(), Gf.Vec3d(*q.GetImaginary())))
                ops[2].Set(Gf.Vec3d(scale, scale, scale))
            
            # Apply random velocity
            if prim.HasAPI(UsdPhysics.RigidBodyAPI):
                rb = UsdPhysics.RigidBodyAPI(prim)
                
                # Random linear velocity (drift)
                vel = Gf.Vec3f(
                    random.uniform(-2.0, 2.0), 
                    random.uniform(-2.0, 2.0), 
                    random.uniform(-1.0, 1.0)
                )
                rb.GetVelocityAttr().Set(vel)
                
                # Random angular velocity (spin)
                ang_vel = Gf.Vec3f(
                    random.uniform(-90, 90),
                    random.uniform(-90, 90),
                    random.uniform(-90, 90)
                )
                rb.GetAngularVelocityAttr().Set(ang_vel)

            # Make visible
            UsdGeom.Imageable(prim).MakeVisible()
            active_paths.append(path)
            
        print(f"[DomainRandomizer] Activated {len(active_paths)} distractors")
        return active_paths
    
    def clear_distractors(self) -> None:
        """
        Hide all distractor prims (return to pool).
        """
        for path in self.distractor_paths:
            prim = self.stage.GetPrimAtPath(path)
            if prim:
                UsdGeom.Imageable(prim).MakeInvisible()
                
                # Reset physics state to prevent them from "exploding" when re-appearing
                if prim.HasAPI(UsdPhysics.RigidBodyAPI):
                    rb = UsdPhysics.RigidBodyAPI(prim)
                    rb.GetVelocityAttr().Set(Gf.Vec3f(0,0,0))
                    rb.GetAngularVelocityAttr().Set(Gf.Vec3f(0,0,0))
        
        print("[DomainRandomizer] Reset distractor pool")
    
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
        
        # Randomly spawn or clear distractors (30% chance to change configuration)
        if random.random() < 0.3:
            if random.random() < 0.5:
                # Spawn new set
                self.spawn_distractors(n=random.randint(2, 6))
            else:
                # Clear existing
                self.clear_distractors()
        
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
