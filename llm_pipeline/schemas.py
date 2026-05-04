"""Pydantic schemas for scene configuration: PPEState, Entity, HazardZone, WorkerBehavior, SceneConfig."""
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

class ClutterZone(BaseModel):
    area: str = Field(..., description="Zone name identifier, e.g. 'center_aisle', 'dock_bay'")
    bounds_min: tuple[float, float] = Field(..., description="Minimum (x, y) bounds of the zone in meters")
    bounds_max: tuple[float, float] = Field(..., description="Maximum (x, y) bounds of the zone in meters")
    density: Literal["low", "medium", "high"] = Field(default="medium", description="Clutter density within this zone")
    types: List[str] = Field(default_factory=lambda: ["box", "box_small", "box_large", "barrel", "drum", "cone", "pallet", "crate"], description="Clutter prop types for this zone")

class LayoutParams(BaseModel):
    rack_pattern: Literal["rows", "grid", "L-shape", "perimeter", "clusters", "none"] = Field(
        default="rows", description="Rack placement pattern algorithm"
    )
    rack_rows: Literal["auto", 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12] = Field(
        default="auto", description="Number of rack rows (1-12) or 'auto' to procedurally fill bounds"
    )
    rack_cols: Literal["auto", 1, 2, 3, 4, 5, 6, 7, 8, 9, 10] = Field(
        default="auto", description="Number of rack columns (1-10) or 'auto' to procedurally fill bounds"
    )
    target_rack_height: float = Field(default=4.5, description="Target height for the racks in meters. Racks and shelves will scale procedurally.")
    aisle_width: float = Field(default=2.5, description="Distance between rack rows in meters (1.0-5.0)")
    bounds_min: tuple[float, float] = Field(default=(-6.0, -6.0), description="Minimum (x, y) layout footprint in meters. Must stay within ±6m.")
    bounds_max: tuple[float, float] = Field(default=(6.0, 6.0), description="Maximum (x, y) layout footprint in meters. Must stay within ±6m.")
    clutter_density: Literal["low", "medium", "high"] = Field(
        default="high", description="Global clutter density: low=8 props, medium=18 props, high=30 props"
    )
    clutter_zones: List[ClutterZone] = Field(
        default_factory=list, description="Optional zone-specific clutter overrides. If empty, clutter is scattered globally."
    )
    pallet_rows: int = Field(default=3, description="Number of pallet staging rows")
    pallet_cols: int = Field(default=2, description="Number of pallet staging columns")
    rack_fill: Literal["empty", "sparse", "medium", "full"] = Field(
        default="medium",
        description="How full rack shelves are: empty=0%, sparse=30%, medium=60%, full=90% of shelf positions filled"
    )
    dock_area: bool = Field(
        default=False, description="Whether to spawn a loading dock cluster of loaded pallets near the warehouse entrance"
    )
    max_rows: int = Field(default=0, description="Max rack rows when auto-fitting (0=unlimited). Caps density so standard layouts don't oversaturate.")
    max_cols: int = Field(default=0, description="Max rack columns when auto-fitting (0=unlimited). Caps density so standard layouts don't oversaturate.")
    cross_aisle_every: int = Field(default=0, description="Insert a cross-aisle (perpendicular fire/forklift gap) every N columns. 0=disabled.")
    cross_aisle_width: float = Field(default=3.5, description="Width in metres of each cross-aisle gap (typical: 3.5-4.0m)")
    aisle_widths: Optional[List[float]] = Field(default=None, description="Per-gap aisle widths cycling [narrow, wide, narrow, ...]. Overrides uniform aisle_width for 'rows' pattern. E.g. [2.5, 4.0, 2.5] for two picking aisles flanking a main drive aisle.")
    dock_zone_frac: float = Field(default=0.25, description="Fraction of warehouse Y-axis reserved for dock/staging zone at the front")
    storage_zone_frac: float = Field(default=0.55, description="Fraction of warehouse Y-axis used for rack storage zone in the middle")

class VehicleBehavior(BaseModel):
    vehicle_id: str                  # matches prim name: "forklift_01", "cart_01", ...
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
    camera_mode: Literal["indoor", "orbit"] = Field(
        default="indoor",
        description="Camera placement: 'indoor' = single fixed surveillance position inside warehouse, 'orbit' = multiple dynamic viewpoints/angles on a spherical shell around the scene"
    )
    camera_position: Optional[tuple[float, float, float]] = Field(
        default=None,
        description="Explicit camera (x, y, z) in meters. If None, auto-derived from scene. x,y clamped to warehouse interior."
    )
    focal_length: Optional[float] = Field(
        default=None,
        description="Camera focal length in mm. Lower values = wider FOV. Default 14.0 for indoor warehouse (captures ~90deg FOV). Use 10-12 to guarantee wide shots that include all described assets, 18-24 for narrower."
    )
    lighting_conditions: Literal["daylight", "overcast", "dusk", "night"] = Field(
        default="daylight",
        description="Lighting condition. Must be one of: daylight, overcast, dusk, night"
    )
    worker_behaviors: List[WorkerBehavior] = Field(
        default_factory=list,
        description="Behavior command sequences for each worker, one entry per worker entity"
    )
    vehicle_behaviors: List[VehicleBehavior] = Field(
        default_factory=list,
        description="Behavior command sequences for each vehicle (like forklift), one entry per vehicle entity"
    )
    layout: str = Field(
        default="standard_warehouse",
        description="Layout preset name (standard_warehouse, narrow_aisle, open_floor, cross_dock, cold_storage, loading_dock, maintenance_bay, storage_yard) or 'custom'"
    )
    layout_params: Optional[LayoutParams] = Field(
        default=None,
        description="Parameter overrides for custom or preset-based layouts. None means use preset defaults."
    )
