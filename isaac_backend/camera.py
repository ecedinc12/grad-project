"""
Camera Positioning Logic

Provides indoor fixed-position placement and orbit distribution for
camera viewpoints in warehouse SDG. Pure Python — no Isaac Sim imports
except rep.distribution in orbit_distribution().

Camera-first approach: the camera placement is determined from config
(angle hints, hazard zones, or explicit override) BEFORE entities are
spawned. Then compute_ground_visible_area() projects the camera frustum
onto the ground plane to derive a (min_x, max_x, min_y, max_y) spawn
region so that entities are always placed within the camera's field of view.

Constants define warehouse interior bounds, angle-to-height mappings,
and angle-to-elevation mappings.
"""

import math
import random
import omni.replicator.core as rep

WAREHOUSE_INTERIOR_X = (-7.0, 7.0)
WAREHOUSE_INTERIOR_Y = (-7.0, 7.0)
INTERIOR_MARGIN = 0.5
CEILING_Z = 6.0
FLOOR_Z = 0.3
MIN_INDOOR_HEIGHT = 3.0

ANGLE_HEIGHT_MAP = {
    "overhead":   (5.0, 6.0),
    "high_angle": (4.0, 6.0),
    "eye_level":  (2.5, 4.0),
    "low_angle":  (2.0, 3.5),
}
DEFAULT_HEIGHT_RANGE = (2.5, 6.0)

ANGLE_ELEVATION_MAP = {
    "overhead":   (55, 70),
    "high_angle": (35, 55),
    "eye_level":  (10, 30),
    "low_angle":  (5,  15),
}

# Surveillance mount geometry
MOUNT_WALL_INSET = 0.4   # metres camera body is inset from the effective wall face
_WX = WAREHOUSE_INTERIOR_X[1] - INTERIOR_MARGIN   # 6.5
_WY = WAREHOUSE_INTERIOR_Y[1] - INTERIOR_MARGIN   # 6.5

# 4 warehouse corners — classic CCTV mount positions
CORNER_MOUNTS = [
    ( _WX - MOUNT_WALL_INSET,  _WY - MOUNT_WALL_INSET),
    (-_WX + MOUNT_WALL_INSET,  _WY - MOUNT_WALL_INSET),
    ( _WX - MOUNT_WALL_INSET, -_WY + MOUNT_WALL_INSET),
    (-_WX + MOUNT_WALL_INSET, -_WY + MOUNT_WALL_INSET),
]

# 4 wall midpoints — sweeping side/aisle view cameras
WALL_MID_MOUNTS = [
    ( _WX - MOUNT_WALL_INSET,  0.0),
    (-_WX + MOUNT_WALL_INSET,  0.0),
    (0.0,  _WY - MOUNT_WALL_INSET),
    (0.0, -_WY + MOUNT_WALL_INSET),
]

MOUNT_XY_JITTER = 0.3   # metres, uniform ±, for dataset diversity

# Per-angle default focal lengths — only used when config omits focal_length
ANGLE_FOCAL_LENGTH_MAP = {
    "overhead":    24.0,   # ceiling mount, wide area
    "high_angle":   8.0,   # wide-angle CCTV covering diagonal corner view
    "eye_level":   16.0,   # moderate — mid-wall/rack post
    "low_angle":   14.0,   # moderate-wide from low rack/wall post
}
DEFAULT_FOCAL_LENGTH = 14.0



def clamp_to_warehouse(x, y, z):
    """Constrain a position to warehouse interior bounds with margin."""
    x_lo = WAREHOUSE_INTERIOR_X[0] + INTERIOR_MARGIN
    x_hi = WAREHOUSE_INTERIOR_X[1] - INTERIOR_MARGIN
    y_lo = WAREHOUSE_INTERIOR_Y[0] + INTERIOR_MARGIN
    y_hi = WAREHOUSE_INTERIOR_Y[1] - INTERIOR_MARGIN
    x = max(x_lo, min(x_hi, x))
    y = max(y_lo, min(y_hi, y))
    z = max(FLOOR_Z, min(CEILING_Z, z))
    return (x, y, z)


