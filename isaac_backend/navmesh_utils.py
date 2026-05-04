"""
Navmesh-aware target validation for worker GoTo commands.

NavigationManager (references/navigation_manager.py:138-156) calls
navmesh.query_shortest_path(start, target, agent_radius=0.5); if it returns
None, generate_path bails out and the worker stalls on that command. This
module pre-validates each GoTo target against the live navmesh and snaps
unreachable ones to the nearest reachable point, so commands never reach
the script in an unrouteable state.
"""

import math


AGENT_RADIUS = 0.6
DEFAULT_MAX_RADIUS = 4.0
DEFAULT_NUM_RINGS = 8
DEFAULT_SAMPLES_PER_RING = 12


def _carb_float3(x, y, z=0.0):
    import carb
    return carb.Float3(float(x), float(y), float(z))


def get_navmesh():
    """Return the live navmesh, or None if unavailable (e.g. bake failed)."""
    try:
        import omni.anim.navigation.core as nav
        return nav.acquire_interface().get_navmesh()
    except Exception:
        return None


def _is_reachable(navmesh, start_xy, target_xy, agent_radius=AGENT_RADIUS):
    try:
        path = navmesh.query_shortest_path(
            _carb_float3(*start_xy),
            _carb_float3(*target_xy),
            agent_radius=agent_radius,
        )
        return path is not None
    except Exception:
        return False


def get_worker_pos(stage, worker_name):
    """Read a worker's current world (x, y) from its xform translate.

    Returns None if the prim isn't on the stage yet.
    """
    try:
        from pxr import UsdGeom, Gf
    except ImportError:
        return None
    prim = stage.GetPrimAtPath(f"/World/Characters/{worker_name}")
    if not prim or not prim.IsValid():
        return None
    xf = UsdGeom.Xformable(prim)
    for op in xf.GetOrderedXformOps():
        if op.GetOpType() == UsdGeom.XformOp.TypeTranslate:
            v = op.Get()
            if v is not None:
                return float(v[0]), float(v[1])
    # Fallback: compute from local-to-world.
    try:
        m = xf.ComputeLocalToWorldTransform(0.0)
        t = m.ExtractTranslation()
        return float(t[0]), float(t[1])
    except Exception:
        return None


def try_snap_target(origin_xy, target_xy, navmesh=None,
                    agent_radius=AGENT_RADIUS,
                    max_radius=DEFAULT_MAX_RADIUS,
                    num_rings=DEFAULT_NUM_RINGS,
                    samples_per_ring=DEFAULT_SAMPLES_PER_RING):
    """Return a reachable (x, y) near target_xy, or None if none found.

    If target_xy is already reachable, returns it unchanged. Otherwise
    spirals outward and returns the nearest reachable sample. Returns
    None when nothing within max_radius is reachable — caller should
    drop the command rather than ship an unrouteable target.

    No-op (returns target_xy) when no navmesh is available.
    """
    if navmesh is None:
        navmesh = get_navmesh()
    if navmesh is None:
        return target_xy

    if _is_reachable(navmesh, origin_xy, target_xy, agent_radius):
        return target_xy

    tx, ty = float(target_xy[0]), float(target_xy[1])
    for ring in range(1, num_rings + 1):
        r = (ring / num_rings) * max_radius
        phase = (ring % 2) * (math.pi / samples_per_ring)
        for s in range(samples_per_ring):
            angle = phase + (s / samples_per_ring) * 2.0 * math.pi
            cand = (tx + r * math.cos(angle), ty + r * math.sin(angle))
            if _is_reachable(navmesh, origin_xy, cand, agent_radius):
                return cand

    return None


def snap_target(origin_xy, target_xy, navmesh=None,
                agent_radius=AGENT_RADIUS,
                max_radius=DEFAULT_MAX_RADIUS,
                num_rings=DEFAULT_NUM_RINGS,
                samples_per_ring=DEFAULT_SAMPLES_PER_RING):
    """Backward-compatible wrapper: falls back to origin_xy on miss."""
    snapped = try_snap_target(origin_xy, target_xy, navmesh=navmesh,
                              agent_radius=agent_radius,
                              max_radius=max_radius,
                              num_rings=num_rings,
                              samples_per_ring=samples_per_ring)
    if snapped is None:
        print(f"[WARN] navmesh_utils: no reachable point within {max_radius}m of "
              f"({float(target_xy[0]):.2f}, {float(target_xy[1]):.2f}) from origin "
              f"({origin_xy[0]:.2f}, {origin_xy[1]:.2f}); holding at origin")
        return (float(origin_xy[0]), float(origin_xy[1]))
    return snapped
