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
from pxr import UsdGeom, Gf
import omni.usd


def spawn_at_fixed_position(asset_path, position, rotation=(0, 0, 0), semantic_class=None, prim_name=None):
    """Spawn an entity at a deterministic position using direct USD xform ops.

    Unlike get_geofenced_spawner which uses Replicator randomization
    (which re-rolls position every frame), this creates a fixed prim
    with explicit translate/rotate ops that never change.

    Args:
        asset_path: USD path to the asset.
        position: (x, y, z) position in meters.
        rotation: (rx, ry, rz) rotation in degrees.
        semantic_class: Optional semantic class name for labeling.
        prim_name: Optional explicit name for the prim. If None, derives from basename.

    Returns:
        Tuple of (prim_path, (x, y)) for tracking spawn position.
    """
    stage = omni.usd.get_context().get_stage()

    if prim_name:
        basename = prim_name
    else:
        basename = asset_path.rstrip("/").split("/")[-1].replace(".usd", "")
        
    parent_path = "/World/Entities"
    if not stage.GetPrimAtPath(parent_path):
        stage.DefinePrim(parent_path, "Xform")

    prim_path = f"{parent_path}/{basename}"
    counter = 1
    while stage.GetPrimAtPath(prim_path):
        prim_path = f"{parent_path}/{basename}_{counter}"
        counter += 1

    prim = stage.DefinePrim(prim_path, "Xform")
    prim.GetReferences().AddReference(asset_path)

    xf = UsdGeom.Xformable(prim)
    xf.ClearXformOpOrder()
    xf.AddTranslateOp().Set(Gf.Vec3d(float(position[0]), float(position[1]), float(position[2])))
    xf.AddRotateXYZOp().Set(Gf.Vec3d(float(rotation[0]), float(rotation[1]), float(rotation[2])))

    if semantic_class:
        from isaac_backend.semantics import apply_usd_semantics
        apply_usd_semantics(prim, semantic_class)

    spawn_pos = (float(position[0]), float(position[1]))
    print(f"[INFO] Fixed-spawn '{basename}' -> {prim_path} at ({position[0]:.2f}, {position[1]:.2f}, {position[2]:.2f}) sem='{semantic_class}'")
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

    print(f"[WARN] anchor_zone '{anchor_zone}' did not match any hazard zone name. Available: {[z.get('name') for z in hazard_zones]}")
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

        # Check if we should parent this zone to an existing entity (e.g. for moving hazards)
        parent_path = "/World/HazardZones"
        for prim in stage.Traverse():
            if prim.GetName().lower() == name.lower() and "/World/Entities/" in str(prim.GetPath()):
                parent_path = str(prim.GetPath())
                print(f"[INFO] Parenting hazard zone '{name}' to entity at {parent_path}")
                break

        cx = (bmin[0] + bmax[0]) / 2.0
        cy = (bmin[1] + bmax[1]) / 2.0
        
        # If parented to an entity, use relative offset 0,0 instead of absolute world coords
        if parent_path != "/World/HazardZones":
            pos = Gf.Vec3d(0, 0, 0.5)
        else:
            pos = Gf.Vec3d(cx, cy, 0.5)

        sx = abs(bmax[0] - bmin[0])
        sy = abs(bmax[1] - bmin[1])

        prim_path = f"{parent_path}/hazard_volume"
        prim = stage.DefinePrim(prim_path, "Cube")

        # Flat floor decal: 2cm thin so it never occludes workers or vehicles.
        # Semantics still land on the rendered pixels for CocoWriter detection.
        flat_pos = Gf.Vec3d(pos[0], pos[1], 0.01)
        xf = UsdGeom.Xformable(prim)
        xf.ClearXformOpOrder()
        xf.AddTranslateOp().Set(flat_pos)
        xf.AddScaleOp().Set(Gf.Vec3d(sx, sy, 0.01))

        # Hide from all render passes (RGB and segmentation) — zones are spatial
        # logic helpers only; annotations come from worker/vehicle detections.
        UsdGeom.Imageable(prim).MakeInvisible()

        from isaac_backend.semantics import apply_usd_semantics
        apply_usd_semantics(prim, f"hazard_zone_{danger}")

        print(f"[INFO] Hazard zone '{name}' at ({cx:.1f}, {cy:.1f}) size={sx:.1f}x{sy:.1f} danger={danger}")