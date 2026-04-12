from pydantic import BaseModel, Field
from typing import List, Optional, Literal

class PPEState(BaseModel):
    hardhat: bool = Field(default=False, description="Whether the worker is wearing a hardhat")
    vest: bool = Field(default=False, description="Whether the worker is wearing a high-visibility vest")

class Entity(BaseModel):
    type: Literal["worker", "vehicle", "zone"] = Field(..., description="The type of entity")
    asset_id: str = Field(..., description="The ID/name of the asset to spawn. For zones: use descriptive names like 'forklift_aisle', 'loading_dock', 'restricted_area'")
    ppe_state: Optional[PPEState] = Field(default=None, description="PPE state, applicable mainly for workers")
    anchor_zone: Optional[str] = Field(default=None, description="The zone or area this entity is anchored to")

class HazardZone(BaseModel):
    name: str = Field(..., description="Zone identifier matching entity.asset_id, e.g. 'forklift_aisle'")
    bounds_min: tuple[float, float] = Field(..., description="Minimum (x, y) bounds of the zone in meters")
    bounds_max: tuple[float, float] = Field(..., description="Maximum (x, y) bounds of the zone in meters")
    danger_level: Literal["warning", "restricted", "critical"] = Field(
        default="warning",
        description="Severity: warning (caution area), restricted (authorized only), critical (lethal hazard)"
    )

class BehaviorCommand(BaseModel):
    command: Literal["GoTo", "Idle", "LookAround"]
    x: Optional[float] = None        # GoTo only — clamped to ±6m warehouse bounds
    y: Optional[float] = None        # GoTo only
    z: Optional[float] = 0.0         # GoTo only — elevation (0.0 for ground plane)
    rotation: Optional[float] = None # GoTo only — facing direction (degrees)
    duration: Optional[float] = None # Idle / LookAround only (seconds)

class WorkerBehavior(BaseModel):
    worker_id: str                   # matches prim name: "worker_01", "worker_02", ...
    commands: List[BehaviorCommand]

class SceneConfig(BaseModel):
    entities: List[Entity] = Field(default_factory=list, description="List of entities in the scene")
    hazard_zones: List[HazardZone] = Field(
        default_factory=list,
        description="Hazard zone definitions with spatial bounds and danger levels"
    )
    camera_angles: List[Literal["overhead", "high_angle", "eye_level", "low_angle"]] = Field(
        default_factory=list,
        description="Camera elevation hints. Each value must be one of: overhead, high_angle, eye_level, low_angle"
    )
    lighting_conditions: Literal["daylight", "overcast", "dusk", "night"] = Field(
        default="daylight",
        description="Lighting condition. Must be one of: daylight, overcast, dusk, night"
    )
    worker_behaviors: List[WorkerBehavior] = Field(
        default_factory=list,
        description="Behavior command sequences for each worker, one entry per worker entity"
    )
