"""Ceiling fixtures: overhead lights, sprinklers, pipe runs."""

import math
import random

from pxr import UsdGeom, Gf, UsdPhysics

from isaac_backend.layouts.geometry import DEFAULT_CEILING_Z
from isaac_backend.layouts.placement import _place, _draw_floor_glyph, _GLYPH_3x5
from isaac_backend.layouts.materials import bind_material


def _place_overhead_light(stage, idx, x, y, z=None, length=2.0):
    if z is None:
        z = DEFAULT_CEILING_Z - 0.15
    """Long thin white cuboid as a ceiling strip light."""
    path = f"/World/Layout/ceil_light_{idx}"
    cube = UsdGeom.Cube.Define(stage, path)
    cube.GetSizeAttr().Set(2.0)
    prim = cube.GetPrim()
    xf = UsdGeom.XformCommonAPI(prim)
    xf.SetScale(Gf.Vec3f(length / 2.0, 0.10, 0.04))
    xf.SetTranslate(Gf.Vec3d(x, y, z))
    bind_material(stage, cube, "M_Emissive", (0.96, 0.96, 0.92))
    return idx + 1



def _place_sprinkler_head(stage, idx, x, y, z=None):
    if z is None:
        z = DEFAULT_CEILING_Z - 0.05
    """Small red-tipped sprinkler head pendant from the ceiling."""
    body_path = f"/World/Layout/sprinkler_{idx}"
    body = UsdGeom.Cylinder.Define(stage, body_path)
    body.GetRadiusAttr().Set(0.04)
    body.GetHeightAttr().Set(0.12)
    body.GetAxisAttr().Set("Z")
    bxf = UsdGeom.XformCommonAPI(body.GetPrim())
    bxf.SetTranslate(Gf.Vec3d(x, y, z))
    bind_material(stage, body, "M_AgedSteel", (0.65, 0.65, 0.62))
    bulb_path = f"/World/Layout/sprinkler_bulb_{idx}"
    bulb = UsdGeom.Sphere.Define(stage, bulb_path)
    bulb.GetRadiusAttr().Set(0.035)
    sxf = UsdGeom.XformCommonAPI(bulb.GetPrim())
    sxf.SetTranslate(Gf.Vec3d(x, y, z - 0.09))
    bind_material(stage, bulb, "M_PlasticGloss", (0.85, 0.10, 0.10))
    return idx + 2



def _place_ceiling_pipe_run(stage, idx, x_start, x_end, y, z=4.7, color=(0.55, 0.30, 0.18)):
    """Long thin cylinder spanning across ceiling — gas/sprinkler/conduit pipe."""
    length = abs(x_end - x_start)
    if length < 0.5:
        return idx
    path = f"/World/Layout/pipe_{idx}"
    cyl = UsdGeom.Cylinder.Define(stage, path)
    cyl.GetRadiusAttr().Set(0.06)
    cyl.GetHeightAttr().Set(length)
    cyl.GetAxisAttr().Set("X")
    cxf = UsdGeom.XformCommonAPI(cyl.GetPrim())
    cxf.SetTranslate(Gf.Vec3d((x_start + x_end) / 2.0, y, z))
    bind_material(stage, cyl, "M_AgedSteel", color)
    return idx + 1


