"""Warehouse interior bounds and clamping helpers."""

import math

WAREHOUSE_INTERIOR_X = (-12.0, 12.0)
WAREHOUSE_INTERIOR_Y = (-12.0, 12.0)
INTERIOR_MARGIN = 0.5
CEILING_Z = 12.0
FLOOR_Z = 0.3
MIN_INDOOR_HEIGHT = 3.0


def clamp_to_warehouse(x, y, z):
    x_lo = WAREHOUSE_INTERIOR_X[0] + INTERIOR_MARGIN
    x_hi = WAREHOUSE_INTERIOR_X[1] - INTERIOR_MARGIN
    y_lo = WAREHOUSE_INTERIOR_Y[0] + INTERIOR_MARGIN
    y_hi = WAREHOUSE_INTERIOR_Y[1] - INTERIOR_MARGIN
    x = max(x_lo, min(x_hi, x))
    y = max(y_lo, min(y_hi, y))
    z = max(FLOOR_Z, min(CEILING_Z, z))
    return (x, y, z)


def clamp_bounds_to_warehouse(visible_bounds):
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


def compute_scene_bbox(entity_positions, worker_positions, hazard_zones):
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
            cx = (bmin[0] + bmax[0]) / 2.0
            cy = (bmin[1] + bmax[1]) / 2.0
            points.append((cx, cy))
    if not points:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return {
        "centroid": (sum(xs) / len(xs), sum(ys) / len(ys)),
        "min_x": min(xs), "max_x": max(xs),
        "min_y": min(ys), "max_y": max(ys),
        "x_span": max(xs) - min(xs), "y_span": max(ys) - min(ys),
    }


def compute_scene_radius(hazard_zones=None, entity_positions=None):
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
    return (radius_min, radius_min + 4)
