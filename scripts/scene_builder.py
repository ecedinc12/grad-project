"""
Scene Builder Module for Industrial Safety Synthetic Data Pipeline.

This module handles the construction of 3D digital twins of industrial zones
using USD (Universal Scene Description) with a focus on photorealism,
physics fidelity, and VRAM optimization.
"""

import omni.usd
from pxr import Usd, UsdGeom, Sdf, Gf, UsdPhysics
import omni.isaac.core.utils.stage as stage_utils
from omni.isaac.core.utils.prims import create_prim
from typing import Optional, Dict, Any
import numpy as np


class SceneBuilder:
    """Constructs and configures the base industrial environment."""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        """
        Initialize the SceneBuilder.
        
        Args:
            config: Configuration dictionary for scene parameters.
        """
        self.config = config or {}
        self._stage: Optional[Usd.Stage] = None
        self._physics_scene_path = "/World/PhysicsScene"
        self._asset_instances: Dict[str, list] = {}
        
    @property
    def stage(self) -> Usd.Stage:
        """Get the current USD stage, creating one if necessary."""
        if self._stage is None:
            self._stage = omni.usd.get_context().get_stage()
            if self._stage is None:
                self._stage = omni.usd.get_context().new_stage()
        return self._stage
    
    def create_stage(self, up_axis: str = "Z", meters_per_unit: float = 1.0) -> None:
        """
        Initialize the stage with correct up-axis and units.
        
        Args:
            up_axis: Up axis for the stage ("Z" or "Y").
            meters_per_unit: Unit scale (1.0 for meters).
        """
        # Ensure we have a valid stage
        self._stage = self.stage
        
        # Set stage metadata
        UsdGeom.SetStageUpAxis(self._stage, 
                               UsdGeom.Tokens.z if up_axis.upper() == "Z" else UsdGeom.Tokens.y)
        UsdGeom.SetStageMetersPerUnit(self._stage, meters_per_unit)
        
        print(f"[SceneBuilder] Stage initialized: {self._stage.GetRootLayer().identifier}")
        print(f"[SceneBuilder] Up axis: {up_axis}, Units: {meters_per_unit} meters")
    
    def setup_physics(self, 
                      gravity: Gf.Vec3f = Gf.Vec3f(0.0, 0.0, -9.81),
                      broadphase_type: str = "MBP",
                      solver_type: str = "TGS",
                      enable_gpu_dynamics: bool = True) -> None:
        """
        Configure PhysicsScene for GPU dynamics.
        
        Args:
            gravity: Gravity vector (m/s²).
            broadphase_type: Broadphase algorithm ("MBP", "PCM", "ABP").
            solver_type: Solver type ("TGS" or "PGS").
            enable_gpu_dynamics: Enable GPU acceleration for physics.
        """
        # Create or get the physics scene prim
        if not self.stage.GetPrimAtPath(self._physics_scene_path):
            physics_scene = UsdPhysics.Scene.Define(self.stage, self._physics_scene_path)
            physics_scene.CreateGravityAttr().Set(gravity)
        else:
            physics_scene = UsdPhysics.Scene.Get(self.stage, self._physics_scene_path)
        
        # Configure PhysX-specific settings
        prim = self.stage.GetPrimAtPath(self._physics_scene_path)
        
        # Set attributes if they don't exist
        if not prim.HasAttribute("physxScene:broadphaseType"):
            prim.CreateAttribute("physxScene:broadphaseType", Sdf.ValueTypeNames.Token)
        prim.GetAttribute("physxScene:broadphaseType").Set(broadphase_type)
        
        if not prim.HasAttribute("physxScene:solverType"):
            prim.CreateAttribute("physxScene:solverType", Sdf.ValueTypeNames.Token)
        prim.GetAttribute("physxScene:solverType").Set(solver_type)
        
        if not prim.HasAttribute("physxScene:enableGPUDynamics"):
            prim.CreateAttribute("physxScene:enableGPUDynamics", Sdf.ValueTypeNames.Bool)
        prim.GetAttribute("physxScene:enableGPUDynamics").Set(enable_gpu_dynamics)
        
        print(f"[SceneBuilder] Physics configured: "
              f"Gravity={gravity}, Broadphase={broadphase_type}, "
              f"Solver={solver_type}, GPU Dynamics={enable_gpu_dynamics}")
    
    def setup_lighting(self, 
                       hdri_path: Optional[str] = None,
                       dome_intensity: float = 1.0,
                       distant_intensity: float = 500.0) -> None:
        """
        Set up default HDRI and distant lighting.
        
        Args:
            hdri_path: Path to HDRI USD file. If None, uses a simple dome light.
            dome_intensity: Intensity of the dome light.
            distant_intensity: Intensity of the distant light.
        """
        # Add Dome Light (HDRI or simple)
        dome_light_path = "/World/DomeLight"
        if not self.stage.GetPrimAtPath(dome_light_path):
            if hdri_path and hdri_path.endswith('.usd'):
                try:
                    stage_utils.add_reference_to_stage(
                        usd_path=hdri_path,
                        prim_path=dome_light_path
                    )
                    print(f"[SceneBuilder] HDRI loaded from: {hdri_path}")
                except Exception as e:
                    print(f"[SceneBuilder] Failed to load HDRI {hdri_path}: {e}. Using default dome.")
                    self._create_dome_light(dome_light_path, dome_intensity)
            else:
                self._create_dome_light(dome_light_path, dome_intensity)
        
        # Add Distant Light for directional shadows
        distant_light_path = "/World/DistantLight"
        if not self.stage.GetPrimAtPath(distant_light_path):
            create_prim(
                prim_path=distant_light_path,
                prim_type="DistantLight",
                attributes={
                    "inputs:intensity": distant_intensity,
                    "inputs:angle": 0.53  # ~30 degrees for softer shadows
                }
            )
            print(f"[SceneBuilder] Distant light added with intensity {distant_intensity}")
    
    def _create_dome_light(self, path: str, intensity: float) -> None:
        """Create a simple dome light as fallback."""
        create_prim(
            prim_path=path,
            prim_type="DomeLight",
            attributes={
                "inputs:intensity": intensity,
                "inputs:texture:format": "latlong"
            }
        )
    
    def add_asset_instance(self, 
                          usd_path: str, 
                          prim_path: str,
                          position: Gf.Vec3f = Gf.Vec3f(0, 0, 0),
                          rotation: Gf.Vec3f = Gf.Vec3f(0, 0, 0),
                          scale: float = 1.0) -> bool:
        """
        Add an asset instance to the scene with instancing support.
        
        Args:
            usd_path: Path to the USD asset file.
            prim_path: Desired prim path in the stage.
            position: XYZ position.
            rotation: Euler angles in degrees (XYZ).
            scale: Uniform scale factor.
            
        Returns:
            True if successful, False otherwise.
        """
        try:
            # Use instancing if this asset has been loaded before
            if usd_path in self._asset_instances:
                # Create instance reference
                stage_utils.add_reference_to_stage(
                    usd_path=usd_path,
                    prim_path=prim_path,
                    instanceable=True
                )
            else:
                # First instance - load normally
                stage_utils.add_reference_to_stage(
                    usd_path=usd_path,
                    prim_path=prim_path
                )
                self._asset_instances[usd_path] = [prim_path]
            
            # Set transform
            prim = self.stage.GetPrimAtPath(prim_path)
            if prim:
                xform = UsdGeom.Xformable(prim)
                translate_op = xform.AddTranslateOp()
                rotate_op = xform.AddRotateXYZOp()
                scale_op = xform.AddScaleOp()
                
                translate_op.Set(position)
                rotate_op.Set(Gf.Vec3f(
                    np.radians(rotation[0]),
                    np.radians(rotation[1]),
                    np.radians(rotation[2])
                ))
                scale_op.Set(Gf.Vec3f(scale, scale, scale))
                
                print(f"[SceneBuilder] Asset instance added: {prim_path}")
                return True
                
        except Exception as e:
            print(f"[SceneBuilder] Failed to add asset {usd_path} at {prim_path}: {e}")
            return False
        
        return False
    
    def create_industrial_floor(self, 
                               size: float = 100.0,
                               height: float = 0.1,
                               material_path: Optional[str] = None) -> str:
        """
        Create a basic industrial floor plane.
        
        Args:
            size: Length and width of the floor.
            height: Thickness of the floor.
            material_path: Optional path to material USD.
            
        Returns:
            Path to the created floor prim.
        """
        floor_path = "/World/IndustrialFloor"
        
        # Create cube for floor (thick plane)
        create_prim(
            prim_path=floor_path,
            prim_type="Cube",
            attributes={
                "size": (size, size, height),
                "purpose": "default"
            }
        )
        
        # Position at origin
        prim = self.stage.GetPrimAtPath(floor_path)
        xform = UsdGeom.Xformable(prim)
        translate_op = xform.AddTranslateOp()
        translate_op.Set(Gf.Vec3f(0, 0, -height/2))
        
        # Apply material if provided
        if material_path:
            try:
                stage_utils.add_reference_to_stage(
                    usd_path=material_path,
                    prim_path=f"{floor_path}/Material"
                )
            except Exception as e:
                print(f"[SceneBuilder] Could not apply material {material_path}: {e}")
        
        # Make it a collision object
        UsdPhysics.CollisionAPI.Apply(prim)
        
        print(f"[SceneBuilder] Industrial floor created: {size}x{size}m")
        return floor_path
    
    def build(self) -> bool:
        """
        Execute the full scene build process.
        
        Returns:
            True if successful, False otherwise.
        """
        try:
            print("[SceneBuilder] Starting scene construction...")
            
            # Core setup
            self.create_stage()
            self.setup_physics()
            self.setup_lighting()
            
            # Add industrial floor
            self.create_industrial_floor(
                size=self.config.get("floor_size", 100.0),
                height=self.config.get("floor_height", 0.2),
                material_path=self.config.get("floor_material")
            )
            
            print("[SceneBuilder] Scene construction completed successfully.")
            return True
            
        except Exception as e:
            print(f"[SceneBuilder] Scene construction failed: {e}")
            return False


if __name__ == "__main__":
    # Example usage and testing
    config = {
        "floor_size": 120.0,
        "floor_height": 0.15,
        "floor_material": None
    }
    
    builder = SceneBuilder(config)
    success = builder.build()
    
    if success:
        print("SceneBuilder test PASSED")
    else:
        print("SceneBuilder test FAILED")