def _compute_scene_bbox(entity_positions, worker_positions, hazard_zones):
    """Compute the bounding box and centroid of all scene elements."""
    points = []

    if worker_positions:
        points.extend(worker_positions)
    elif entity_positions:
        points.extend(entity_positions)

    if hazard_zones:
        for zone in hazard_zones:
            bmin = zone.get("bounds_min", (-2, -2))
            bmax = zone.get("bounds_max", (2, 2))
            cx = (bmin[0] + bmax[0]) / 2.0
            cy = (bmin[1] + bmax[1]) / 2.0
            points.append((cx, cy))

    if not points:
        return None

    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    cx = sum(xs) / len(xs)
    cy = sum(ys) / len(ys)
    x_span = max(xs) - min(xs)
    y_span = max(ys) - min(ys)

    return {
        "centroid": (cx, cy),
        "min_x": min(xs), "max_x": max(xs),
        "min_y": min(ys), "max_y": max(ys),
        "x_span": x_span, "y_span": y_span,
    }


def pick_indoor_position(angle_hints, hazard_zones=None,
                          entity_positions=None, worker_positions=None):
    """Place camera at a realistic wall/ceiling surveillance mount.

    overhead   — ceiling above scene centroid, small random offset for natural tilt
    high_angle — corner mount near ceiling; choose randomly from top-2 corners
                 by distance from scene centroid (farther = wider view)
    eye_level  — wall-midpoint mount at mid height; top-2 by distance
    low_angle  — wall-midpoint mount at low height; top-2 by distance
    """
    bbox = _compute_scene_bbox(entity_positions, worker_positions, hazard_zones)
    cx, cy = bbox["centroid"] if bbox is not None else (0.0, 0.0)

    first_known = next((h for h in (angle_hints or []) if h in ANGLE_HEIGHT_MAP), None)
    z_lo, z_hi = ANGLE_HEIGHT_MAP.get(first_known, DEFAULT_HEIGHT_RANGE)

    if first_known == "overhead":
        jx = random.uniform(-MOUNT_XY_JITTER, MOUNT_XY_JITTER)
        jy = random.uniform(-MOUNT_XY_JITTER, MOUNT_XY_JITTER)
        cam_pos = clamp_to_warehouse(cx + jx, cy + jy, random.uniform(z_lo, z_hi))
    else:
        pool = CORNER_MOUNTS if first_known == "high_angle" else WALL_MID_MOUNTS
        ranked = sorted(pool,
                        key=lambda m: (m[0]-cx)**2 + (m[1]-cy)**2,
                        reverse=True)
        chosen = random.choice(ranked[:2])
        jx = random.uniform(-MOUNT_XY_JITTER, MOUNT_XY_JITTER)
        jy = random.uniform(-MOUNT_XY_JITTER, MOUNT_XY_JITTER)
        cam_pos = clamp_to_warehouse(chosen[0]+jx, chosen[1]+jy, random.uniform(z_lo, z_hi))

    cam_pos = (cam_pos[0], cam_pos[1], max(cam_pos[2], MIN_INDOOR_HEIGHT))
    print(f"[CAMERA] pick_indoor_position: angle={first_known}, "
          f"centroid=({cx:.2f},{cy:.2f}), "
          f"camera=({cam_pos[0]:.2f},{cam_pos[1]:.2f},{cam_pos[2]:.2f})")
    return cam_pos


def _build_orbit_positions(n=30, radius_min=4, radius_max=9,
                            azimuth_deg=(0, 360), elevation_deg=(10, 70)):
    """Generate n camera positions on a spherical shell around the origin."""
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


def _compute_scene_radius(hazard_zones=None, entity_positions=None):
    """Compute orbit radius bounds from scene entity extents."""
    points = []

    if hazard_zones:
        for zone in hazard_zones:
            bmin = zone.get("bounds_min", (-2, -2))
            bmax = zone.get("bounds_max", (2, 2))
            for px in (bmin[0], bmax[0]):
                for py in (bmin[1], bmax[1]):
                    points.append((px, py))

    if entity_positions:
        for ex, ey in entity_positions:
            points.append((ex, ey))

    if not points:
        return (4, 9)

    max_dist = max(math.sqrt(px**2 + py**2) for px, py in points)
    radius_min = max(4, math.ceil(max_dist * 1.2))
    radius_max = radius_min + 4
    return (radius_min, radius_max)


