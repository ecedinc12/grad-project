"""Camera mount selection and orbit position generation."""

import math
import random

import omni.replicator.core as rep

from isaac_backend.camera.bounds import (
    WAREHOUSE_INTERIOR_X,
    WAREHOUSE_INTERIOR_Y,
    INTERIOR_MARGIN,
    MIN_INDOOR_HEIGHT,
    clamp_to_warehouse,
    compute_scene_bbox,
    compute_scene_radius,
)

ANGLE_HEIGHT_MAP = {
    "overhead":   (9.0, 11.5),
    "high_angle": (7.0, 11.0),
    "eye_level":  (2.5, 6.0),
    "low_angle":  (2.0, 4.0),
}
DEFAULT_HEIGHT_RANGE = (2.5, 11.0)

ANGLE_ELEVATION_MAP = {
    "overhead":   (55, 70),
    "high_angle": (35, 55),
    "eye_level":  (10, 30),
    "low_angle":  (5,  15),
}

ANGLE_FOCAL_LENGTH_MAP = {
    "overhead":    24.0,
    "high_angle":   8.0,
    "eye_level":   16.0,
    "low_angle":   14.0,
}
DEFAULT_FOCAL_LENGTH = 14.0

MOUNT_WALL_INSET = 0.4
_WX = WAREHOUSE_INTERIOR_X[1] - INTERIOR_MARGIN
_WY = WAREHOUSE_INTERIOR_Y[1] - INTERIOR_MARGIN

CORNER_MOUNTS = [
    ( _WX - MOUNT_WALL_INSET,  _WY - MOUNT_WALL_INSET),
    (-_WX + MOUNT_WALL_INSET,  _WY - MOUNT_WALL_INSET),
    ( _WX - MOUNT_WALL_INSET, -_WY + MOUNT_WALL_INSET),
    (-_WX + MOUNT_WALL_INSET, -_WY + MOUNT_WALL_INSET),
]

WALL_MID_MOUNTS = [
    ( _WX - MOUNT_WALL_INSET,  0.0),
    (-_WX + MOUNT_WALL_INSET,  0.0),
    (0.0,  _WY - MOUNT_WALL_INSET),
    (0.0, -_WY + MOUNT_WALL_INSET),
]

MOUNT_XY_JITTER = 0.3


def pick_indoor_position(angle_hints, hazard_zones=None,
                         entity_positions=None, worker_positions=None,
                         preferred_mount=None):
    bbox = compute_scene_bbox(entity_positions, worker_positions, hazard_zones)
    cx, cy = bbox["centroid"] if bbox is not None else (0.0, 0.0)

    first_known = next((h for h in (angle_hints or []) if h in ANGLE_HEIGHT_MAP), None)
    z_lo, z_hi = ANGLE_HEIGHT_MAP.get(first_known, DEFAULT_HEIGHT_RANGE)

    chosen_mount_idx = None
    if first_known == "overhead":
        jx = random.uniform(-MOUNT_XY_JITTER, MOUNT_XY_JITTER)
        jy = random.uniform(-MOUNT_XY_JITTER, MOUNT_XY_JITTER)
        cam_pos = clamp_to_warehouse(cx + jx, cy + jy, random.uniform(z_lo, z_hi))
    else:
        pool = CORNER_MOUNTS if first_known in ("high_angle", "cctv") else WALL_MID_MOUNTS
        if preferred_mount is not None and preferred_mount < len(pool):
            chosen = pool[preferred_mount]
            chosen_mount_idx = preferred_mount
        else:
            ranked = sorted(list(enumerate(pool)),
                            key=lambda item: (item[1][0]-cx)**2 + (item[1][1]-cy)**2,
                            reverse=True)
            idx, chosen = random.choice(ranked[:2])
            chosen_mount_idx = idx

        jx = random.uniform(-MOUNT_XY_JITTER, MOUNT_XY_JITTER)
        jy = random.uniform(-MOUNT_XY_JITTER, MOUNT_XY_JITTER)
        cam_pos = clamp_to_warehouse(chosen[0]+jx, chosen[1]+jy, random.uniform(z_lo, z_hi))

    cam_pos = (cam_pos[0], cam_pos[1], max(cam_pos[2], MIN_INDOOR_HEIGHT))
    print(f"[CAMERA] pick_indoor_position: angle={first_known}, "
          f"centroid=({cx:.2f},{cy:.2f}), "
          f"camera=({cam_pos[0]:.2f},{cam_pos[1]:.2f},{cam_pos[2]:.2f})")
    return cam_pos, chosen_mount_idx


