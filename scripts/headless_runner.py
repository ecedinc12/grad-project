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

# CRITICAL: SimulationApp must be imported before any other Omniverse imports
from omni.isaac.kit import SimulationApp

# Configure headless mode
config = {"headless": True, "width": 1920, "height": 1080}
simulation_app = SimulationApp(config)

# Now import other Omniverse modules
from omni.isaac.core import World
from omni.isaac.core.utils.stage import create_new_stage
import omni.replicator.core as rep

# Import project modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scene_builder import SceneBuilder
from scenario_runner import ScenarioRunner
from domain_randomizer import DomainRandomizer
from data_writer import SafetyDatasetWriter


class HeadlessRunner:
    """
    Main orchestrator for headless data generation.
    """
    
    def __init__(self, config_path: str = "config/generation_config.yaml"):
        """
        Initialize the runner with configuration.
        
        Args:
            config_path: Path to generation configuration YAML.
        """
        self.config_path = config_path
        self.config = self._load_config()
        
        # Core components
        self.world: Optional[World] = None
        self.scene_builder: Optional[SceneBuilder] = None
        self.scenario_runner: Optional[ScenarioRunner] = None
        self.domain_randomizer: Optional[DomainRandomizer] = None
        self.data_writer: Optional[SafetyDatasetWriter] = None
        
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
            
            # Create a new stage
            create_new_stage()
            
            # Initialize World
            self.world = World(stage_units_in_meters=1.0)
            self.world.scene.add_default_ground_plane()
            
            # Initialize SceneBuilder
            self.scene_builder = SceneBuilder(self.config)
            if not self.scene_builder.build():
                print("[HeadlessRunner] SceneBuilder failed")
                return False
            
            # Initialize ScenarioRunner
            self.scenario_runner = ScenarioRunner(self.world.stage)
            
            # Register workers (placeholder - in production, load from config)
            # For now, create a test worker
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
            
            # Attach writer to Replicator
            rep.WriterRegistry.register(self.data_writer)
            
            print("[HeadlessRunner] All components initialized successfully")
            return True
            
        except Exception as e:
            print(f"[HeadlessRunner] Initialization failed: {e}")
            return False
    
    def _setup_test_workers(self) -> None:
        """Setup test workers for demonstration."""
        # In production, this would load actual worker assets from config
        # For now, we'll create placeholder prims
        from omni.isaac.core.utils.prims import create_prim
        
        for i in range(3):  # Create 3 test workers
            worker_path = f"/World/Worker_{i}"
            create_prim(
                prim_path=worker_path,
                prim_type="Cone",
                attributes={"height": 1.8, "radius": 0.3}
            )
            
            # Create PPE prims (simplified)
            helmet_path = f"{worker_path}/Helmet"
            vest_path = f"{worker_path}/Vest"
            
            create_prim(prim_path=helmet_path, prim_type="Sphere", attributes={"radius": 0.2})
            create_prim(prim_path=vest_path, prim_type="Cube", attributes={"size": (0.4, 0.5, 0.1)})
            
            # Register with scenario runner
            self.scenario_runner.register_worker(worker_path)
        
        # Setup a geofence hazard
        self.scenario_runner.setup_geofence(
            zone_bounds=((-2, -2), (2, 2)),
            hazard_type="RestrictedArea"
        )
        
        print("[HeadlessRunner] Created 3 test workers and geofence")
    
    def run(self) -> None:
        """
        Execute the main generation loop.
        """
        if not self.initialize():
            print("[HeadlessRunner] Failed to initialize, exiting")
            return
        
        print(f"[HeadlessRunner] Starting generation of {self.total_frames} frames...")
        start_time = time.time()
        
        try:
            for frame_idx in range(self.total_frames):
                # 1. Physics Step
                self.scenario_runner.update(self.dt)
                self.world.step(render=False)
                
                # 2. Logic Step (Hazard triggers)
                hazards = self.scenario_runner.check_hazards()
                if hazards and frame_idx % 100 == 0:
                    print(f"[HeadlessRunner] Frame {frame_idx}: {len(hazards)} hazards detected")
                
                # 3. Randomization Step
                self.domain_randomizer.randomize_frame()
                
                # 4. Render & Write
                # Trigger Replicator to capture and write data
                rep.orchestrator.step()
                
                # 5. Periodic cleanup
                if frame_idx % 100 == 0:
                    gc.collect()  # Python garbage collector
                    print(f"[HeadlessRunner] Processed {frame_idx}/{self.total_frames} frames")
                    
                    # Randomize scenario every 100 frames
                    self.scenario_runner.randomize_scenario(floor_height=0.0)
                
                # 6. Check for shutdown
                if not simulation_app.is_running():
                    print("[HeadlessRunner] SimulationApp stopped, exiting early")
                    break
                
        except KeyboardInterrupt:
            print("[HeadlessRunner] Interrupted by user")
        except Exception as e:
            print(f"[HeadlessRunner] Error during execution: {e}")
            import traceback
            traceback.print_exc()
        finally:
            # Calculate statistics
            elapsed_time = time.time() - start_time
            fps = self.frame_count / elapsed_time if elapsed_time > 0 else 0
            
            print(f"[HeadlessRunner] Generation completed")
            print(f"  Frames processed: {self.frame_count}")
            print(f"  Elapsed time: {elapsed_time:.2f} seconds")
            print(f"  Average FPS: {fps:.2f}")
            
            # Shutdown
            self.shutdown()
    
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
        simulation_app.close()
        
        print("[HeadlessRunner] Shutdown complete")


def main():
    """Main entry point."""
    print("=" * 60)
    print("Industrial Safety Synthetic Data Pipeline - Headless Runner")
    print("=" * 60)
    
    # Parse command line arguments
    import argparse
    parser = argparse.ArgumentParser(description="Headless data generation runner")
    parser.add_argument("--config", default="config/generation_config.yaml",
                       help="Path to configuration file")
    parser.add_argument("--frames", type=int, default=None,
                       help="Override total number of frames to generate")
    
    args = parser.parse_args()
    
    # Initialize and run
    runner = HeadlessRunner(config_path=args.config)
    
    if args.frames is not None:
        runner.total_frames = args.frames
    
    runner.run()


if __name__ == "__main__":
    main()