def positions_for_angles(angle_hints, hazard_zones=None,
                          entity_positions=None, worker_positions=None,
                          mode="indoor", num_positions=1):
    """Return camera positions for the given angle hints.

    mode="indoor" — fixed positions inside the warehouse.
    mode="orbit" — positions on a spherical shell around the scene.
    """
    if mode == "indoor":
        positions = []
        for _ in range(num_positions):
            pos = pick_indoor_position(
                angle_hints, hazard_zones=hazard_zones,
                entity_positions=entity_positions,
                worker_positions=worker_positions,
            )
            positions.append(pos)
        return positions

    radius_min, radius_max = _compute_scene_radius(hazard_zones, entity_positions)

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
    """Return a rep.distribution.sequence over the calculated spherical shell positions."""
    return rep.distribution.sequence(scene_positions)


def pick_look_at_target(entity_positions, worker_positions, hazard_zones):
    """Compute the look_at target as the centroid of all scene elements.

    Uses worker positions primarily (since they move), falls back to
    entity positions, then hazard zone centers.
    """
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


SENSOR_WIDTH_MM = 36.0
SENSOR_HEIGHT_MM = 20.25
VISIBLE_MARGIN_FRACTION = 0.25
MIN_VISIBLE_SIZE = 2.0


def compute_ground_visible_area(cam_pos, look_at, focal_length=14.0,
                                 margin_fraction=VISIBLE_MARGIN_FRACTION):
    """Compute the conservative AABB on the ground plane (z=0) visible from the camera.

    Projects the four corner rays of the camera frustum onto z=0 and
    returns a shrunk axis-aligned bounding box suitable for constraining
    entity spawn positions.

    Rays that don't hit the ground (ray_dz >= 0) are skipped — they
    point skyward and don't limit the ground visible area. If too few
    rays hit, falls back to a region around the camera's ground projection.

    Args:
        cam_pos: Camera position (x, y, z).
        look_at: Look-at target (x, y, z).
        focal_length: Focal length in mm (default 14.0 → wide FOV).
        margin_fraction: Fraction of each edge to inset (0.15 = use inner 85%).

    Returns:
        Tuple (min_x, max_x, min_y, max_y) of the conservative spawn region.
    """
    cam_x, cam_y, cam_z = cam_pos
    la_x, la_y, la_z = look_at

    dx = la_x - cam_x
    dy = la_y - cam_y
    dz = la_z - cam_z
    d_len = math.sqrt(dx * dx + dy * dy + dz * dz)
    if d_len < 1e-6:
        dz = -1.0
        d_len = 1.0
    dx /= d_len
    dy /= d_len
    dz /= d_len

    right_len = math.sqrt(dy * dy + dx * dx)
    if right_len < 1e-4:
        rx, ry, rz = 1.0, 0.0, 0.0
    else:
        rx = -dy / right_len
        ry = dx / right_len
        rz = 0.0

    ux = dy * rz - dz * ry
    uy = dz * rx - dx * rz
    uz = dx * ry - dy * rx
    u_len = math.sqrt(ux * ux + uy * uy + uz * uz)
    if u_len < 1e-6:
        ux, uy, uz = 0.0, 1.0, 0.0
    else:
        ux /= u_len
        uy /= u_len
        uz /= u_len

    half_hfov = math.atan(SENSOR_WIDTH_MM / (2.0 * focal_length))
    half_vfov = math.atan(SENSOR_HEIGHT_MM / (2.0 * focal_length))

    ground_points = []

    for sh, sv in [(-1, -1), (1, -1), (-1, 1), (1, 1)]:
        ray_dx = dx + math.tan(half_hfov) * sh * rx + math.tan(half_vfov) * sv * ux
        ray_dy = dy + math.tan(half_hfov) * sh * ry + math.tan(half_vfov) * sv * uy
        ray_dz = dz + math.tan(half_hfov) * sh * rz + math.tan(half_vfov) * sv * uz

        if ray_dz < -1e-6:
            t = -cam_z / ray_dz
            if t > 0:
                gx = cam_x + ray_dx * t
                gy = cam_y + ray_dy * t
                gx = max(WAREHOUSE_INTERIOR_X[0], min(WAREHOUSE_INTERIOR_X[1], gx))
                gy = max(WAREHOUSE_INTERIOR_Y[0], min(WAREHOUSE_INTERIOR_Y[1], gy))
                ground_points.append((gx, gy))

    if len(ground_points) < 2:
        fallback_radius = 3.0
        cx = cam_x + dx * max(cam_z, 1.0)
        cy = cam_y + dy * max(cam_z, 1.0)
        ground_points = [
            (cx - fallback_radius, cy - fallback_radius),
            (cx + fallback_radius, cy - fallback_radius),
            (cx - fallback_radius, cy + fallback_radius),
            (cx + fallback_radius, cy + fallback_radius),
        ]
        print("[CAMERA] Too few ground intersections, using fallback region around camera projection")

    min_x = min(p[0] for p in ground_points)
    max_x = max(p[0] for p in ground_points)
    min_y = min(p[1] for p in ground_points)
    max_y = max(p[1] for p in ground_points)

    span_x = max(max_x - min_x, MIN_VISIBLE_SIZE)
    span_y = max(max_y - min_y, MIN_VISIBLE_SIZE)
    min_x += span_x * margin_fraction / 2.0
    max_x -= span_x * margin_fraction / 2.0
    min_y += span_y * margin_fraction / 2.0
    max_y -= span_y * margin_fraction / 2.0

    if max_x - min_x < MIN_VISIBLE_SIZE:
        cx = (min_x + max_x) / 2.0
        min_x = cx - MIN_VISIBLE_SIZE / 2.0
        max_x = cx + MIN_VISIBLE_SIZE / 2.0
    if max_y - min_y < MIN_VISIBLE_SIZE:
        cy = (min_y + max_y) / 2.0
        min_y = cy - MIN_VISIBLE_SIZE / 2.0
        max_y = cy + MIN_VISIBLE_SIZE / 2.0

    wh_min_x = WAREHOUSE_INTERIOR_X[0] + INTERIOR_MARGIN
    wh_max_x = WAREHOUSE_INTERIOR_X[1] - INTERIOR_MARGIN
    wh_min_y = WAREHOUSE_INTERIOR_Y[0] + INTERIOR_MARGIN
    wh_max_y = WAREHOUSE_INTERIOR_Y[1] - INTERIOR_MARGIN
    min_x = max(min_x, wh_min_x)
    max_x = min(max_x, wh_max_x)
    min_y = max(min_y, wh_min_y)
    max_y = min(max_y, wh_max_y)

    print(f"[CAMERA] Ground visible area: x=[{min_x:.2f}, {max_x:.2f}] y=[{min_y:.2f}, {max_y:.2f}]")
    return (min_x, max_x, min_y, max_y)


