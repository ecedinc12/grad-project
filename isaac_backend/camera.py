import math

def _build_orbit_positions(n=30, radius_min=12, radius_max=20,
                            azimuth_deg=(0, 360), elevation_deg=(20, 70)):
    """Pre-compute n camera positions on a hemisphere — all at safe distance from origin."""
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

ORBIT_POSITIONS = _build_orbit_positions()

ANGLE_ELEVATION_MAP = {
    "overhead":   (65, 85),
    "high_angle": (45, 65),
    "eye_level":  (15, 35),
    "low_angle":  (5,  20),
}

def _compute_scene_radius(hazard_zones=None, entity_positions=None):
    """Compute a safe camera radius that can see all entities and zones.

    Returns (radius_min, radius_max) tuple. Uses the furthest entity/zone corner
    from the origin plus a 50% margin as the minimum radius.
    """
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
        return (12, 20)

    max_dist = max(math.sqrt(px**2 + py**2) for px, py in points)
    radius_min = max(12, math.ceil(max_dist * 1.5))
    radius_max = radius_min + 8
    return (radius_min, radius_max)

def positions_for_angles(angle_hints, hazard_zones=None, entity_positions=None):
    """Return orbit positions filtered to the requested elevation bands,
    sorted by Z descending so index 0 is always the highest position.
    Falls back to the full default hemisphere if hints are empty/unknown.

    Dynamically adjusts radius based on scene bounds when provided.
    """
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
