"""Dock equipment: doors, levelers, trucks."""

import math
import random

from pxr import UsdGeom, Gf, UsdPhysics

from isaac_backend.layouts.geometry import DEFAULT_CEILING_Z
from isaac_backend.layouts.placement import _place, _draw_floor_glyph, _GLYPH_3x5
from isaac_backend.layouts.materials import bind_material


def _place_dock_door(stage, idx, x, y, width=2.6, height=3.2, rot_z=0):
    """Sectional roll-up loading-bay door — four horizontal panels with thin
    seams between, plus a darker frame around the opening."""
    panel_color = (0.78, 0.78, 0.74)
    seam_color = (0.45, 0.45, 0.42)
    frame_color = (0.25, 0.25, 0.27)
    ang = math.radians(rot_z)
    cos_a, sin_a = math.cos(ang), math.sin(ang)
    n_panels = 4
    panel_h = height / n_panels
    for p in range(n_panels):
        z = panel_h / 2.0 + p * panel_h
        path = f"/World/Layout/dock_panel_{idx}_{p}"
        cube = UsdGeom.Cube.Define(stage, path)
        cube.GetSizeAttr().Set(2.0)
        pxf = UsdGeom.XformCommonAPI(cube.GetPrim())
        pxf.SetScale(Gf.Vec3f(width / 2.0, 0.04, panel_h / 2.0 - 0.01))
        pxf.SetTranslate(Gf.Vec3d(x, y, z))
        pxf.SetRotate(Gf.Vec3f(0, 0, rot_z), UsdGeom.XformCommonAPI.RotationOrderXYZ)
        bind_material(stage, cube, "M_AgedSteel", panel_color)
    # Frame: two side jambs + a header bar
    for sgn_i, sgn in enumerate((-1, 1)):
        local_x = sgn * (width / 2.0 + 0.06)
        wx = x + local_x * cos_a
        wy = y + local_x * sin_a
        path = f"/World/Layout/dock_jamb_{idx}_{sgn_i}"
        cube = UsdGeom.Cube.Define(stage, path)
        cube.GetSizeAttr().Set(2.0)
        jxf = UsdGeom.XformCommonAPI(cube.GetPrim())
        jxf.SetScale(Gf.Vec3f(0.06, 0.06, height / 2.0))
        jxf.SetTranslate(Gf.Vec3d(wx, wy, height / 2.0))
        jxf.SetRotate(Gf.Vec3f(0, 0, rot_z), UsdGeom.XformCommonAPI.RotationOrderXYZ)
        bind_material(stage, cube, "M_AgedSteel", frame_color)
    head_path = f"/World/Layout/dock_header_{idx}"
    head = UsdGeom.Cube.Define(stage, head_path)
    head.GetSizeAttr().Set(2.0)
    hxf = UsdGeom.XformCommonAPI(head.GetPrim())
    hxf.SetScale(Gf.Vec3f(width / 2.0 + 0.08, 0.06, 0.10))
    hxf.SetTranslate(Gf.Vec3d(x, y, height + 0.05))
    hxf.SetRotate(Gf.Vec3f(0, 0, rot_z), UsdGeom.XformCommonAPI.RotationOrderXYZ)
    bind_material(stage, head, "M_AgedSteel", frame_color)
    return idx + 1



def _place_dock_leveler(stage, idx, x, y, width=2.4, depth=1.0):
    """Steel dock leveler plate just inside the dock door — slight ramp tone."""
    path = f"/World/Layout/leveler_{idx}"
    cube = UsdGeom.Cube.Define(stage, path)
    cube.GetSizeAttr().Set(2.0)
    xf = UsdGeom.XformCommonAPI(cube.GetPrim())
    xf.SetScale(Gf.Vec3f(width / 2.0, depth / 2.0, 0.025))
    xf.SetTranslate(Gf.Vec3d(x, y, 0.025))
    bind_material(stage, cube, "M_AgedSteel", (0.42, 0.42, 0.45))
    return idx + 1