def clamp_bounds_to_warehouse(visible_bounds):
    """Clamp a (min_x, max_x, min_y, max_y) tuple to warehouse interior bounds."""
    min_x, max_x, min_y, max_y = visible_bounds
    wh_min_x = WAREHOUSE_INTERIOR_X[0] + INTERIOR_MARGIN
    wh_max_x = WAREHOUSE_INTERIOR_X[1] - INTERIOR_MARGIN
    wh_min_y = WAREHOUSE_INTERIOR_Y[0] + INTERIOR_MARGIN
    wh_max_y = WAREHOUSE_INTERIOR_Y[1] - INTERIOR_MARGIN
    return (
        max(min_x, wh_min_x),
        min(max_x, wh_max_x),
        max(min_y, wh_min_y),
        min(max_y, wh_max_y),
    )


def fit_camera_to_entities(cam_pos, look_at, entity_positions, focal_length=14.0, margin=0.85):
    """Pull camera backward along view axis until all entity positions fit in the frame.

    For each entity, computes the minimum backward shift needed so the entity's
    angular offset from the view axis is within margin * half_fov. Takes the
    max shift across all entities and both FOV axes.

    Args:
        cam_pos: Camera position (x, y, z).
        look_at: Look-at target (x, y, z).
        entity_positions: List of (x, y) ground-plane entity positions.
        focal_length: Camera focal length in mm.
        margin: Fraction of each FOV half to use (0.85 keeps entities in inner 85%).

    Returns:
        Adjusted cam_pos (x, y, z) — unchanged if all entities already fit.
    """
    if not entity_positions:
        return cam_pos

    cam_x, cam_y, cam_z = cam_pos
    la_x, la_y, la_z = look_at

    dx = la_x - cam_x
    dy = la_y - cam_y
    dz = la_z - cam_z
    d_len = math.sqrt(dx*dx + dy*dy + dz*dz)
    if d_len < 1e-6:
        return cam_pos
    fx, fy, fz = dx/d_len, dy/d_len, dz/d_len

    right_len = math.sqrt(fy*fy + fx*fx)
    if right_len < 1e-4:
        rx, ry, rz = 1.0, 0.0, 0.0
    else:
        rx = -fy / right_len
        ry =  fx / right_len
        rz =  0.0

    ux = fy*rz - fz*ry
    uy = fz*rx - fx*rz
    uz = fx*ry - fy*rx
    u_len = math.sqrt(ux*ux + uy*uy + uz*uz)
    if u_len < 1e-6:
        ux, uy, uz = 0.0, 1.0, 0.0
    else:
        ux /= u_len; uy /= u_len; uz /= u_len

    tan_hfov = math.tan(math.atan(SENSOR_WIDTH_MM  / (2.0 * focal_length))) * margin
    tan_vfov = math.tan(math.atan(SENSOR_HEIGHT_MM / (2.0 * focal_length))) * margin

    max_delta = 0.0
    min_depth = 0.5  # entity must be at least this far in front after shift

    for ex, ey in entity_positions:
        ex_rel = ex - cam_x
        ey_rel = ey - cam_y
        ez_rel = 0.0 - cam_z

        depth      = ex_rel*fx + ey_rel*fy + ez_rel*fz
        right_proj = ex_rel*rx + ey_rel*ry + ez_rel*rz
        up_proj    = ex_rel*ux + ey_rel*uy + ez_rel*uz

        entity_delta = max(0.0, min_depth - depth)
        if tan_hfov > 0:
            entity_delta = max(entity_delta, abs(right_proj) / tan_hfov - depth)
        if tan_vfov > 0:
            entity_delta = max(entity_delta, abs(up_proj)    / tan_vfov - depth)

        max_delta = max(max_delta, entity_delta)

    if max_delta < 0.05:
        return cam_pos

    new_cam_pos = clamp_to_warehouse(
        cam_x - fx * max_delta,
        cam_y - fy * max_delta,
        cam_z - fz * max_delta,
    )
    new_cam_pos = (new_cam_pos[0], new_cam_pos[1], max(new_cam_pos[2], MIN_INDOOR_HEIGHT))
    print(f"[CAMERA] fit_camera_to_entities: shifted {max_delta:.2f}m back → "
          f"({new_cam_pos[0]:.2f}, {new_cam_pos[1]:.2f}, {new_cam_pos[2]:.2f})")
    return new_cam_pos


