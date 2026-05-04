"""
Camera Positioning Logic

Camera-first approach: placement determined from config (angle hints,
hazard zones, override) BEFORE entities are spawned. Then
compute_ground_visible_area() projects the camera frustum onto the
ground plane to derive a (min_x, max_x, min_y, max_y) spawn region.

Submodules:
  - bounds   — interior limits and clamping
  - placement — mount selection, orbit positions, look_at, scene placement
  - framing  — frustum-to-ground projection, fit-to-entities
"""

from isaac_backend.camera.bounds import (
    WAREHOUSE_INTERIOR_X,
    WAREHOUSE_INTERIOR_Y,
    INTERIOR_MARGIN,
    CEILING_Z,
    FLOOR_Z,
    MIN_INDOOR_HEIGHT,
    clamp_to_warehouse,
    clamp_bounds_to_warehouse,
    compute_scene_bbox,
    compute_scene_radius,
)
from isaac_backend.camera.placement import (
    ANGLE_HEIGHT_MAP,
    ANGLE_ELEVATION_MAP,
    ANGLE_FOCAL_LENGTH_MAP,
    DEFAULT_HEIGHT_RANGE,
    DEFAULT_FOCAL_LENGTH,
    MOUNT_WALL_INSET,
    MOUNT_XY_JITTER,
    CORNER_MOUNTS,
    WALL_MID_MOUNTS,
    pick_indoor_position,
    positions_for_angles,
    orbit_distribution,
    pick_look_at_target,
    pick_camera_placement,
)
from isaac_backend.camera.framing import (
    SENSOR_WIDTH_MM,
    SENSOR_HEIGHT_MM,
    VISIBLE_MARGIN_FRACTION,
    MIN_VISIBLE_SIZE,
    compute_ground_visible_area,
    fit_camera_to_entities,
)

__all__ = [
    "WAREHOUSE_INTERIOR_X", "WAREHOUSE_INTERIOR_Y", "INTERIOR_MARGIN",
    "CEILING_Z", "FLOOR_Z", "MIN_INDOOR_HEIGHT",
    "clamp_to_warehouse", "clamp_bounds_to_warehouse",
    "compute_scene_bbox", "compute_scene_radius",
    "ANGLE_HEIGHT_MAP", "ANGLE_ELEVATION_MAP", "ANGLE_FOCAL_LENGTH_MAP",
    "DEFAULT_HEIGHT_RANGE", "DEFAULT_FOCAL_LENGTH",
    "MOUNT_WALL_INSET", "MOUNT_XY_JITTER", "CORNER_MOUNTS", "WALL_MID_MOUNTS",
    "pick_indoor_position", "positions_for_angles", "orbit_distribution",
    "pick_look_at_target", "pick_camera_placement",
    "SENSOR_WIDTH_MM", "SENSOR_HEIGHT_MM", "VISIBLE_MARGIN_FRACTION", "MIN_VISIBLE_SIZE",
    "compute_ground_visible_area", "fit_camera_to_entities",
]
