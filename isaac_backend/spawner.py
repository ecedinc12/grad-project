"""
Geofenced Entity Spawner + Hazard Zone Creator

Supports two spawning modes:
1. Fixed-position: places an entity at a deterministic (x, y) position.
2. Geofenced random: uses Replicator randomizer to place within bounds.

Entities with an anchor_zone are placed at the center of the matching
hazard zone using fixed-position spawning. Entities without an anchor_zone
use geofenced random spawning within the warehouse bounds.

Creates invisible USD volumes with hazard_zone semantics for zone detection.
"""

import random
import omni.replicator.core as rep
from pxr import UsdGeom, Gf, Sdf
import omni.usd


def spawn_at_fixed_position(asset_path, position, rotation=(0, 0, 0), semantic_class=None):
    """Spawn an entity at a deterministic position using direct USD xform ops.

    Unlike get_geofenced_spawner which uses Replicator randomization
    (which re-rolls position every frame), this creates a fixed prim
    with explicit translate/rotate ops that never change.

    Args:
        asset_path: USD path to the asset.
        position: (x, y, z) position in meters.
        rotation: (rx, ry, rz) rotation in degrees.
        semantic_class: Optional semantic class name for labeling.

    Returns:
        Tuple of (prim_path, (x, y)) for tracking spawn position.
    """
    stage = omni.usd.get_context().get_stage()

    basename = asset_path.rstrip("/").split("/")[-1].replace(".usd", "")
    prim_path = f"/World/Layout/{basename}"
    counter = 1
    while stage.GetPrimAtPath(prim_path):
        prim_path = f"/World/Layout/{basename}_{counter}"
        counter += 1

    prim = stage.DefinePrim(prim_path, "Xform")
    prim.GetReferences().AddReference(asset_path)

    xf = UsdGeom.Xformable(prim)
    xf.ClearXformOpOrder()
    xf.AddTranslateOp().Set(Gf.Vec3d(float(position[0]), float(position[1]), float(position[2])))
    xf.AddRotateYOp().Set(float(rotation[1]))

    if semantic_class:
        prim.CreateAttribute("semantic:Semantics:params:semanticData", Sdf.ValueTypeNames.Token, True).Set(semantic_class)
        prim.CreateAttribute("semantic:Semantics:params:semanticType", Sdf.ValueTypeNames.Token, True).Set("class")

    spawn_pos = (float(position[0]), float(position[1]))
    print(f"[INFO] Fixed-spawn {basename} at ({position[0]:.2f}, {position[1]:.2f}, {position[2]:.2f}) sem={semantic_class}")
    return prim_path, spawn_pos


def resolve_anchor_zone_bounds(anchor_zone, hazard_zones):
    """Look up the bounding box for an anchor_zone name in hazard_zones.

    Returns ((xmin, ymin), (xmax, ymax)) or None if not found.
    """
    if not anchor_zone or not hazard_zones:
        return None

    target = anchor_zone.lower().replace(" ", "_").replace("-", "_")
    for zone in hazard_zones:
        zone_name = zone.get("name", "").lower().replace(" ", "_").replace("-", "_")
        if zone_name == target or target in zone_name or zone_name in target:
            bmin = zone.get("bounds_min", (-2, -2))
            bmax = zone.get("bounds_max", (2, 2))
            return (tuple(bmin), tuple(bmax))

    return None


def get_geofenced_spawner(asset_path, num_instances=1, bounds_min=(-10, -10), bounds_max=(10, 10)):
    """Return a callable that spawns entities at random XY positions within bounds.

    WARNING: This uses Replicator's rep.distribution.uniform which re-randomizes
    position on every orchestrator.step() call. For entities that need to stay
    in a fixed position (e.g. vehicles), use spawn_at_fixed_position instead.
    """
    def spawn_in_bounds():
        prims = rep.create.from_usd(asset_path, count=num_instances)
        with prims:
            rep.modify.pose(
                position=rep.distribution.uniform(
                    (bounds_min[0], bounds_min[1], 0),
                    (bounds_max[0], bounds_max[1], 0)
                ),
                rotation=rep.distribution.uniform((0, 0, 0), (0, 0, 360))
            )
        return prims

    rep.randomizer.register(spawn_in_bounds)
    return spawn_in_bounds


def spawn_hazard_zones(hazard_zones, stage):
    """Create invisible USD volumes with hazard_zone semantics.

    These appear in bounding box and segmentation output but not in RGB,
    enabling the model to learn zone-based safety violations.
    """
    stage.DefinePrim("/World/HazardZones", "Xform")

    for zone in hazard_zones:
        name = zone.get("name", f"zone_{random.randint(0, 999)}")
        bmin = zone.get("bounds_min", (-2, -2))
        bmax = zone.get("bounds_max", (2, 2))
        danger = zone.get("danger_level", "warning")

        cx = (bmin[0] + bmax[0]) / 2.0
        cy = (bmin[1] + bmax[1]) / 2.0
        sx = abs(bmax[0] - bmin[0])
        sy = abs(bmax[1] - bmin[1])

        prim_path = f"/World/HazardZones/{name}"
        prim = stage.DefinePrim(prim_path, "Cube")

        xf = UsdGeom.Xformable(prim)
        xf.ClearXformOpOrder()
        xf.AddTranslateOp().Set(Gf.Vec3d(cx, cy, 0.5))
        xf.AddScaleOp().Set(Gf.Vec3d(sx, sy, 1.0))

        UsdGeom.Imageable(prim).MakeInvisible()

        prim.CreateAttribute("semantic:Semantics:params:semanticData", Sdf.ValueTypeNames.Token, True).Set(f"hazard_zone_{danger}")
        prim.CreateAttribute("semantic:Semantics:params:semanticType", Sdf.ValueTypeNames.Token, True).Set("class")

        print(f"[INFO] Hazard zone '{name}' at ({cx:.1f}, {cy:.1f}) size={sx:.1f}x{sy:.1f} danger={danger}")