def pick_camera_placement(scene_config, hazard_zones=None):
    """Determine camera position and look_at from config alone — no entity dependency.

    This is the camera-first entry point. Call BEFORE spawning entities
    so that visible_bounds can be computed and used to constrain spawn positions.

    Returns:
        (cam_pos, look_at, focal_length) where cam_pos and look_at are (x, y, z) tuples.
    """
    angle_hints = scene_config.get("camera_angles", [])
    camera_position_override = scene_config.get("camera_position")
    if scene_config.get("focal_length"):
        focal_length = scene_config["focal_length"]
    else:
        first_known = next((h for h in angle_hints if h in ANGLE_FOCAL_LENGTH_MAP), None)
        focal_length = ANGLE_FOCAL_LENGTH_MAP.get(first_known, DEFAULT_FOCAL_LENGTH)

    if camera_position_override:
        cam_pos = clamp_to_warehouse(*camera_position_override)
        cam_pos = (cam_pos[0], cam_pos[1], max(cam_pos[2], MIN_INDOOR_HEIGHT))
        print(f"[CAMERA] Using camera_position override: ({cam_pos[0]:.2f}, {cam_pos[1]:.2f}, {cam_pos[2]:.2f})")
    else:
        cam_pos = pick_indoor_position(
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
          f"focal_length={focal_length}mm")
    return cam_pos, look_at, focal_length