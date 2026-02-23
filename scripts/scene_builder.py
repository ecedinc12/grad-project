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
                      gravity: Optional[Gf.Vec3f] = None,
                      broadphase_type: str = "MBP",
                      solver_type: str = "TGS",
                      enable_gpu_dynamics: bool = True) -> None:
        """
        Configure PhysicsScene for GPU dynamics.
        
        Args:
            gravity: Gravity vector (m/s²). If None, determined by stage Up-Axis.
            broadphase_type: Broadphase algorithm ("MBP", "PCM", "ABP").
            solver_type: Solver type ("TGS" or "PGS").
            enable_gpu_dynamics: Enable GPU acceleration for physics.
        """
        # Determine gravity based on stage up-axis if not provided
        if gravity is None:
            up_axis = UsdGeom.GetStageUpAxis(self.stage)
            if up_axis == UsdGeom.Tokens.z:
                gravity = Gf.Vec3f(0.0, 0.0, -9.81)
            else:
                gravity = Gf.Vec3f(0.0, -9.81, 0.0)

        # Create or get the physics scene prim
        if not self.stage.GetPrimAtPath(self._physics_scene_path):
            physics_scene = UsdPhysics.Scene.Define(self.stage, self._physics_scene_path)
            physics_scene.CreateGravityAttr().Set(gravity)
        else:
            physics_scene = UsdPhysics.Scene.Get(self.stage, self._physics_scene_path)
            # Update gravity if it was passed explicitly or calculated
            physics_scene.GetGravityAttr().Set(gravity)
        
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
    
    def add_asset_from_nucleus(self, 
                              path_suffix: str,
                              prim_path: str,
                              position: Gf.Vec3f = Gf.Vec3f(0, 0, 0),
                              rotation: Gf.Vec3f = Gf.Vec3f(0, 0, 0),
                              scale: float = 1.0,
                              max_retries: int = 3) -> bool:
        """
        Robust wrapper to load assets from Nucleus server with retry logic.
        
        Args:
            path_suffix: Relative path on Nucleus server (e.g., "/NVIDIA/Assets/...")
            prim_path: Desired prim path in the stage.
            position: XYZ position.
            rotation: Euler angles in degrees (XYZ).
            scale: Uniform scale factor.
            max_retries: Number of retry attempts on failure.
            
        Returns:
            True if successful, False otherwise.
        """
        import time
        import omni.client
        
        # Construct full Nucleus URL
        # Load config to get nucleus_server
        try:
            import yaml
            with open("config/generation_config.yaml", 'r') as f:
                config = yaml.safe_load(f)
            nucleus_server = config['assets']['nucleus_server'].rstrip('/')
        except Exception as e:
            print(f"[SceneBuilder] Failed to load config: {e}")
            return False
        
        full_url = f"{nucleus_server}{path_suffix}"
        
        # Validate file existence before attempting to reference
        print(f"[SceneBuilder] Checking asset existence: {full_url}")
        result = omni.client.stat(full_url)
        if result != omni.client.Result.OK:
            print(f"[SceneBuilder] Asset not found or inaccessible: {full_url}")
            return False
        
        # Retry loop for adding reference
        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    print(f"[SceneBuilder] Retry attempt {attempt + 1}/{max_retries} for {path_suffix}")
                    time.sleep(0.5 * attempt)  # Exponential backoff
                
                # Use instancing if this asset has been loaded before
                if full_url in self._asset_instances:
                    stage_utils.add_reference_to_stage(
                        usd_path=full_url,
                        prim_path=prim_path,
                        instanceable=True
                    )
                    self._asset_instances[full_url].append(prim_path)
                else:
                    stage_utils.add_reference_to_stage(
                        usd_path=full_url,
                        prim_path=prim_path
                    )
                    self._asset_instances[full_url] = [prim_path]
                
                # Set transform
                prim = self.stage.GetPrimAtPath(prim_path)
                if prim:
                    xform = UsdGeom.Xformable(prim)
                    # Clear existing ops to avoid conflicts
                    xform.ClearXformOpOrder()
                    
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
                    
                    print(f"[SceneBuilder] Asset instance added: {prim_path} from {path_suffix}")
                    return True
                    
            except Exception as e:
                print(f"[SceneBuilder] Attempt {attempt + 1} failed for {path_suffix}: {e}")
                if attempt == max_retries - 1:
                    print(f"[SceneBuilder] All {max_retries} attempts failed for {path_suffix}")
                    return False
                continue
        
        return False

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
        # For Nucleus paths, use the new robust method
        if usd_path.startswith("omniverse://") or usd_path.startswith("/NVIDIA/"):
            import omni.client
            # Extract path suffix
            if usd_path.startswith("omniverse://"):
                # Use robust URL parsing
                result, _, _, path = omni.client.break_url(usd_path)
                path_suffix = path
            else:
                path_suffix = usd_path
            
            return self.add_asset_from_nucleus(
                path_suffix=path_suffix,
                prim_path=prim_path,
                position=position,
                rotation=rotation,
                scale=scale
            )
        
        # Fallback for local paths
        try:
            # Use instancing if this asset has been loaded before
            if usd_path in self._asset_instances:
                # Create instance reference
                stage_utils.add_reference_to_stage(
                    usd_path=usd_path,
                    prim_path=prim_path,
                    instanceable=True
                )
                self._asset_instances[usd_path].append(prim_path)
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
                # Clear existing ops
                xform.ClearXformOpOrder()
                
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
    """
    Demonstration of the ScenarioRunner module.
    This test runs without requiring actual USD assets by using a mock stage.
    """
    print("=== ScenarioRunner Module Test ===")
    
    # Import ScenarioRunner from the correct module
    # Since this is in a different file, we need to import it
    # First, make sure we can import from the scripts directory
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    
    try:
        from scenario_runner import ScenarioRunner
    except ImportError as e:
        print(f"ERROR: Could not import ScenarioRunner: {e}")
        print("Make sure scenario_runner.py is in the same directory.")
        exit(1)
    
    # Create an in-memory stage for testing
    from pxr import Usd
    import omni.usd
    
    # Get or create a stage
    context = omni.usd.get_context()
    stage = context.new_stage()
    
    if stage is None:
        print("ERROR: Failed to create stage")
        exit(1)
    
    print(f"Stage created: {stage.GetRootLayer().identifier}")
    
    # Create a simple test prim to act as a worker
    worker_path = "/World/TestWorker"
    from pxr import UsdGeom
    sphere_prim = UsdGeom.Sphere.Define(stage, worker_path)
    
    # Create PPE child prims (dummy prims for testing)
    helmet_prim = UsdGeom.Sphere.Define(stage, f"{worker_path}/Skeleton/Head/Helmet")
    vest_prim = UsdGeom.Sphere.Define(stage, f"{worker_path}/Skeleton/Spine2/Vest")
    
    print(f"Created test worker at {worker_path}")
    
    # Initialize ScenarioRunner
    runner = ScenarioRunner(stage)
    runner.register_worker(worker_path)
    
    # Setup a geofence hazard zone
    runner.setup_geofence(((-2, -2), (2, 2)), "RestrictedArea")
    print("Geofence hazard zone configured")
    
    # Randomize the scenario
    runner.randomize_scenario(floor_height=0.0)
    print("Scenario randomized")
    
    # Check initial hazards
    hazards = runner.check_hazards()
    print(f"Initial hazard check: {len(hazards)} events")
    for event in hazards:
        print(f"  - {event['type']}: {event.get('subtype', event.get('zone', ''))}")
    
    # Simulate a few steps
    print("\nSimulating 5 steps...")
    for i in range(5):
        runner.update(dt=0.1)
        hazards = runner.check_hazards()
        if hazards:
            print(f"Step {i+1}: {len(hazards)} hazards detected")
        else:
            print(f"Step {i+1}: No hazards")
    
    print("\n=== Test completed successfully ===")
    print("Note: This is a basic functionality test. Full integration requires")
    print("actual USD assets and proper simulation environment.")
