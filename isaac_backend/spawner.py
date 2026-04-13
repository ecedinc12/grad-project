"""
Geofenced Entity Spawner + Hazard Zone Creator

Uses Replicator randomizer for entity spawning within XY bounds.
Creates invisible USD volumes with hazard_zone semantics for zone detection.
"""

import random
import omni.replicator.core as rep
from pxr import UsdGeom, Gf, Sdf
import omni.usd


def get_geofenced_spawner(asset_path, num_instances=1, bounds_min=(-10, -10), bounds_max=(10, 10)):
    """Return a callable that spawns entities at random XY positions within bounds."""
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
