"""
Camera Positioning Logic

Provides indoor fixed-position placement and orbit distribution for
camera viewpoints in warehouse SDG. Pure Python — no Isaac Sim imports
except rep.distribution in orbit_distribution().

The indoor camera is placed at an OFFSET from the scene centroid,
looking toward the centroid. This ensures the camera frames the entire
scene rather than hovering directly above it.

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

ANGLE_HEIGHT_MAP = {
    "overhead":   (5.0, 6.0),
    "high_angle": (4.0, 6.0),
    "eye_level":  (1.4, 2.0),
    "low_angle":  (0.3, 1.0),
}
DEFAULT_HEIGHT_RANGE = (1.4, 6.0)

ANGLE_ELEVATION_MAP = {
    "overhead":   (55, 70),
    "high_angle": (35, 55),
    "eye_level":  (10, 30),
    "low_angle":  (5,  15),
}


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
    """Compute an offset indoor camera position that frames the entire scene.

    Places the camera at a corner/side offset from the scene centroid,
    looking toward the centroid. This ensures the camera sees all entities
    rather than hovering directly above them.

    For 'high_angle': camera is placed at a diagonal corner offset.
    For 'overhead': camera is placed directly above centroid (traditional).
    For 'eye_level'/'low_angle': camera is offset to one side at low height.
    """
    bbox = _compute_scene_bbox(entity_positions, worker_positions, hazard_zones)
    if bbox is None:
        return clamp_to_warehouse(0.0, 0.0, 3.0)

    cx, cy = bbox["centroid"]
    x_span = max(bbox["x_span"], 2.0)
    y_span = max(bbox["y_span"], 2.0)

    if angle_hints:
        first_known = next((h for h in angle_hints if h in ANGLE_HEIGHT_MAP), None)
    else:
        first_known = None

    if first_known == "overhead":
        z_lo, z_hi = ANGLE_HEIGHT_MAP["overhead"]
        z = (z_lo + z_hi) / 2.0
        cam_x, cam_y, cam_z = cx, cy, z
    elif first_known == "high_angle":
        z_lo, z_hi = ANGLE_HEIGHT_MAP["high_angle"]
        z = (z_lo + z_hi) / 2.0
        offset_x = max(x_span * 0.6, 3.0)
        offset_y = max(y_span * 0.4, 2.0)
        best_x, best_y = cx, cy
        best_dist = -1
        for sx in (1, -1):
            for sy in (1, -1):
                try_x = cx + sx * offset_x
                try_y = cy + sy * offset_y
                clamped = clamp_to_warehouse(try_x, try_y, z)
                dist = math.sqrt((try_x - clamped[0])**2 + (try_y - clamped[1])**2)
                if dist < abs(sx) * offset_x * 0.1:
                    corner_dist = math.sqrt((clamped[0] - cx)**2 + (clamped[1] - cy)**2)
                    if corner_dist > best_dist:
                        best_dist = corner_dist
                        best_x, best_y = clamped[0], clamped[1]
        if best_dist <= 0:
            best_x = clamp_to_warehouse(cx + offset_x, cy + offset_y, z)[0]
            best_y = clamp_to_warehouse(cx + offset_x, cy + offset_y, z)[1]
        cam_x, cam_y, cam_z = best_x, best_y, z
    elif first_known in ("eye_level", "low_angle"):
        z_lo, z_hi = ANGLE_HEIGHT_MAP.get(first_known, DEFAULT_HEIGHT_RANGE)
        z = (z_lo + z_hi) / 2.0
        offset_x = max(x_span * 0.8, 4.0)
        try_x = cx + offset_x
        clamped = clamp_to_warehouse(try_x, cy, z)
        cam_x, cam_y, cam_z = clamped
    else:
        z_lo, z_hi = DEFAULT_HEIGHT_RANGE
        z = (z_lo + z_hi) / 2.0
        offset_x = max(x_span * 0.7, 3.5)
        offset_y = max(y_span * 0.5, 2.0)
        best_x, best_y = cx + offset_x, cy - offset_y
        clamped = clamp_to_warehouse(best_x, best_y, z)
        cam_x, cam_y, cam_z = clamped

    return (cam_x, cam_y, cam_z)


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
                          mode="indoor"):
    """Return camera positions for the given angle hints.

    mode="indoor" — single fixed position inside the warehouse.
    mode="orbit" — multiple positions on a spherical shell around the scene.
    """
    if mode == "indoor":
        pos = pick_indoor_position(
            angle_hints, hazard_zones=hazard_zones,
            entity_positions=entity_positions,
            worker_positions=worker_positions,
        )
        return [pos]

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
    """Return a rep.distribution.uniform over the bounding box of scene_positions."""
    xs = [p[0] for p in scene_positions]
    ys = [p[1] for p in scene_positions]
    zs = [p[2] for p in scene_positions]

    return rep.distribution.uniform(
        (min(xs), min(ys), min(zs)),
        (max(xs), max(ys), max(zs))
    )


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
        return (0.0, 0.0, 1.0)

    cx = sum(p[0] for p in points) / len(points)
    cy = sum(p[1] for p in points) / len(points)
    return (cx, cy, 1.0)