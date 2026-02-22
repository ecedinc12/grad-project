"""
Scenario Runner Module for Industrial Safety Synthetic Data Pipeline.

This module orchestrates the simulation logic, including worker navigation,
PPE compliance toggling, and hazard event scripting.
"""

import random
from enum import Enum
from typing import Optional, List, Dict, Any
import numpy as np

from pxr import Usd, UsdGeom, Gf, UsdPhysics
import omni.isaac.core.utils.prims as prim_utils
import omni.isaac.core.utils.xforms as xform_utils
from omni.isaac.core.utils.rotations import euler_angles_to_quat


class WorkerState(Enum):
    IDLE = 0
    WALK = 1
    HAZARD_INTERACTION = 2


class WorkerController:
    """
    Manages the state and logic for a single worker character.
    """
    def __init__(self, prim_path: str, stage: Usd.Stage):
        self.prim_path = prim_path
        self.stage = stage
        self.prim = prim_utils.get_prim_at_path(prim_path)
        
        if not self.prim:
            print(f"[WorkerController] Error: Prim not found at {prim_path}")
            return

        self.xform = UsdGeom.Xformable(self.prim)
        
        # PPE Slots (Assumes standard hierarchy)
        # Adjust these paths based on actual asset hierarchy
        self.helmet_path = f"{prim_path}/Skeleton/Head/Helmet"
        self.vest_path = f"{prim_path}/Skeleton/Spine2/Vest"
        
        # State
        self.state = WorkerState.IDLE
        self.has_helmet = True
        self.has_vest = True
        self.target_position: Optional[Gf.Vec3f] = None
        self.speed = 1.2  # m/s
        
    def toggle_ppe(self, helmet: Optional[bool] = None, vest: Optional[bool] = None) -> Dict[str, bool]:
        """
        Sets visibility of PPE items. 
        True = Visible (Compliant), False = Invisible (Non-compliant).
        None = Randomize.
        """
        if helmet is None:
            # 70% chance of compliance
            self.has_helmet = random.random() < 0.7
        else:
            self.has_helmet = helmet

        if vest is None:
            # 80% chance of compliance
            self.has_vest = random.random() < 0.8
        else:
            self.has_vest = vest
            
        # Apply visibility
        self._set_visibility(self.helmet_path, self.has_helmet)
        self._set_visibility(self.vest_path, self.has_vest)
        
        return {"helmet": self.has_helmet, "vest": self.has_vest}

    def _set_visibility(self, path: str, visible: bool):
        prim = self.stage.GetPrimAtPath(path)
        if prim:
            imageable = UsdGeom.Imageable(prim)
            if visible:
                imageable.MakeVisible()
            else:
                imageable.MakeInvisible()
        # Silent failure if prim doesn't exist (might not have loaded yet)

    def set_target(self, target: Gf.Vec3f):
        """Set a navigation target for the worker."""
        self.target_position = target
        self.state = WorkerState.WALK

    def update(self, dt: float):
        """
        Advance worker logic by one time step.
        Simple linear movement for now; replace with Omni.Anim.Graph later.
        """
        if self.state == WorkerState.WALK and self.target_position:
            current_pos = self._get_position()
            direction = self.target_position - current_pos
            distance = direction.GetLength()
            
            if distance < 0.1:
                self.state = WorkerState.IDLE
                self.target_position = None
                return

            # Normalize and move
            move_vec = direction / distance * self.speed * dt
            new_pos = current_pos + move_vec
            
            # Update Transform
            self._set_position(new_pos)
            
            # Face direction of movement
            # (Simplified rotation logic)
            angle = np.arctan2(direction[1], direction[0])
            self._set_rotation_z(np.degrees(angle))

    def _get_position(self) -> Gf.Vec3f:
        # Get world position
        # Compute the world transform at the current time
        world_transform = UsdGeom.Xformable(self.prim).ComputeLocalToWorldTransform(self.stage.GetTime())
        return world_transform.ExtractTranslation()

    def _set_position(self, pos: Gf.Vec3f):
        # Get current orientation to preserve it
        world_transform = UsdGeom.Xformable(self.prim).ComputeLocalToWorldTransform(self.stage.GetTime())
        rotation = world_transform.ExtractRotationQuat()
        # Set world pose with new position and current orientation
        xform_utils.set_world_pose(self.prim, position=pos, orientation=rotation)

    def _set_rotation_z(self, angle_deg: float):
        # Get current position to preserve it
        current_pos = self._get_position()
        # Create a quaternion rotation around Z axis
        # Convert angle to radians for quaternion
        angle_rad = np.radians(angle_deg)
        # Create a quaternion (w, x, y, z) for rotation around Z axis
        # Using euler_angles_to_quat which expects (roll, pitch, yaw) in radians
        # For rotation around Z axis, we use (0, 0, angle_rad)
        quat = euler_angles_to_quat([0.0, 0.0, angle_rad])
        # Set world pose with new orientation
        xform_utils.set_world_pose(self.prim, position=current_pos, orientation=quat)


class ScenarioRunner:
    """
    Orchestrates the entire scenario including multiple workers and hazards.
    """
    def __init__(self, stage: Usd.Stage):
        self.stage = stage
        self.workers: List[WorkerController] = []
        self.hazards: List[Dict] = []
        
    def register_worker(self, prim_path: str):
        worker = WorkerController(prim_path, self.stage)
        self.workers.append(worker)
        print(f"[ScenarioRunner] Registered worker: {prim_path}")
        
    def setup_geofence(self, zone_bounds: tuple, hazard_type: str):
        """
        Define a hazardous zone.
        zone_bounds: ((min_x, min_y), (max_x, max_y))
        """
        self.hazards.append({
            "type": "geofence",
            "bounds": zone_bounds,
            "info": hazard_type
        })

    def check_hazards(self) -> List[Dict]:
        """
        Check for any active hazard triggers.
        Returns a list of event dictionaries.
        """
        events = []
        
        for worker in self.workers:
            # Check PPE
            if not worker.has_helmet:
                events.append({
                    "type": "ppe_violation",
                    "subtype": "no_helmet",
                    "worker": worker.prim_path
                })
            if not worker.has_vest:
                events.append({
                    "type": "ppe_violation",
                    "subtype": "no_vest",
                    "worker": worker.prim_path
                })
                
            # Check Geofences
            pos = worker._get_position()
            for hazard in self.hazards:
                if hazard["type"] == "geofence":
                    (min_x, min_y), (max_x, max_y) = hazard["bounds"]
                    if min_x <= pos[0] <= max_x and min_y <= pos[1] <= max_y:
                        events.append({
                            "type": "geofence_breach",
                            "zone": hazard["info"],
                            "worker": worker.prim_path
                        })
                        
        return events

    def update(self, dt: float):
        for worker in self.workers:
            worker.update(dt)

    def randomize_scenario(self, floor_height: float = 0.0):
        """Reset and randomize all worker states.
        
        Args:
            floor_height: The height of the floor to place workers above it.
        """
        for worker in self.workers:
            worker.toggle_ppe()  # Randomize PPE
            
            # Randomize position (Placeholder logic)
            # In production, use valid navmesh points
            x = random.uniform(-5, 5)
            y = random.uniform(-5, 5)
            # Place worker slightly above the floor to avoid collision issues
            z = floor_height + 1.0  # 1 meter above floor
            worker._set_position(Gf.Vec3f(x, y, z))
            
            # Randomize rotation to face a random direction
            angle_deg = random.uniform(0, 360)
            worker._set_rotation_z(angle_deg)