def _build_orbit_positions(n=30, radius_min=4, radius_max=9,
                           azimuth_deg=(0, 360), elevation_deg=(10, 70)):
    positions = []
    for i in range(n):
        az = math.radians(azimuth_deg[0] + (azimuth_deg[1] - azimuth_deg[0]) * i / n)
        el = math.radians(elevation_deg[0] + (elevation_deg[1] - elevation_deg[0]) * (i % 5) / 4)
        r  = radius_min + (radius_max - radius_min) * (i % 3) / 2
        x  = r * math.cos(el) * math.cos(az)
        y  = r * math.cos(el) * math.sin(az)
        z  = r * math.sin(el)
        positions.append((x, y, z))
    return positions


def positions_for_angles(angle_hints, hazard_zones=None,
                         entity_positions=None, worker_positions=None,
                         mode="indoor", num_positions=1):
    if mode == "indoor":
        positions = []
        for _ in range(num_positions):
            pos, _ = pick_indoor_position(
                angle_hints, hazard_zones=hazard_zones,
                entity_positions=entity_positions,
                worker_positions=worker_positions,
            )
            positions.append(pos)
        return positions

    radius_min, radius_max = compute_scene_radius(hazard_zones, entity_positions)

    known = [h for h in angle_hints if h in ANGLE_ELEVATION_MAP]
    if not known:
        return sorted(
            _build_orbit_positions(radius_min=radius_min, radius_max=radius_max),
            key=lambda p: p[2], reverse=True
        )
    el_min = min(ANGLE_ELEVATION_MAP[h][0] for h in known)
    el_max = max(ANGLE_ELEVATION_MAP[h][1] for h in known)
    return sorted(
        _build_orbit_positions(
            radius_min=radius_min,
            radius_max=radius_max,
            elevation_deg=(el_min, el_max)
        ),
        key=lambda p: p[2], reverse=True,
    )


def orbit_distribution(scene_positions):
    return rep.distribution.sequence(scene_positions)


def pick_look_at_target(entity_positions, worker_positions, hazard_zones):
    points = []
    if worker_positions:
        points.extend(worker_positions)
    if entity_positions:
        for p in entity_positions:
            if p not in points:
                points.append(p)
    if hazard_zones:
        for zone in hazard_zones:
            bmin = zone.get("bounds_min", (-2, -2))
            bmax = zone.get("bounds_max", (2, 2))
            points.append(((bmin[0] + bmax[0]) / 2.0, (bmin[1] + bmax[1]) / 2.0))

    if not points:
        print("[CAMERA] No points for look_at target — defaulting to (0, 0, 1.0)")
        return (0.0, 0.0, 1.0)

    cx = sum(p[0] for p in points) / len(points)
    cy = sum(p[1] for p in points) / len(points)
    print(f"[CAMERA] pick_look_at_target: {len(points)} points, target=({cx:.2f}, {cy:.2f}, 1.0)")
    return (cx, cy, 1.0)


def pick_camera_placement(scene_config, hazard_zones=None):
    angle_hints = scene_config.get("camera_angles", [])
    camera_position_override = scene_config.get("camera_position")
    if scene_config.get("focal_length"):
        focal_length = scene_config["focal_length"]
    else:
        first_known = next((h for h in angle_hints if h in ANGLE_FOCAL_LENGTH_MAP), None)
        focal_length = ANGLE_FOCAL_LENGTH_MAP.get(first_known, DEFAULT_FOCAL_LENGTH)

    chosen_mount = None
    if camera_position_override:
        cam_pos = clamp_to_warehouse(*camera_position_override)
        cam_pos = (cam_pos[0], cam_pos[1], max(cam_pos[2], MIN_INDOOR_HEIGHT))
        print(f"[CAMERA] Using camera_position override: ({cam_pos[0]:.2f}, {cam_pos[1]:.2f}, {cam_pos[2]:.2f})")
    else:
        cam_pos, chosen_mount = pick_indoor_position(
            angle_hints,
            hazard_zones=hazard_zones,
            entity_positions=None,
            worker_positions=None,
        )

    look_at = pick_look_at_target(
        entity_positions=[],
        worker_positions=[],
        hazard_zones=hazard_zones or [],
    )

    print(f"[CAMERA] Camera placement: pos=({cam_pos[0]:.2f}, {cam_pos[1]:.2f}, {cam_pos[2]:.2f}) "
          f"look_at=({look_at[0]:.2f}, {look_at[1]:.2f}, {look_at[2]:.2f}) "
          f"focal_length={focal_length}mm chosen_mount={chosen_mount}")
    return cam_pos, look_at, focal_length, chosen_mount
