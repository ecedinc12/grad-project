import math
import random

WAREHOUSE_INTERIOR_X = (-7.0, 7.0)
WAREHOUSE_INTERIOR_Y = (-7.0, 7.0)
INTERIOR_MARGIN = 0.5
CEILING_Z = 6.0
FLOOR_Z = 0.3

ANGLE_HEIGHT_MAP = {
    "overhead":   (5.0, 6.0),
    "high_angle": (3.0, 4.5),
    "eye_level":  (1.4, 2.0),
    "low_angle":  (0.3, 1.0),
}
DEFAULT_HEIGHT_RANGE = (1.4, 4.5)


def clamp_to_warehouse(x, y, z):
    x_lo = WAREHOUSE_INTERIOR_X[0] + INTERIOR_MARGIN
    x_hi = WAREHOUSE_INTERIOR_X[1] - INTERIOR_MARGIN
    y_lo = WAREHOUSE_INTERIOR_Y[0] + INTERIOR_MARGIN
    y_hi = WAREHOUSE_INTERIOR_Y[1] - INTERIOR_MARGIN
    x = max(x_lo, min(x_hi, x))
    y = max(y_lo, min(y_hi, y))
    z = max(FLOOR_Z, min(CEILING_Z, z))
    return (x, y, z)


def pick_indoor_position(angle_hints, hazard_zones=None,
                         entity_positions=None, worker_positions=None):
    points = []

    if worker_positions:
        for wx, wy in worker_positions:
            points.append((wx, wy))
    elif entity_positions:
        for ex, ey in entity_positions:
            points.append((ex, ey))

    if hazard_zones:
        for zone in hazard_zones:
            bmin = zone.get("bounds_min", (-2, -2))
            bmax = zone.get("bounds_max", (2, 2))
            cx = (bmin[0] + bmax[0]) / 2.0
            cy = (bmin[1] + bmax[1]) / 2.0
            points.append((cx, cy))

    if points:
        cx = sum(p[0] for p in points) / len(points)
        cy = sum(p[1] for p in points) / len(points)
    else:
        cx, cy = 0.0, 0.0

    cx, cy, _ = clamp_to_warehouse(cx, cy, 0.0)

    if angle_hints:
        first_known = next((h for h in angle_hints if h in ANGLE_HEIGHT_MAP), None)
        if first_known:
            z_lo, z_hi = ANGLE_HEIGHT_MAP[first_known]
        else:
            z_lo, z_hi = DEFAULT_HEIGHT_RANGE
    else:
        z_lo, z_hi = DEFAULT_HEIGHT_RANGE

    z = (z_lo + z_hi) / 2.0

    return (cx, cy, z)


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


ANGLE_ELEVATION_MAP = {
    "overhead":   (55, 70),
    "high_angle": (35, 55),
    "eye_level":  (10, 30),
    "low_angle":  (5,  15),
}


def _compute_scene_radius(hazard_zones=None, entity_positions=None):
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
    import omni.replicator.core as rep

    xs = [p[0] for p in scene_positions]
    ys = [p[1] for p in scene_positions]
    zs = [p[2] for p in scene_positions]

    return rep.distribution.uniform(
        (min(xs), min(ys), min(zs)),
        (max(xs), max(ys), max(zs))
    )