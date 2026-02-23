"""
Headless Runner for Industrial Safety Synthetic Data Pipeline.

Main entry point that orchestrates scene building, scenario simulation,
domain randomization, and data writing in a headless Isaac Sim environment.
"""

import sys
import os
import gc
import time
from typing import Dict, Any, Optional
import yaml

# CRITICAL: SimulationApp must be instantiated before any other Omniverse imports
# We handle this in the main() execution block to allow class definitions to load safely

class HeadlessRunner:
    """
    Main orchestrator for headless data generation.
    """
    
    def __init__(self, config_path: str, sim_app):
        """
        Initialize the runner with configuration.
        
        Args:
            config_path: Path to generation configuration YAML.
            sim_app: The SimulationApp instance.
        """
        self.sim_app = sim_app
        self.config_path = config_path
        self.config = self._load_config()
        
        # Core components
        self.world = None
        self.scene_builder = None
        self.scenario_runner = None
        self.domain_randomizer = None
        self.data_writer = None
        
        # State
        self.frame_count = 0
        self.total_frames = self.config.get("total_frames", 1000)
        self.dt = 1.0 / 30.0  # 30 FPS
        
        print(f"[HeadlessRunner] Initialized for {self.total_frames} frames")
    
    def _load_config(self) -> Dict[str, Any]:
        """Load and parse configuration file."""
        try:
            with open(self.config_path, 'r') as f:
                config = yaml.safe_load(f)
            
            # Set defaults for missing values
            config.setdefault("total_frames", 1000)
            config.setdefault("output", {}).setdefault("base_dir", "output/dataset_v1")
            
            return config
            
        except Exception as e:
            print(f"[HeadlessRunner] Error loading config: {e}")
            raise
    
    def initialize(self) -> bool:
        """
        Initialize all components and the simulation world.
        
        Returns:
            True if successful, False otherwise.
        """
        try:
            print("[HeadlessRunner] Initializing components...")
            
            # Lazy imports to ensure context is ready
            from omni.isaac.core import World
            from omni.isaac.core.utils.stage import create_new_stage
            
            # Create a new stage
            create_new_stage()
            
            # Initialize World (Physics & Time)
            self.world = World(stage_units_in_meters=1.0)
            self.world.scene.add_default_ground_plane()
            
            # Import project modules
            # Ensure script directory is in path
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from scene_builder import SceneBuilder
            from scenario_runner import ScenarioRunner
            from domain_randomizer import DomainRandomizer
            from data_writer import SafetyDatasetWriter
            import omni.replicator.core as rep
            
            # Initialize SceneBuilder
            self.scene_builder = SceneBuilder(self.config)
            if not self.scene_builder.build():
                print("[HeadlessRunner] SceneBuilder failed")
                return False
            
            # Initialize ScenarioRunner
            self.scenario_runner = ScenarioRunner(self.world.stage)
            
            # Register workers (Placeholder: In production, load from config/assets)
            self._setup_test_workers()
            
            # Initialize DomainRandomizer
            self.domain_randomizer = DomainRandomizer(self.world.stage)
            
            # Initialize DataWriter
            class_mapping = {
                "worker": 0,
                "forklift": 1,
                "helmet": 2,
                "no_helmet": 3
            }
            
            output_dir = self.config["output"]["base_dir"]
            self.data_writer = SafetyDatasetWriter(
                output_dir=output_dir,
                class_mapping=class_mapping,
                annotation_format="kitti"
            )
            
            # Setup Replicator Camera and Attachment
            self._setup_replicator(rep)
            
            print("[HeadlessRunner] All components initialized successfully")
            return True
            
        except Exception as e:
            print(f"[HeadlessRunner] Initialization failed: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _setup_replicator(self, rep):
        """Configure Replicator render products and attach writer."""
        # Create a camera prim
        from omni.isaac.core.utils.prims import create_prim
        from pxr import Gf, UsdGeom
        
        camera_path = "/World/Camera"
        create_prim(camera_path, "Camera", attributes={
            "focusDistance": 400, 
            "focalLength": 24
        })
        
        # Position camera looking down-ish
        camera_prim = self.world.stage.GetPrimAtPath(camera_path)
        xform = UsdGeom.Xformable(camera_prim)
        # Position: x=0, y=-10, z=5; Look at Origin
        # Simple transform for now
        transform = Gf.Matrix4d().SetTranslate(Gf.Vec3d(0, -10, 5)) * \
                   Gf.Matrix4d().SetRotate(Gf.Rotation(Gf.Vec3d(1, 0, 0), 60))
        # Note: In a real run, ScenarioRunner or CameraRig should manage this
        
        # Create Render Product
        render_product = rep.create.render_product(camera_path, (1920, 1080))
        
        # Attach the writer to the render product
        # SafetyDatasetWriter is a custom writer instance
        self.data_writer.attach([render_product])
        print(f"[HeadlessRunner] Writer attached to render product: {render_product}")
    
    def _setup_test_workers(self) -> None:
        """Setup test workers for demonstration."""
        from omni.isaac.core.utils.prims import create_prim
        
        for i in range(2): 
            worker_path = f"/World/Worker_{i}"
            # Create simple shapes representing workers
            create_prim(worker_path, "Cone", attributes={"height": 1.8, "radius": 0.3})
            
            # Sub-prims for PPE logic
            create_prim(f"{worker_path}/Helmet", "Sphere", attributes={"radius": 0.2})
            create_prim(f"{worker_path}/Vest", "Cube", attributes={"size": (0.4, 0.5, 0.1)})
            
            self.scenario_runner.register_worker(worker_path)
        
        # Setup hazard
        self.scenario_runner.setup_geofence(
            zone_bounds=((-2, -2), (2, 2)),
            hazard_type="RestrictedArea"
        )
        print("[HeadlessRunner] Created test workers and geofence")
    
    def run(self) -> None:
        """
        Execute the main generation loop.
        """
        if not self.initialize():
            return
        
        import omni.replicator.core as rep
        
        print(f"[HeadlessRunner] Starting generation of {self.total_frames} frames...")
        start_time = time.time()
        
        try:
            for frame_idx in range(self.total_frames):
                
                # 1. Simulation Logic Update (Moves characters, checks logic)
                #    We pass dt, but we don't step physics yet.
                self.scenario_runner.update(self.dt)
                
                # 2. Hazard Check (Logic State)
                hazards = self.scenario_runner.check_hazards()
                # In a real pipeline, we'd inject this hazard info into the writer's metadata
                # For now, we just log it
                if hazards and frame_idx % 50 == 0:
                     print(f"[HeadlessRunner] Frame {frame_idx}: {len(hazards)} hazards")

                # 3. Domain Randomization (Visuals)
                self.domain_randomizer.randomize_frame()
                
                # 4. Step & Render & Write
                #    rep.orchestrator.step() advances the timeline and triggers the attached writer.
                #    This effectively does world.step(render=True) + Data Acquisition.
                rep.orchestrator.step()
                
                self.frame_count += 1
                
                # 5. Periodic Cleanup / Reset
                if frame_idx > 0 and frame_idx % 100 == 0:
                    gc.collect()
                    print(f"[HeadlessRunner] Processed {frame_idx}/{self.total_frames} frames")
                    # Reset scenario periodically to prevent workers wandering too far
                    self.scenario_runner.randomize_scenario(floor_height=0.0)
                
                # Check if app was closed externally
                if not self.sim_app.is_running():
                    break
                
        except KeyboardInterrupt:
            print("[HeadlessRunner] Interrupted by user")
        except Exception as e:
            print(f"[HeadlessRunner] Error during execution: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self._print_stats(start_time)
            self.shutdown()
    
    def _print_stats(self, start_time):
        elapsed_time = time.time() - start_time
        fps = self.frame_count / elapsed_time if elapsed_time > 0 else 0
        print(f"[HeadlessRunner] Generation completed")
        print(f"  Frames processed: {self.frame_count}")
        print(f"  Elapsed time: {elapsed_time:.2f} seconds")
        print(f"  Average FPS: {fps:.2f}")
    
    def shutdown(self) -> None:
        """Clean shutdown of all components."""
        print("[HeadlessRunner] Shutting down...")
        
        # Shutdown writer
        if self.data_writer:
            self.data_writer.on_shutdown()
        
        # Clear distractors
        if self.domain_randomizer:
            self.domain_randomizer.clear_distractors()
        
        # Close simulation app
        if self.sim_app:
            self.sim_app.close()
        
        print("[HeadlessRunner] Shutdown complete")


def main():
    """Main entry point."""
    print("=" * 60)
    print("Industrial Safety Synthetic Data Pipeline - Headless Runner")
    print("=" * 60)
    
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/generation_config.yaml", help="Path to config")
    parser.add_argument("--frames", type=int, default=None, help="Override frame count")
    args = parser.parse_args()

    # 1. Start SimulationApp
    from omni.isaac.kit import SimulationApp
    config = {"headless": True, "width": 1920, "height": 1080}
    simulation_app = SimulationApp(config)
    
    # 2. Run Application
    runner = HeadlessRunner(config_path=args.config, sim_app=simulation_app)
    if args.frames:
        runner.total_frames = args.frames
        
    runner.run()


if __name__ == "__main__":
    main()