def _place_open_dock_door(stage, idx, x, y, width=2.6, height=3.2, rot_z=0):
    """Open dock door — two side jambs + header + a panel-bundle 'rolled-up'
    rectangle below the header + a dark threshold strip along the floor where
    the door used to seal. Reads as 'truck is currently being loaded here.'"""
    frame_color = (0.25, 0.25, 0.27)
    threshold_color = (0.10, 0.10, 0.12)
    ang = math.radians(rot_z)
    cos_a, sin_a = math.cos(ang), math.sin(ang)
    for sgn_i, sgn in enumerate((-1, 1)):
        local_x = sgn * (width / 2.0 + 0.06)
        wx = x + local_x * cos_a
        wy = y + local_x * sin_a
        path = f"/World/Layout/odock_jamb_{idx}_{sgn_i}"
        cube = UsdGeom.Cube.Define(stage, path)
        cube.GetSizeAttr().Set(2.0)
        jxf = UsdGeom.XformCommonAPI(cube.GetPrim())
        jxf.SetScale(Gf.Vec3f(0.06, 0.06, height / 2.0))
        jxf.SetTranslate(Gf.Vec3d(wx, wy, height / 2.0))
        jxf.SetRotate(Gf.Vec3f(0, 0, rot_z),
                      UsdGeom.XformCommonAPI.RotationOrderXYZ)
        bind_material(stage, cube, "M_AgedSteel", frame_color)
    head_path = f"/World/Layout/odock_header_{idx}"
    head = UsdGeom.Cube.Define(stage, head_path)
    head.GetSizeAttr().Set(2.0)
    hxf = UsdGeom.XformCommonAPI(head.GetPrim())
    hxf.SetScale(Gf.Vec3f(width / 2.0 + 0.08, 0.06, 0.10))
    hxf.SetTranslate(Gf.Vec3d(x, y, height + 0.05))
    hxf.SetRotate(Gf.Vec3f(0, 0, rot_z),
                  UsdGeom.XformCommonAPI.RotationOrderXYZ)
    bind_material(stage, head, "M_AgedSteel", frame_color)
    bundle_path = f"/World/Layout/odock_bundle_{idx}"
    bundle = UsdGeom.Cube.Define(stage, bundle_path)
    bundle.GetSizeAttr().Set(2.0)
    bxf = UsdGeom.XformCommonAPI(bundle.GetPrim())
    bxf.SetScale(Gf.Vec3f(width / 2.0 - 0.05, 0.20, 0.20))
    bxf.SetTranslate(Gf.Vec3d(x, y + 0.15, height - 0.10))
    bxf.SetRotate(Gf.Vec3f(0, 0, rot_z),
                  UsdGeom.XformCommonAPI.RotationOrderXYZ)
    bind_material(stage, bundle, "M_AgedSteel", (0.62, 0.62, 0.58))
    thr_path = f"/World/Layout/odock_thresh_{idx}"
    thr = UsdGeom.Cube.Define(stage, thr_path)
    thr.GetSizeAttr().Set(2.0)
    txf = UsdGeom.XformCommonAPI(thr.GetPrim())
    txf.SetScale(Gf.Vec3f(width / 2.0, 0.15, 0.025))
    txf.SetTranslate(Gf.Vec3d(x, y, 0.025))
    txf.SetRotate(Gf.Vec3f(0, 0, rot_z),
                  UsdGeom.XformCommonAPI.RotationOrderXYZ)
    bind_material(stage, thr, "M_PaintedConcrete", threshold_color)
    return idx + 5



def _place_truck_back(stage, idx, x, y, width=2.6, depth=4.5, height=3.0,
                       color=(0.25, 0.30, 0.45)):
    """Crude box-truck silhouette parked at the dock — large dark cuboid +
    two darker vertical seams on the back face + two red tail-light stubs."""
    body_path = f"/World/Layout/truck_body_{idx}"
    body = UsdGeom.Cube.Define(stage, body_path)
    body.GetSizeAttr().Set(2.0)
    bxf = UsdGeom.XformCommonAPI(body.GetPrim())
    bxf.SetScale(Gf.Vec3f(width / 2.0, depth / 2.0, height / 2.0))
    bxf.SetTranslate(Gf.Vec3d(x, y, height / 2.0))
    bind_material(stage, body, "M_AgedSteel", color)
    for sgn_i, sgn in enumerate((-1, 1)):
        s_path = f"/World/Layout/truck_seam_{idx}_{sgn_i}"
        s = UsdGeom.Cube.Define(stage, s_path)
        s.GetSizeAttr().Set(2.0)
        sxf = UsdGeom.XformCommonAPI(s.GetPrim())
        sxf.SetScale(Gf.Vec3f(0.025, 0.04, height / 2.0 - 0.10))
        sxf.SetTranslate(Gf.Vec3d(x + sgn * width * 0.40,
                                   y + depth / 2.0 - 0.04,
                                   height / 2.0))
        bind_material(stage, s, "M_AgedSteel", (0.15, 0.18, 0.25))
    for sgn_i, sgn in enumerate((-1, 1)):
        l_path = f"/World/Layout/truck_taillight_{idx}_{sgn_i}"
        L = UsdGeom.Cube.Define(stage, l_path)
        L.GetSizeAttr().Set(2.0)
        lxf = UsdGeom.XformCommonAPI(L.GetPrim())
        lxf.SetScale(Gf.Vec3f(0.16, 0.04, 0.10))
        lxf.SetTranslate(Gf.Vec3d(x + sgn * width * 0.42,
                                   y + depth / 2.0 - 0.05, 0.55))
        bind_material(stage, L, "M_Emissive", (0.85, 0.10, 0.10))
    return idx + 5



def _place_dock_leveler_ramped(stage, idx, x, y, width=2.4, depth=1.4,
                                tilt_deg=8):
    """Angled steel leveler that bridges the warehouse threshold to a truck
    bed — tilts down toward -Y (where the truck is parked)."""
    path = f"/World/Layout/leveler_ramped_{idx}"
    cube = UsdGeom.Cube.Define(stage, path)
    cube.GetSizeAttr().Set(2.0)
    xf = UsdGeom.XformCommonAPI(cube.GetPrim())
    xf.SetScale(Gf.Vec3f(width / 2.0, depth / 2.0, 0.025))
    xf.SetTranslate(Gf.Vec3d(x, y, 0.10))
    xf.SetRotate(Gf.Vec3f(-tilt_deg, 0, 0),
                 UsdGeom.XformCommonAPI.RotationOrderXYZ)
    bind_material(stage, cube, "M_AgedSteel", (0.45, 0.45, 0.48))
    return idx + 1


