import math

def _build_orbit_positions(n=30, radius_min=3, radius_max=6,
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

def positions_for_angles(angle_hints):
    """Return orbit positions filtered to the requested elevation bands.
    Falls back to the full default hemisphere if hints are empty/unknown."""
    known = [h for h in angle_hints if h in ANGLE_ELEVATION_MAP]
    if not known:
        return ORBIT_POSITIONS
    el_min = min(ANGLE_ELEVATION_MAP[h][0] for h in known)
    el_max = max(ANGLE_ELEVATION_MAP[h][1] for h in known)
    return _build_orbit_positions(elevation_deg=(el_min, el_max))
