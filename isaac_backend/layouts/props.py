"""
Leaf prop primitives.

Every `_place_*` here authors a small composed USD prop (sign, bollard,
stain, sprinkler, etc.) on the stage and returns the next free idx. They
are deliberately decoupled from the layout-scale spawners — a spawner
picks positions, a prop primitive draws geometry.
"""

import math
import random

from pxr import UsdGeom, Gf, UsdPhysics

from .geometry import DEFAULT_CEILING_Z
from .placement import _place, _draw_floor_glyph, _GLYPH_3x5
from .materials import bind_material


def _place_column_guard(stage, idx, x, y, height=0.55):
    """Yellow plastic-style column-protector stub at a rack corner, wrapped in
    a black/yellow hazard chevron pattern (alternating thin black bands)."""
    path = f"/World/Layout/col_guard_{idx}"
    cyl = UsdGeom.Cylinder.Define(stage, path)
    cyl.GetRadiusAttr().Set(0.12)
    cyl.GetHeightAttr().Set(height)
    cyl.GetAxisAttr().Set("Z")
    prim = cyl.GetPrim()
    xf = UsdGeom.XformCommonAPI(prim)
    xf.SetTranslate(Gf.Vec3d(x, y, height / 2.0))
    bind_material(stage, cyl, "M_YellowSafetyPaint", (0.95, 0.78, 0.05))
    if not prim.HasAPI(UsdPhysics.CollisionAPI):
        UsdPhysics.CollisionAPI.Apply(prim)
    # Hazard chevron — three thin black bands wrapping the post. Slightly
    # larger radius so they sit proud of the yellow base instead of z-fighting.
    band_count = 3
    band_h = 0.05
    for b in range(band_count):
        bz = (b + 1) * height / (band_count + 1)
        band_path = f"/World/Layout/col_guard_band_{idx}_{b}"
        band = UsdGeom.Cylinder.Define(stage, band_path)
        band.GetRadiusAttr().Set(0.125)
        band.GetHeightAttr().Set(band_h)
        band.GetAxisAttr().Set("Z")
        bxf = UsdGeom.XformCommonAPI(band.GetPrim())
        bxf.SetTranslate(Gf.Vec3d(x, y, bz))
        bind_material(stage, band, "M_PlasticMatte", (0.05, 0.05, 0.05))
    return idx + 1


def _place_charger_box(stage, idx, x, y, rot_z=0):
    """Simple boxy 'battery charging station' — gray cabinet."""
    path = f"/World/Layout/charger_{idx}"
    cube = UsdGeom.Cube.Define(stage, path)
    cube.GetSizeAttr().Set(2.0)
    prim = cube.GetPrim()
    xf = UsdGeom.XformCommonAPI(prim)
    xf.SetScale(Gf.Vec3f(0.45, 0.35, 0.55))  # ~0.9m wide, 0.7m deep, 1.1m tall
    xf.SetTranslate(Gf.Vec3d(x, y, 0.55))
    xf.SetRotate(Gf.Vec3f(0, 0, rot_z), UsdGeom.XformCommonAPI.RotationOrderXYZ)
    bind_material(stage, cube, "M_PaintedWall", (0.32, 0.34, 0.38))
    if not prim.HasAPI(UsdPhysics.CollisionAPI):
        UsdPhysics.CollisionAPI.Apply(prim)
    return idx + 1


def _place_shelf_placard(stage, idx, x, y, z, rot_z, band_color=None):
    """Small SKU placard on a rack upright — white body with an optional
    colored bay-ID band along the top to mimic A-1, B-2 style aisle labels."""
    path = f"/World/Layout/placard_{idx}"
    cube = UsdGeom.Cube.Define(stage, path)
    cube.GetSizeAttr().Set(2.0)
    prim = cube.GetPrim()
    xf = UsdGeom.XformCommonAPI(prim)
    xf.SetScale(Gf.Vec3f(0.18, 0.02, 0.06))
    xf.SetTranslate(Gf.Vec3d(x, y, z))
    xf.SetRotate(Gf.Vec3f(0, 0, rot_z), UsdGeom.XformCommonAPI.RotationOrderXYZ)
    bind_material(stage, cube, "M_PlasticMatte", (0.95, 0.95, 0.92))
    used = 1
    if band_color is not None:
        band_path = f"/World/Layout/placard_band_{idx}"
        band = UsdGeom.Cube.Define(stage, band_path)
        band.GetSizeAttr().Set(2.0)
        bxf = UsdGeom.XformCommonAPI(band.GetPrim())
        # Sits along the top edge of the placard, slightly proud on the +Y side.
        bxf.SetScale(Gf.Vec3f(0.18, 0.022, 0.018))
        bxf.SetTranslate(Gf.Vec3d(x, y, z + 0.045))
        bxf.SetRotate(Gf.Vec3f(0, 0, rot_z), UsdGeom.XformCommonAPI.RotationOrderXYZ)
        bind_material(stage, band, "M_PlasticMatte", band_color)
        used += 1
    return idx + used


def _place_fire_extinguisher(stage, idx, x, y):
    """Red cylinder mounted on a wall — wall-side fire extinguisher."""
    base_path = f"/World/Layout/fire_ext_{idx}"
    cyl = UsdGeom.Cylinder.Define(stage, base_path)
    cyl.GetRadiusAttr().Set(0.09)
    cyl.GetHeightAttr().Set(0.55)
    cyl.GetAxisAttr().Set("Z")
    prim = cyl.GetPrim()
    xf = UsdGeom.XformCommonAPI(prim)
    xf.SetTranslate(Gf.Vec3d(x, y, 1.10))
    bind_material(stage, cyl, "M_PlasticGloss", (0.78, 0.08, 0.07))
    # Backplate
    bp_path = f"/World/Layout/fire_ext_plate_{idx}"
    plate = UsdGeom.Cube.Define(stage, bp_path)
    plate.GetSizeAttr().Set(2.0)
    pxf = UsdGeom.XformCommonAPI(plate.GetPrim())
    pxf.SetScale(Gf.Vec3f(0.18, 0.02, 0.32))
    pxf.SetTranslate(Gf.Vec3d(x, y - 0.06, 1.10))
    bind_material(stage, plate, "M_PaintedWall", (0.85, 0.85, 0.82))
    return idx + 2


def _place_exit_sign(stage, idx, x, y, z=2.6):
    """Green emissive exit sign plane high on the wall."""
    path = f"/World/Layout/exit_sign_{idx}"
    cube = UsdGeom.Cube.Define(stage, path)
    cube.GetSizeAttr().Set(2.0)
    prim = cube.GetPrim()
    xf = UsdGeom.XformCommonAPI(prim)
    xf.SetScale(Gf.Vec3f(0.30, 0.04, 0.14))
    xf.SetTranslate(Gf.Vec3d(x, y, z))
    bind_material(stage, cube, "M_Emissive", (0.10, 0.85, 0.25))
    return idx + 1


def _place_trash_bin(stage, idx, x, y, color=(0.18, 0.42, 0.18)):
    path = f"/World/Layout/bin_{idx}"
    cyl = UsdGeom.Cylinder.Define(stage, path)
    cyl.GetRadiusAttr().Set(0.22)
    cyl.GetHeightAttr().Set(0.75)
    cyl.GetAxisAttr().Set("Z")
    prim = cyl.GetPrim()
    xf = UsdGeom.XformCommonAPI(prim)
    xf.SetTranslate(Gf.Vec3d(x, y, 0.375))
    bind_material(stage, cyl, "M_PlasticMatte", color)
    if not prim.HasAPI(UsdPhysics.CollisionAPI):
        UsdPhysics.CollisionAPI.Apply(prim)
    return idx + 1


def _place_pack_table(stage, idx, x, y, rot_z=0):
    """Wooden-toned packing table for the wrap/pack station."""
    path = f"/World/Layout/pack_table_{idx}"
    cube = UsdGeom.Cube.Define(stage, path)
    cube.GetSizeAttr().Set(2.0)
    prim = cube.GetPrim()
    xf = UsdGeom.XformCommonAPI(prim)
    xf.SetScale(Gf.Vec3f(0.90, 0.40, 0.04))
    xf.SetTranslate(Gf.Vec3d(x, y, 0.85))
    xf.SetRotate(Gf.Vec3f(0, 0, rot_z), UsdGeom.XformCommonAPI.RotationOrderXYZ)
    bind_material(stage, cube, "M_Wood", (0.55, 0.40, 0.25))
    if not prim.HasAPI(UsdPhysics.CollisionAPI):
        UsdPhysics.CollisionAPI.Apply(prim)
    # Four legs
    for leg_i, (sx, sy) in enumerate(((-0.85, -0.36), (0.85, -0.36), (-0.85, 0.36), (0.85, 0.36))):
        ang = math.radians(rot_z)
        wx = x + sx * math.cos(ang) - sy * math.sin(ang)
        wy = y + sx * math.sin(ang) + sy * math.cos(ang)
        leg_path = f"/World/Layout/pack_table_leg_{idx}_{leg_i}"
        leg = UsdGeom.Cube.Define(stage, leg_path)
        leg.GetSizeAttr().Set(2.0)
        lxf = UsdGeom.XformCommonAPI(leg.GetPrim())
        lxf.SetScale(Gf.Vec3f(0.04, 0.04, 0.42))
        lxf.SetTranslate(Gf.Vec3d(wx, wy, 0.42))
        bind_material(stage, leg, "M_Wood", (0.45, 0.32, 0.18))
    return idx + 1


def _place_cardboard_stack(stage, idx, x, y, rot_z=0, sheets=8):
    """Stack of flattened cardboard sheets — thin tan slabs."""
    path = f"/World/Layout/cardboard_{idx}"
    cube = UsdGeom.Cube.Define(stage, path)
    cube.GetSizeAttr().Set(2.0)
    prim = cube.GetPrim()
    h = 0.012 * sheets
    xf = UsdGeom.XformCommonAPI(prim)
    xf.SetScale(Gf.Vec3f(0.55, 0.40, h))
    xf.SetTranslate(Gf.Vec3d(x, y, h))
    xf.SetRotate(Gf.Vec3f(0, 0, rot_z), UsdGeom.XformCommonAPI.RotationOrderXYZ)
    bind_material(stage, cube, "M_Cardboard", (0.72, 0.55, 0.32))
    return idx + 1


def _place_floor_arrow(stage, idx, x, y, rot_z=0):
    """Yellow directional arrow painted on the floor — head + shaft."""
    yellow = (0.92, 0.78, 0.10)
    ang = math.radians(rot_z)
    cos_a, sin_a = math.cos(ang), math.sin(ang)
    # Shaft
    sh_path = f"/World/Layout/arrow_shaft_{idx}"
    sh = UsdGeom.Cube.Define(stage, sh_path)
    sh.GetSizeAttr().Set(2.0)
    sxf = UsdGeom.XformCommonAPI(sh.GetPrim())
    sxf.SetScale(Gf.Vec3f(0.55, 0.07, 0.012))
    sxf.SetTranslate(Gf.Vec3d(x, y, 0.013))
    sxf.SetRotate(Gf.Vec3f(0, 0, rot_z), UsdGeom.XformCommonAPI.RotationOrderXYZ)
    bind_material(stage, sh, "M_YellowSafetyPaint", yellow)
    # Head — two angled bars
    for sgn_i, sgn in enumerate((-1, 1)):
        hd_path = f"/World/Layout/arrow_head_{idx}_{sgn_i}"
        hd = UsdGeom.Cube.Define(stage, hd_path)
        hd.GetSizeAttr().Set(2.0)
        hxf = UsdGeom.XformCommonAPI(hd.GetPrim())
        hxf.SetScale(Gf.Vec3f(0.28, 0.07, 0.012))
        # Tip is +X end of shaft (pre-rotation)
        local_x, local_y = 0.45, sgn * 0.18
        wx = x + local_x * cos_a - local_y * sin_a
        wy = y + local_x * sin_a + local_y * cos_a
        hxf.SetTranslate(Gf.Vec3d(wx, wy, 0.013))
        hxf.SetRotate(Gf.Vec3f(0, 0, rot_z + sgn * 35), UsdGeom.XformCommonAPI.RotationOrderXYZ)
        bind_material(stage, hd, "M_YellowSafetyPaint", yellow)
    return idx + 3


def _place_caution_sign(stage, idx, x, y, rot_z=0):
    """Yellow A-frame 'wet floor' caution sign — two angled panels."""
    yellow = (0.95, 0.82, 0.10)
    ang = math.radians(rot_z)
    cos_a, sin_a = math.cos(ang), math.sin(ang)
    for sgn_i, (sgn, tilt) in enumerate(((-1, 18), (1, -18))):
        path = f"/World/Layout/caution_{idx}_{sgn_i}"
        cube = UsdGeom.Cube.Define(stage, path)
        cube.GetSizeAttr().Set(2.0)
        prim = cube.GetPrim()
        xf = UsdGeom.XformCommonAPI(prim)
        xf.SetScale(Gf.Vec3f(0.16, 0.01, 0.32))
        local_x = sgn * 0.10
        wx = x + local_x * cos_a
        wy = y + local_x * sin_a
        xf.SetTranslate(Gf.Vec3d(wx, wy, 0.32))
        xf.SetRotate(Gf.Vec3f(0, tilt, rot_z), UsdGeom.XformCommonAPI.RotationOrderXYZ)
        bind_material(stage, cube, "M_PlasticGloss", yellow)
    return idx + 2


def _place_wall_junction_box(stage, idx, x, y, z=1.4):
    """Gray electrical junction box on a wall."""
    path = f"/World/Layout/junction_{idx}"
    cube = UsdGeom.Cube.Define(stage, path)
    cube.GetSizeAttr().Set(2.0)
    prim = cube.GetPrim()
    xf = UsdGeom.XformCommonAPI(prim)
    xf.SetScale(Gf.Vec3f(0.18, 0.04, 0.25))
    xf.SetTranslate(Gf.Vec3d(x, y, z))
    bind_material(stage, cube, "M_PaintedWall", (0.45, 0.47, 0.50))
    return idx + 1


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


def _place_aisle_sign(stage, idx, x, y, band_color, z=2.8):
    """Small hanging aisle-number placard with a colored band."""
    body_path = f"/World/Layout/aisle_sign_{idx}"
    body = UsdGeom.Cube.Define(stage, body_path)
    body.GetSizeAttr().Set(2.0)
    bxf = UsdGeom.XformCommonAPI(body.GetPrim())
    bxf.SetScale(Gf.Vec3f(0.22, 0.02, 0.16))
    bxf.SetTranslate(Gf.Vec3d(x, y, z))
    bind_material(stage, body, "M_PlasticMatte", (0.96, 0.96, 0.94))
    band_path = f"/World/Layout/aisle_sign_band_{idx}"
    band = UsdGeom.Cube.Define(stage, band_path)
    band.GetSizeAttr().Set(2.0)
    cxf = UsdGeom.XformCommonAPI(band.GetPrim())
    cxf.SetScale(Gf.Vec3f(0.22, 0.025, 0.04))
    cxf.SetTranslate(Gf.Vec3d(x, y, z + 0.18))
    bind_material(stage, band, "M_PlasticMatte", band_color)
    return idx + 2


def _place_mop_and_bucket(stage, idx, x, y):
    """Yellow mop bucket cylinder + thin angled broom handle."""
    bucket_path = f"/World/Layout/mop_bucket_{idx}"
    cyl = UsdGeom.Cylinder.Define(stage, bucket_path)
    cyl.GetRadiusAttr().Set(0.20)
    cyl.GetHeightAttr().Set(0.45)
    cyl.GetAxisAttr().Set("Z")
    bxf = UsdGeom.XformCommonAPI(cyl.GetPrim())
    bxf.SetTranslate(Gf.Vec3d(x, y, 0.225))
    bind_material(stage, cyl, "M_PlasticGloss", (0.92, 0.78, 0.10))
    broom_path = f"/World/Layout/broom_handle_{idx}"
    broom = UsdGeom.Cube.Define(stage, broom_path)
    broom.GetSizeAttr().Set(2.0)
    hxf = UsdGeom.XformCommonAPI(broom.GetPrim())
    hxf.SetScale(Gf.Vec3f(0.015, 0.015, 0.65))
    hxf.SetTranslate(Gf.Vec3d(x + 0.18, y + 0.05, 0.75))
    hxf.SetRotate(Gf.Vec3f(0, 14, 0), UsdGeom.XformCommonAPI.RotationOrderXYZ)
    bind_material(stage, broom, "M_Wood", (0.55, 0.38, 0.20))
    return idx + 2


def _place_tire_scuff(stage, idx, x, y, length, rot_z=0):
    """Broken stripe down an aisle centerline — forklift tire residue. Drawn
    as a chain of short rust-brown segments so it reads as worn rubber,
    not a solid line of paint."""
    color = (0.22, 0.16, 0.12)
    ang = math.radians(rot_z)
    cos_a, sin_a = math.cos(ang), math.sin(ang)
    seg_len = 0.70
    gap = 0.25
    pitch = seg_len + gap
    n_segs = max(1, int(length / pitch))
    start = -((n_segs - 1) * pitch) / 2.0
    for s in range(n_segs):
        if random.random() < 0.18:
            continue  # missing segment for natural unevenness
        local_x = start + s * pitch + random.uniform(-0.05, 0.05)
        local_y = random.uniform(-0.04, 0.04)
        wx = x + local_x * cos_a - local_y * sin_a
        wy = y + local_x * sin_a + local_y * cos_a
        path = f"/World/Layout/tire_scuff_{idx}_{s}"
        cube = UsdGeom.Cube.Define(stage, path)
        cube.GetSizeAttr().Set(2.0)
        sxf = UsdGeom.XformCommonAPI(cube.GetPrim())
        sxf.SetScale(Gf.Vec3f(seg_len / 2.0, 0.10, 0.006))
        sxf.SetTranslate(Gf.Vec3d(wx, wy, 0.018))
        sxf.SetRotate(Gf.Vec3f(0, 0, rot_z), UsdGeom.XformCommonAPI.RotationOrderXYZ)
        bind_material(stage, cube, "M_PaintedConcrete", color)
    return idx + 1


def _place_oil_stain(stage, idx, x, y, radius=0.55):
    """Irregular puddle — cluster of small flat dark blobs."""
    base_color = (0.12, 0.10, 0.08)
    for b in range(random.randint(5, 8)):
        ang = random.uniform(0, 2 * math.pi)
        r = random.uniform(0.0, radius)
        bx = x + r * math.cos(ang)
        by = y + r * math.sin(ang)
        sx = random.uniform(0.14, 0.28)
        sy = random.uniform(0.14, 0.28)
        path = f"/World/Layout/oil_blob_{idx}_{b}"
        cube = UsdGeom.Cube.Define(stage, path)
        cube.GetSizeAttr().Set(2.0)
        oxf = UsdGeom.XformCommonAPI(cube.GetPrim())
        oxf.SetScale(Gf.Vec3f(sx, sy, 0.005))
        oxf.SetTranslate(Gf.Vec3d(bx, by, 0.020))
        oxf.SetRotate(Gf.Vec3f(0, 0, random.uniform(0, 90)),
                      UsdGeom.XformCommonAPI.RotationOrderXYZ)
        bind_material(stage, cube, "M_OilFilm", base_color)
    return idx + 1


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


def _place_hazard_hatch(stage, idx, x, y, width, depth, rot_z=0, stripes=8):
    """Diagonal yellow/black hazard hatching laid on the floor."""
    ang = math.radians(rot_z)
    cos_a, sin_a = math.cos(ang), math.sin(ang)
    yellow = (0.95, 0.78, 0.10)
    black = (0.08, 0.08, 0.08)
    # Backplate (yellow)
    bp_path = f"/World/Layout/hazard_bp_{idx}"
    bp = UsdGeom.Cube.Define(stage, bp_path)
    bp.GetSizeAttr().Set(2.0)
    bxf = UsdGeom.XformCommonAPI(bp.GetPrim())
    bxf.SetScale(Gf.Vec3f(width / 2.0, depth / 2.0, 0.012))
    bxf.SetTranslate(Gf.Vec3d(x, y, 0.010))
    bxf.SetRotate(Gf.Vec3f(0, 0, rot_z), UsdGeom.XformCommonAPI.RotationOrderXYZ)
    bind_material(stage, bp, "M_YellowSafetyPaint", yellow)
    # Black diagonal stripes on top
    stripe_w = width / stripes
    for s in range(stripes):
        if s % 2 == 0:
            continue
        local_x = -width / 2.0 + (s + 0.5) * stripe_w
        wx = x + local_x * cos_a
        wy = y + local_x * sin_a
        sp_path = f"/World/Layout/hazard_st_{idx}_{s}"
        sp = UsdGeom.Cube.Define(stage, sp_path)
        sp.GetSizeAttr().Set(2.0)
        sxf = UsdGeom.XformCommonAPI(sp.GetPrim())
        sxf.SetScale(Gf.Vec3f(stripe_w * 0.55, depth / 2.0 * 1.4, 0.014))
        sxf.SetTranslate(Gf.Vec3d(wx, wy, 0.014))
        # Diagonal: rotate stripe ~45° relative to the patch.
        sxf.SetRotate(Gf.Vec3f(0, 0, rot_z + 45), UsdGeom.XformCommonAPI.RotationOrderXYZ)
        bind_material(stage, sp, "M_PaintedConcrete", black)
    return idx + 1 + (stripes // 2)


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


def _place_hi_vis_bollard(stage, idx, x, y, height=0.95):
    """Yellow/black banded bollard for dock-door corners and hazard markers."""
    base_path = f"/World/Layout/bollard_base_{idx}"
    base = UsdGeom.Cylinder.Define(stage, base_path)
    base.GetRadiusAttr().Set(0.10)
    base.GetHeightAttr().Set(height)
    base.GetAxisAttr().Set("Z")
    bxf = UsdGeom.XformCommonAPI(base.GetPrim())
    bxf.SetTranslate(Gf.Vec3d(x, y, height / 2.0))
    bind_material(stage, base, "M_YellowSafetyPaint", (0.95, 0.78, 0.05))
    # Two black bands at 1/3 and 2/3 height
    n_band = 2
    for b in range(n_band):
        band_path = f"/World/Layout/bollard_band_{idx}_{b}"
        band = UsdGeom.Cylinder.Define(stage, band_path)
        band.GetRadiusAttr().Set(0.105)
        band.GetHeightAttr().Set(0.10)
        band.GetAxisAttr().Set("Z")
        bndxf = UsdGeom.XformCommonAPI(band.GetPrim())
        bndxf.SetTranslate(Gf.Vec3d(x, y, height * (b + 1) / 3.0))
        bind_material(stage, band, "M_PlasticMatte", (0.06, 0.06, 0.06))
    return idx + 1 + n_band


def _place_empty_pallet_stack(stage, idx, x, y, asset_library, count=6, rot_z=0):
    """Stack of empty pallets — uses real pallet asset if available, else procedural slabs."""
    placed = 0
    if "pallet" in asset_library:
        for k in range(count):
            z = 0.14 * k
            jitter_rot = rot_z + random.uniform(-2, 2)
            idx = _place("pallet", x + random.uniform(-0.02, 0.02),
                         y + random.uniform(-0.02, 0.02), z, jitter_rot,
                         asset_library, stage, idx)
            placed += 1
    else:
        for k in range(count):
            path = f"/World/Layout/empty_pallet_{idx}"
            cube = UsdGeom.Cube.Define(stage, path)
            cube.GetSizeAttr().Set(2.0)
            xf = UsdGeom.XformCommonAPI(cube.GetPrim())
            xf.SetScale(Gf.Vec3f(0.60, 0.50, 0.07))
            xf.SetTranslate(Gf.Vec3d(x, y, 0.07 + 0.14 * k))
            bind_material(stage, cube, "M_Wood", (0.55, 0.40, 0.22))
            idx += 1
            placed += 1
    return idx, placed


def _place_parking_stall(stage, idx, x, y, width=2.2, depth=3.4, rot_z=0):
    """White rectangular outline marking a forklift parking stall on the floor."""
    color = (0.92, 0.92, 0.88)
    line_w = 0.08
    ang = math.radians(rot_z)
    cos_a, sin_a = math.cos(ang), math.sin(ang)
    # 4 sides
    sides = [
        (0, depth / 2.0, width, line_w),   # top
        (0, -depth / 2.0, width, line_w),  # bottom
        (-width / 2.0, 0, line_w, depth),  # left
        (width / 2.0, 0, line_w, depth),   # right
    ]
    placed = 0
    for (lx, ly, lw, ld) in sides:
        wx = x + lx * cos_a - ly * sin_a
        wy = y + lx * sin_a + ly * cos_a
        path = f"/World/Layout/stall_{idx}_{placed}"
        cube = UsdGeom.Cube.Define(stage, path)
        cube.GetSizeAttr().Set(2.0)
        xf = UsdGeom.XformCommonAPI(cube.GetPrim())
        xf.SetScale(Gf.Vec3f(lw / 2.0, ld / 2.0, 0.012))
        xf.SetTranslate(Gf.Vec3d(wx, wy, 0.013))
        xf.SetRotate(Gf.Vec3f(0, 0, rot_z), UsdGeom.XformCommonAPI.RotationOrderXYZ)
        bind_material(stage, cube, "M_PaintedConcrete", color)
        placed += 1
    return idx + placed


def _place_first_aid_kit(stage, idx, x, y, z=1.55):
    """White wall-mounted box with a red cross face."""
    path = f"/World/Layout/firstaid_{idx}"
    cube = UsdGeom.Cube.Define(stage, path)
    cube.GetSizeAttr().Set(2.0)
    xf = UsdGeom.XformCommonAPI(cube.GetPrim())
    xf.SetScale(Gf.Vec3f(0.18, 0.06, 0.14))
    xf.SetTranslate(Gf.Vec3d(x, y, z))
    bind_material(stage, cube, "M_PlasticMatte", (0.95, 0.95, 0.92))
    # Red cross — vertical bar + horizontal bar, slightly proud of the box face.
    for bi, (sx, sy, sz, color) in enumerate((
        (0.04, 0.005, 0.10, (0.85, 0.10, 0.10)),
        (0.10, 0.005, 0.03, (0.85, 0.10, 0.10)),
    )):
        bar_path = f"/World/Layout/firstaid_bar_{idx}_{bi}"
        bar = UsdGeom.Cube.Define(stage, bar_path)
        bar.GetSizeAttr().Set(2.0)
        bxf = UsdGeom.XformCommonAPI(bar.GetPrim())
        bxf.SetScale(Gf.Vec3f(sx, sy, sz))
        bxf.SetTranslate(Gf.Vec3d(x, y - 0.065, z))
        bind_material(stage, bar, "M_PlasticGloss", color)
    return idx + 3


def _place_wall_clock(stage, idx, x, y, z=2.4):
    """Round white clock face on a wall."""
    path = f"/World/Layout/clock_{idx}"
    cyl = UsdGeom.Cylinder.Define(stage, path)
    cyl.GetRadiusAttr().Set(0.20)
    cyl.GetHeightAttr().Set(0.04)
    cyl.GetAxisAttr().Set("Y")
    cxf = UsdGeom.XformCommonAPI(cyl.GetPrim())
    cxf.SetTranslate(Gf.Vec3d(x, y, z))
    bind_material(stage, cyl, "M_PlasticMatte", (0.95, 0.95, 0.92))
    # Minute & hour hands as thin cubes
    for hi, (sx, sz, sy_off, color) in enumerate(((0.005, 0.14, -0.04, (0.10, 0.10, 0.10)),
                                                   (0.005, 0.10, -0.04, (0.10, 0.10, 0.10)))):
        h_path = f"/World/Layout/clock_hand_{idx}_{hi}"
        hand = UsdGeom.Cube.Define(stage, h_path)
        hand.GetSizeAttr().Set(2.0)
        hxf = UsdGeom.XformCommonAPI(hand.GetPrim())
        hxf.SetScale(Gf.Vec3f(sx, 0.005, sz))
        hxf.SetTranslate(Gf.Vec3d(x, y + sy_off, z + sz / 2.0))
        bind_material(stage, hand, "M_PlasticMatte", color)
    return idx + 3


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


def _place_painted_aisle_code(stage, idx, x, y, text, rot_z=0,
                               tile_color=(0.92, 0.78, 0.10)):
    """Big colored floor tile with a black aisle code (e.g. 'A-1') stamped on top."""
    text = (text or "")[:4]
    n = max(1, len(text))
    cell = 0.18
    char_w = 3 * cell
    gap = 1 * cell
    tile_w = n * char_w + max(0, n - 1) * gap + 0.40
    tile_h = 5 * cell + 0.30
    path = f"/World/Layout/aisle_code_tile_{idx}"
    cube = UsdGeom.Cube.Define(stage, path)
    cube.GetSizeAttr().Set(2.0)
    xf = UsdGeom.XformCommonAPI(cube.GetPrim())
    xf.SetScale(Gf.Vec3f(tile_w / 2.0, tile_h / 2.0, 0.010))
    xf.SetTranslate(Gf.Vec3d(x, y, 0.012))
    xf.SetRotate(Gf.Vec3f(0, 0, rot_z),
                 UsdGeom.XformCommonAPI.RotationOrderXYZ)
    bind_material(stage, cube, "M_PaintedConcrete", tile_color)
    return _draw_floor_glyph(stage, idx + 1, text, x, y, cell_size=cell,
                              color=(0.06, 0.06, 0.06), z=0.018, rot_z=rot_z)


def _place_aisle_mirror(stage, idx, x, y, height=2.4):
    """Convex blind-corner safety mirror — black pole + circular mirror disc + bezel."""
    pole_path = f"/World/Layout/mirror_pole_{idx}"
    pole = UsdGeom.Cylinder.Define(stage, pole_path)
    pole.GetRadiusAttr().Set(0.04)
    pole.GetHeightAttr().Set(height)
    pole.GetAxisAttr().Set("Z")
    pxf = UsdGeom.XformCommonAPI(pole.GetPrim())
    pxf.SetTranslate(Gf.Vec3d(x, y, height / 2.0))
    bind_material(stage, pole, "M_AgedSteel", (0.10, 0.10, 0.10))
    disc_path = f"/World/Layout/mirror_disc_{idx}"
    disc = UsdGeom.Cylinder.Define(stage, disc_path)
    disc.GetRadiusAttr().Set(0.40)
    disc.GetHeightAttr().Set(0.05)
    disc.GetAxisAttr().Set("Y")
    dxf = UsdGeom.XformCommonAPI(disc.GetPrim())
    dxf.SetTranslate(Gf.Vec3d(x, y, height - 0.15))
    bind_material(stage, disc, "M_Glass", (0.78, 0.82, 0.85))
    bezel_path = f"/World/Layout/mirror_bezel_{idx}"
    bezel = UsdGeom.Cylinder.Define(stage, bezel_path)
    bezel.GetRadiusAttr().Set(0.42)
    bezel.GetHeightAttr().Set(0.04)
    bezel.GetAxisAttr().Set("Y")
    bxf = UsdGeom.XformCommonAPI(bezel.GetPrim())
    bxf.SetTranslate(Gf.Vec3d(x, y - 0.005, height - 0.15))
    bind_material(stage, bezel, "M_AgedSteel", (0.10, 0.10, 0.10))
    return idx + 3


def _place_zone_sign(stage, idx, x, y, z, text, band_color, rot_z=0):
    """Large suspended zone sign — white panel with a colored top band, the
    label rendered as black 3x5 glyphs on the +Y face, and two black cables
    going up to the ceiling."""
    text = (text or "")[:8]
    n = max(1, len(text))
    cell = 0.20
    char_w = 3 * cell
    gap = 1 * cell
    glyph_w = n * char_w + max(0, n - 1) * gap
    panel_w = glyph_w + 0.6
    panel_h = 5 * cell + 0.4
    body_path = f"/World/Layout/zonesign_body_{idx}"
    body = UsdGeom.Cube.Define(stage, body_path)
    body.GetSizeAttr().Set(2.0)
    bxf = UsdGeom.XformCommonAPI(body.GetPrim())
    bxf.SetScale(Gf.Vec3f(panel_w / 2.0, 0.04, panel_h / 2.0))
    bxf.SetTranslate(Gf.Vec3d(x, y, z))
    bxf.SetRotate(Gf.Vec3f(0, 0, rot_z),
                  UsdGeom.XformCommonAPI.RotationOrderXYZ)
    bind_material(stage, body, "M_PlasticMatte", (0.96, 0.96, 0.94))
    band_path = f"/World/Layout/zonesign_band_{idx}"
    band = UsdGeom.Cube.Define(stage, band_path)
    band.GetSizeAttr().Set(2.0)
    bndxf = UsdGeom.XformCommonAPI(band.GetPrim())
    bndxf.SetScale(Gf.Vec3f(panel_w / 2.0, 0.045, 0.10))
    bndxf.SetTranslate(Gf.Vec3d(x, y, z + panel_h / 2.0 - 0.10))
    bndxf.SetRotate(Gf.Vec3f(0, 0, rot_z),
                    UsdGeom.XformCommonAPI.RotationOrderXYZ)
    bind_material(stage, band, "M_PlasticMatte", band_color)
    for sgn_i, sgn in enumerate((-1, 1)):
        cable_path = f"/World/Layout/zonesign_cable_{idx}_{sgn_i}"
        cable = UsdGeom.Cylinder.Define(stage, cable_path)
        cable.GetRadiusAttr().Set(0.012)
        cable.GetHeightAttr().Set(1.0)
        cable.GetAxisAttr().Set("Z")
        cxf = UsdGeom.XformCommonAPI(cable.GetPrim())
        cxf.SetTranslate(Gf.Vec3d(x + sgn * panel_w * 0.4,
                                   y, z + panel_h / 2.0 + 0.5))
        bind_material(stage, cable, "M_Rubber", (0.10, 0.10, 0.10))
    chars = list(text.upper())
    glyph_y = y + 0.05
    glyph_x_start = x - glyph_w / 2.0 + cell / 2.0
    glyph_z_top = z + panel_h / 2.0 - 0.30
    placed = 0
    for ci, ch in enumerate(chars):
        bits = _GLYPH_3x5.get(ch, _GLYPH_3x5[" "])
        for r in range(5):
            for c in range(3):
                if bits[r * 3 + c] != "1":
                    continue
                gx = glyph_x_start + (ci * (3 + 1) + c) * cell
                gz = glyph_z_top - (r + 1) * cell
                path = f"/World/Layout/zonesign_g_{idx}_{placed}"
                cube = UsdGeom.Cube.Define(stage, path)
                cube.GetSizeAttr().Set(2.0)
                gxf = UsdGeom.XformCommonAPI(cube.GetPrim())
                gxf.SetScale(Gf.Vec3f(cell / 2.0 * 0.85, 0.02,
                                       cell / 2.0 * 0.85))
                gxf.SetTranslate(Gf.Vec3d(gx, glyph_y, gz))
                bind_material(stage, cube, "M_Rubber", (0.06, 0.06, 0.06))
                placed += 1
    return idx + 4 + placed


def _place_conveyor_run(stage, idx, x_start, y_start, x_end, y_end,
                         height=0.80):
    """Straight roller conveyor between two endpoints — deck + rails + rollers + legs."""
    dx = x_end - x_start
    dy = y_end - y_start
    length = math.sqrt(dx * dx + dy * dy)
    if length < 1.0:
        return idx
    rot_z = math.degrees(math.atan2(dy, dx))
    cx = (x_start + x_end) / 2.0
    cy = (y_start + y_end) / 2.0
    width = 0.55
    deck_path = f"/World/Layout/conv_deck_{idx}"
    deck = UsdGeom.Cube.Define(stage, deck_path)
    deck.GetSizeAttr().Set(2.0)
    dxf = UsdGeom.XformCommonAPI(deck.GetPrim())
    dxf.SetScale(Gf.Vec3f(length / 2.0, width / 2.0, 0.04))
    dxf.SetTranslate(Gf.Vec3d(cx, cy, height))
    dxf.SetRotate(Gf.Vec3f(0, 0, rot_z),
                  UsdGeom.XformCommonAPI.RotationOrderXYZ)
    bind_material(stage, deck, "M_AgedSteel", (0.30, 0.30, 0.32))
    ang = math.radians(rot_z)
    cos_a, sin_a = math.cos(ang), math.sin(ang)
    for sgn_i, sgn in enumerate((-1, 1)):
        local_y = sgn * (width / 2.0 + 0.02)
        rx = cx - local_y * sin_a
        ry = cy + local_y * cos_a
        rail_path = f"/World/Layout/conv_rail_{idx}_{sgn_i}"
        rail = UsdGeom.Cube.Define(stage, rail_path)
        rail.GetSizeAttr().Set(2.0)
        rxf = UsdGeom.XformCommonAPI(rail.GetPrim())
        rxf.SetScale(Gf.Vec3f(length / 2.0, 0.025, 0.08))
        rxf.SetTranslate(Gf.Vec3d(rx, ry, height + 0.08))
        rxf.SetRotate(Gf.Vec3f(0, 0, rot_z),
                      UsdGeom.XformCommonAPI.RotationOrderXYZ)
        bind_material(stage, rail, "M_AgedSteel", (0.22, 0.22, 0.24))
    n_rollers = max(4, int(length / 0.18))
    for k in range(n_rollers):
        t = (k + 0.5) / n_rollers
        local_along = -length / 2.0 + t * length
        rx = cx + local_along * cos_a
        ry = cy + local_along * sin_a
        roller_path = f"/World/Layout/conv_roller_{idx}_{k}"
        roller = UsdGeom.Cylinder.Define(stage, roller_path)
        roller.GetRadiusAttr().Set(0.04)
        roller.GetHeightAttr().Set(width - 0.05)
        roller.GetAxisAttr().Set("Y")
        rxf = UsdGeom.XformCommonAPI(roller.GetPrim())
        rxf.SetTranslate(Gf.Vec3d(rx, ry, height + 0.05))
        rxf.SetRotate(Gf.Vec3f(0, 0, rot_z),
                      UsdGeom.XformCommonAPI.RotationOrderXYZ)
        bind_material(stage, roller, "M_AgedSteel", (0.55, 0.55, 0.58))
    n_legs = max(2, int(length / 1.5))
    for L in range(n_legs):
        t = L / max(1, n_legs - 1) if n_legs > 1 else 0.5
        local_along = -length / 2.0 + t * length
        lx = cx + local_along * cos_a
        ly = cy + local_along * sin_a
        for sgn_i, sgn in enumerate((-1, 1)):
            local_y = sgn * width / 2.0
            wx = lx - local_y * sin_a
            wy = ly + local_y * cos_a
            leg_path = f"/World/Layout/conv_leg_{idx}_{L}_{sgn_i}"
            leg = UsdGeom.Cube.Define(stage, leg_path)
            leg.GetSizeAttr().Set(2.0)
            lxf = UsdGeom.XformCommonAPI(leg.GetPrim())
            lxf.SetScale(Gf.Vec3f(0.04, 0.04, height / 2.0))
            lxf.SetTranslate(Gf.Vec3d(wx, wy, height / 2.0))
            bind_material(stage, leg, "M_AgedSteel", (0.20, 0.20, 0.22))
    return idx + 1


def _place_office_enclosure(stage, idx, cx, cy, width=3.6, depth=2.6,
                             height=2.2, rot_z=0):
    """Three-wall partitioned office: solid lower band + glass upper band on
    three sides, the +Y side open to the warehouse floor. Inside: floor tile,
    desk against the back wall, monitor, chair, coffee mug."""
    wall_color = (0.85, 0.86, 0.86)
    glass_color = (0.55, 0.65, 0.72)
    ang = math.radians(rot_z)
    cos_a, sin_a = math.cos(ang), math.sin(ang)
    walls = [
        (-width / 2.0, 0.0, 0.06, depth),
        ( width / 2.0, 0.0, 0.06, depth),
        ( 0.0, -depth / 2.0, width, 0.06),
    ]
    for wi, (lx, ly, sx, sy) in enumerate(walls):
        wx = cx + lx * cos_a - ly * sin_a
        wy = cy + lx * sin_a + ly * cos_a
        path = f"/World/Layout/office_wall_{idx}_{wi}"
        cube = UsdGeom.Cube.Define(stage, path)
        cube.GetSizeAttr().Set(2.0)
        xf = UsdGeom.XformCommonAPI(cube.GetPrim())
        xf.SetScale(Gf.Vec3f(sx / 2.0, sy / 2.0, 0.6))
        xf.SetTranslate(Gf.Vec3d(wx, wy, 0.6))
        xf.SetRotate(Gf.Vec3f(0, 0, rot_z),
                     UsdGeom.XformCommonAPI.RotationOrderXYZ)
        bind_material(stage, cube, "M_PaintedWall", wall_color)
        if not cube.GetPrim().HasAPI(UsdPhysics.CollisionAPI):
            UsdPhysics.CollisionAPI.Apply(cube.GetPrim())
        glass_path = f"/World/Layout/office_glass_{idx}_{wi}"
        glass = UsdGeom.Cube.Define(stage, glass_path)
        glass.GetSizeAttr().Set(2.0)
        gxf = UsdGeom.XformCommonAPI(glass.GetPrim())
        gxf.SetScale(Gf.Vec3f(sx / 2.0 * 0.95, sy / 2.0 * 0.95,
                               (height - 1.2) / 2.0))
        gxf.SetTranslate(Gf.Vec3d(wx, wy, 1.2 + (height - 1.2) / 2.0))
        gxf.SetRotate(Gf.Vec3f(0, 0, rot_z),
                      UsdGeom.XformCommonAPI.RotationOrderXYZ)
        bind_material(stage, glass, "M_Glass", glass_color)
    floor_path = f"/World/Layout/office_floor_{idx}"
    floor = UsdGeom.Cube.Define(stage, floor_path)
    floor.GetSizeAttr().Set(2.0)
    fxf = UsdGeom.XformCommonAPI(floor.GetPrim())
    fxf.SetScale(Gf.Vec3f(width / 2.0 - 0.05, depth / 2.0 - 0.05, 0.012))
    fxf.SetTranslate(Gf.Vec3d(cx, cy, 0.014))
    fxf.SetRotate(Gf.Vec3f(0, 0, rot_z),
                  UsdGeom.XformCommonAPI.RotationOrderXYZ)
    bind_material(stage, floor, "M_Wood", (0.55, 0.45, 0.35))

    def _local_to_world(lx, ly):
        return cx + lx * cos_a - ly * sin_a, cy + lx * sin_a + ly * cos_a

    desk_x, desk_y = _local_to_world(0.0, -depth / 2.0 + 0.5)
    desk_path = f"/World/Layout/office_desk_{idx}"
    desk = UsdGeom.Cube.Define(stage, desk_path)
    desk.GetSizeAttr().Set(2.0)
    dexf = UsdGeom.XformCommonAPI(desk.GetPrim())
    dexf.SetScale(Gf.Vec3f(0.65, 0.30, 0.04))
    dexf.SetTranslate(Gf.Vec3d(desk_x, desk_y, 0.74))
    dexf.SetRotate(Gf.Vec3f(0, 0, rot_z),
                   UsdGeom.XformCommonAPI.RotationOrderXYZ)
    bind_material(stage, desk, "M_Wood", (0.35, 0.28, 0.20))

    mon_x, mon_y = _local_to_world(0.0, -depth / 2.0 + 0.4)
    mon_path = f"/World/Layout/office_monitor_{idx}"
    mon = UsdGeom.Cube.Define(stage, mon_path)
    mon.GetSizeAttr().Set(2.0)
    moxf = UsdGeom.XformCommonAPI(mon.GetPrim())
    moxf.SetScale(Gf.Vec3f(0.30, 0.04, 0.18))
    moxf.SetTranslate(Gf.Vec3d(mon_x, mon_y, 1.05))
    moxf.SetRotate(Gf.Vec3f(0, 0, rot_z),
                   UsdGeom.XformCommonAPI.RotationOrderXYZ)
    bind_material(stage, mon, "M_PlasticGloss", (0.08, 0.08, 0.10))

    ch_x, ch_y = _local_to_world(0.0, -depth / 2.0 + 1.2)
    chair_path = f"/World/Layout/office_chair_{idx}"
    chair = UsdGeom.Cylinder.Define(stage, chair_path)
    chair.GetRadiusAttr().Set(0.22)
    chair.GetHeightAttr().Set(0.50)
    chair.GetAxisAttr().Set("Z")
    chxf = UsdGeom.XformCommonAPI(chair.GetPrim())
    chxf.SetTranslate(Gf.Vec3d(ch_x, ch_y, 0.25))
    bind_material(stage, chair, "M_PlasticMatte", (0.15, 0.15, 0.18))

    mug_x, mug_y = _local_to_world(0.4, -depth / 2.0 + 0.4)
    mug_path = f"/World/Layout/office_mug_{idx}"
    mug = UsdGeom.Cylinder.Define(stage, mug_path)
    mug.GetRadiusAttr().Set(0.045)
    mug.GetHeightAttr().Set(0.10)
    mug.GetAxisAttr().Set("Z")
    muxf = UsdGeom.XformCommonAPI(mug.GetPrim())
    muxf.SetTranslate(Gf.Vec3d(mug_x, mug_y, 0.84))
    bind_material(stage, mug, "M_PlasticGloss", (0.92, 0.92, 0.88))
    return idx + 12


def _place_pallet_jack(stage, idx, x, y, rot_z=0, color=(0.85, 0.20, 0.20)):
    """Manual pallet jack — two parallel fork tines (along local +X), pivot
    block at the base of the handle, angled tubular handle with a transverse
    grip, and four small wheels."""
    ang = math.radians(rot_z)
    cos_a, sin_a = math.cos(ang), math.sin(ang)

    def _to_world(lx, ly):
        return x + lx * cos_a - ly * sin_a, y + lx * sin_a + ly * cos_a

    fork_len = 1.10
    fork_w = 0.10
    fork_gap = 0.30
    for sgn_i, sgn in enumerate((-1, 1)):
        wx, wy = _to_world(fork_len / 2.0, sgn * fork_gap / 2.0)
        path = f"/World/Layout/jack_fork_{idx}_{sgn_i}"
        cube = UsdGeom.Cube.Define(stage, path)
        cube.GetSizeAttr().Set(2.0)
        xf = UsdGeom.XformCommonAPI(cube.GetPrim())
        xf.SetScale(Gf.Vec3f(fork_len / 2.0, fork_w / 2.0, 0.04))
        xf.SetTranslate(Gf.Vec3d(wx, wy, 0.07))
        xf.SetRotate(Gf.Vec3f(0, 0, rot_z),
                     UsdGeom.XformCommonAPI.RotationOrderXYZ)
        bind_material(stage, cube, "M_PlasticGloss", color)
    px, py = _to_world(0.05, 0)
    pivot_path = f"/World/Layout/jack_pivot_{idx}"
    pivot = UsdGeom.Cube.Define(stage, pivot_path)
    pivot.GetSizeAttr().Set(2.0)
    pxf = UsdGeom.XformCommonAPI(pivot.GetPrim())
    pxf.SetScale(Gf.Vec3f(0.10, 0.30, 0.18))
    pxf.SetTranslate(Gf.Vec3d(px, py, 0.18))
    pxf.SetRotate(Gf.Vec3f(0, 0, rot_z),
                  UsdGeom.XformCommonAPI.RotationOrderXYZ)
    bind_material(stage, pivot, "M_PlasticGloss", color)
    handle_len = 1.0
    tilt = 25
    hx, hy = _to_world(-0.30, 0)
    handle_path = f"/World/Layout/jack_handle_{idx}"
    handle = UsdGeom.Cylinder.Define(stage, handle_path)
    handle.GetRadiusAttr().Set(0.025)
    handle.GetHeightAttr().Set(handle_len)
    handle.GetAxisAttr().Set("Z")
    hxf = UsdGeom.XformCommonAPI(handle.GetPrim())
    hxf.SetTranslate(Gf.Vec3d(hx, hy, 0.55))
    hxf.SetRotate(Gf.Vec3f(0, tilt, rot_z),
                  UsdGeom.XformCommonAPI.RotationOrderXYZ)
    bind_material(stage, handle, "M_AgedSteel", (0.20, 0.20, 0.22))
    grip_local_x = -0.30 - handle_len * math.sin(math.radians(tilt))
    grip_z = 0.55 + handle_len / 2.0 * math.cos(math.radians(tilt))
    gx, gy = _to_world(grip_local_x, 0)
    grip_path = f"/World/Layout/jack_grip_{idx}"
    grip = UsdGeom.Cylinder.Define(stage, grip_path)
    grip.GetRadiusAttr().Set(0.04)
    grip.GetHeightAttr().Set(0.20)
    grip.GetAxisAttr().Set("Y")
    grxf = UsdGeom.XformCommonAPI(grip.GetPrim())
    grxf.SetTranslate(Gf.Vec3d(gx, gy, grip_z))
    grxf.SetRotate(Gf.Vec3f(0, 0, rot_z),
                   UsdGeom.XformCommonAPI.RotationOrderXYZ)
    bind_material(stage, grip, "M_Rubber", (0.10, 0.10, 0.10))
    for fi, (lx, ly) in enumerate(((fork_len - 0.05, fork_gap / 2.0),
                                    (fork_len - 0.05, -fork_gap / 2.0),
                                    (0.05, fork_gap / 2.0 + 0.05),
                                    (0.05, -fork_gap / 2.0 - 0.05))):
        wx, wy = _to_world(lx, ly)
        wheel_path = f"/World/Layout/jack_wheel_{idx}_{fi}"
        w = UsdGeom.Cylinder.Define(stage, wheel_path)
        w.GetRadiusAttr().Set(0.05)
        w.GetHeightAttr().Set(0.04)
        w.GetAxisAttr().Set("Y")
        wxf = UsdGeom.XformCommonAPI(w.GetPrim())
        wxf.SetTranslate(Gf.Vec3d(wx, wy, 0.05))
        wxf.SetRotate(Gf.Vec3f(0, 0, rot_z),
                      UsdGeom.XformCommonAPI.RotationOrderXYZ)
        bind_material(stage, w, "M_Rubber", (0.10, 0.10, 0.10))
    return idx + 9


def _place_wall_windows(stage, idx, x_const, y_lo, y_hi, n_windows=4,
                         z_center=2.4, w=1.4, h=1.0,
                         color=(0.55, 0.70, 0.85)):
    """Distribute n_windows light-blue glazed panels along a wall (constant X)
    between y_lo and y_hi at vertical center z_center. Each window: dark frame
    + glass + a thin vertical mullion proud of the glass."""
    if y_hi - y_lo < 1.5 or n_windows < 1:
        return idx
    span = y_hi - y_lo
    for k in range(n_windows):
        t = (k + 0.5) / n_windows
        wy = y_lo + t * span
        f_path = f"/World/Layout/window_frame_{idx}_{k}"
        f = UsdGeom.Cube.Define(stage, f_path)
        f.GetSizeAttr().Set(2.0)
        fxf = UsdGeom.XformCommonAPI(f.GetPrim())
        fxf.SetScale(Gf.Vec3f(0.04, w / 2.0 + 0.05, h / 2.0 + 0.05))
        fxf.SetTranslate(Gf.Vec3d(x_const, wy, z_center))
        bind_material(stage, f, "M_AgedSteel", (0.20, 0.22, 0.24))
        g_path = f"/World/Layout/window_glass_{idx}_{k}"
        g = UsdGeom.Cube.Define(stage, g_path)
        g.GetSizeAttr().Set(2.0)
        gxf = UsdGeom.XformCommonAPI(g.GetPrim())
        gxf.SetScale(Gf.Vec3f(0.03, w / 2.0, h / 2.0))
        gxf.SetTranslate(Gf.Vec3d(x_const + 0.005, wy, z_center))
        bind_material(stage, g, "M_Glass", color)
        m_path = f"/World/Layout/window_mull_{idx}_{k}"
        m = UsdGeom.Cube.Define(stage, m_path)
        m.GetSizeAttr().Set(2.0)
        mxf = UsdGeom.XformCommonAPI(m.GetPrim())
        mxf.SetScale(Gf.Vec3f(0.035, 0.025, h / 2.0))
        mxf.SetTranslate(Gf.Vec3d(x_const + 0.008, wy, z_center))
        bind_material(stage, m, "M_AgedSteel", (0.20, 0.22, 0.24))
    return idx + 3 * n_windows


def _place_mezzanine(stage, idx, x_const, y_lo, y_hi,
                      depth=2.5, height=3.4, side=-1):
    """Mezzanine deck along a wall at constant X spanning y_lo..y_hi.
    side=-1 → deck extends in -X (wall on +X side); side=+1 → deck in +X.
    Deck + column legs every ~3m + top rail + mid rail + toe board on the
    open edge + a stair stub at the y_lo end. Deck and legs carry CollisionAPI."""
    span_y = y_hi - y_lo
    if span_y < 3.0:
        return idx
    deck_x = x_const + side * (depth / 2.0)
    deck_y = (y_lo + y_hi) / 2.0
    deck_path = f"/World/Layout/mezz_deck_{idx}"
    deck = UsdGeom.Cube.Define(stage, deck_path)
    deck.GetSizeAttr().Set(2.0)
    dxf = UsdGeom.XformCommonAPI(deck.GetPrim())
    dxf.SetScale(Gf.Vec3f(depth / 2.0, span_y / 2.0, 0.04))
    dxf.SetTranslate(Gf.Vec3d(deck_x, deck_y, height))
    bind_material(stage, deck, "M_AgedSteel", (0.40, 0.42, 0.45))
    if not deck.GetPrim().HasAPI(UsdPhysics.CollisionAPI):
        UsdPhysics.CollisionAPI.Apply(deck.GetPrim())
    n_legs = max(2, int(span_y / 3.0) + 1)
    leg_outer_x = x_const + side * (depth - 0.15)
    for L in range(n_legs):
        t = L / max(1, n_legs - 1)
        ly = y_lo + t * span_y
        leg_path = f"/World/Layout/mezz_leg_{idx}_{L}"
        leg = UsdGeom.Cylinder.Define(stage, leg_path)
        leg.GetRadiusAttr().Set(0.08)
        leg.GetHeightAttr().Set(height)
        leg.GetAxisAttr().Set("Z")
        lxf = UsdGeom.XformCommonAPI(leg.GetPrim())
        lxf.SetTranslate(Gf.Vec3d(leg_outer_x, ly, height / 2.0))
        bind_material(stage, leg, "M_AgedSteel", (0.30, 0.32, 0.35))
        if not leg.GetPrim().HasAPI(UsdPhysics.CollisionAPI):
            UsdPhysics.CollisionAPI.Apply(leg.GetPrim())
    rail_x = leg_outer_x
    for ri, rz in enumerate((1.05, 0.55)):
        r_path = f"/World/Layout/mezz_rail_{idx}_{ri}"
        r = UsdGeom.Cube.Define(stage, r_path)
        r.GetSizeAttr().Set(2.0)
        rxf = UsdGeom.XformCommonAPI(r.GetPrim())
        rxf.SetScale(Gf.Vec3f(0.025, span_y / 2.0, 0.025))
        rxf.SetTranslate(Gf.Vec3d(rail_x, deck_y, height + rz))
        bind_material(stage, r, "M_YellowSafetyPaint", (0.95, 0.78, 0.10))
    toe_path = f"/World/Layout/mezz_toe_{idx}"
    toe = UsdGeom.Cube.Define(stage, toe_path)
    toe.GetSizeAttr().Set(2.0)
    txf = UsdGeom.XformCommonAPI(toe.GetPrim())
    txf.SetScale(Gf.Vec3f(0.02, span_y / 2.0, 0.10))
    txf.SetTranslate(Gf.Vec3d(rail_x, deck_y, height + 0.10))
    bind_material(stage, toe, "M_AgedSteel", (0.30, 0.30, 0.32))
    stair_run = 1.8
    stair_y = y_lo - stair_run / 2.0
    stair_x = leg_outer_x
    stair_path = f"/World/Layout/mezz_stair_{idx}"
    stair = UsdGeom.Cube.Define(stage, stair_path)
    stair.GetSizeAttr().Set(2.0)
    sxf = UsdGeom.XformCommonAPI(stair.GetPrim())
    sxf.SetScale(Gf.Vec3f(0.50, stair_run / 2.0, 0.05))
    sxf.SetTranslate(Gf.Vec3d(stair_x, stair_y, height / 2.0))
    sxf.SetRotate(Gf.Vec3f(math.degrees(math.atan2(height, stair_run)),
                            0, 0),
                  UsdGeom.XformCommonAPI.RotationOrderXYZ)
    bind_material(stage, stair, "M_AgedSteel", (0.40, 0.42, 0.45))
    return idx + 5 + n_legs


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


def _place_wrapping_station(stage, idx, x, y, rot_z=0):
    """Stretch-wrap machine: gray turntable disc, side-mounted base block,
    yellow vertical mast, light-blue film roll on a carriage halfway up."""
    ang = math.radians(rot_z)
    cos_a, sin_a = math.cos(ang), math.sin(ang)
    tt_path = f"/World/Layout/wrap_turntable_{idx}"
    tt = UsdGeom.Cylinder.Define(stage, tt_path)
    tt.GetRadiusAttr().Set(0.70)
    tt.GetHeightAttr().Set(0.10)
    tt.GetAxisAttr().Set("Z")
    txf = UsdGeom.XformCommonAPI(tt.GetPrim())
    txf.SetTranslate(Gf.Vec3d(x, y, 0.05))
    bind_material(stage, tt, "M_AgedSteel", (0.30, 0.32, 0.35))
    base_local_x = 1.10
    base_x = x + base_local_x * cos_a
    base_y = y + base_local_x * sin_a
    base_path = f"/World/Layout/wrap_base_{idx}"
    base = UsdGeom.Cube.Define(stage, base_path)
    base.GetSizeAttr().Set(2.0)
    bxf = UsdGeom.XformCommonAPI(base.GetPrim())
    bxf.SetScale(Gf.Vec3f(0.18, 0.30, 0.10))
    bxf.SetTranslate(Gf.Vec3d(base_x, base_y, 0.10))
    bxf.SetRotate(Gf.Vec3f(0, 0, rot_z),
                  UsdGeom.XformCommonAPI.RotationOrderXYZ)
    bind_material(stage, base, "M_AgedSteel", (0.25, 0.27, 0.30))
    mast_path = f"/World/Layout/wrap_mast_{idx}"
    mast = UsdGeom.Cube.Define(stage, mast_path)
    mast.GetSizeAttr().Set(2.0)
    mxf = UsdGeom.XformCommonAPI(mast.GetPrim())
    mxf.SetScale(Gf.Vec3f(0.06, 0.06, 1.00))
    mxf.SetTranslate(Gf.Vec3d(base_x, base_y, 1.00))
    mxf.SetRotate(Gf.Vec3f(0, 0, rot_z),
                  UsdGeom.XformCommonAPI.RotationOrderXYZ)
    bind_material(stage, mast, "M_YellowSafetyPaint", (0.95, 0.78, 0.10))
    roll_local_x = base_local_x - 0.20
    roll_x = x + roll_local_x * cos_a
    roll_y = y + roll_local_x * sin_a
    roll_path = f"/World/Layout/wrap_roll_{idx}"
    roll = UsdGeom.Cylinder.Define(stage, roll_path)
    roll.GetRadiusAttr().Set(0.10)
    roll.GetHeightAttr().Set(0.50)
    roll.GetAxisAttr().Set("Z")
    rxf = UsdGeom.XformCommonAPI(roll.GetPrim())
    rxf.SetTranslate(Gf.Vec3d(roll_x, roll_y, 0.80))
    bind_material(stage, roll, "M_StretchFilm", (0.78, 0.85, 0.92))
    return idx + 4


def _place_wrapped_pallet(stage, idx, x, y, asset_library, rot_z=0):
    """Pallet (real asset if available) + light-blue translucent-look cargo
    block with two horizontal seam bands wrapping it as stretch-film."""
    if "pallet" in asset_library:
        idx = _place("pallet", x, y, 0, rot_z, asset_library, stage, idx)
    block_path = f"/World/Layout/wrapped_cargo_{idx}"
    block = UsdGeom.Cube.Define(stage, block_path)
    block.GetSizeAttr().Set(2.0)
    blxf = UsdGeom.XformCommonAPI(block.GetPrim())
    blxf.SetScale(Gf.Vec3f(0.50, 0.40, 0.50))
    blxf.SetTranslate(Gf.Vec3d(x, y, 0.65))
    blxf.SetRotate(Gf.Vec3f(0, 0, rot_z),
                   UsdGeom.XformCommonAPI.RotationOrderXYZ)
    bind_material(stage, block, "M_StretchFilm", (0.78, 0.86, 0.94))
    ang = math.radians(rot_z)
    cos_a, sin_a = math.cos(ang), math.sin(ang)
    seams_placed = 0
    for bi, frac in enumerate((0.30, 0.70)):
        bz = 0.15 + frac * 1.0
        for face_i, (fx, fy) in enumerate(((1, 0), (-1, 0), (0, 1), (0, -1))):
            local_x = fx * 0.51
            local_y = fy * 0.41
            wx = x + local_x * cos_a - local_y * sin_a
            wy = y + local_x * sin_a + local_y * cos_a
            seam_path = f"/World/Layout/wrap_seam_{idx}_{bi}_{face_i}"
            seam = UsdGeom.Cube.Define(stage, seam_path)
            seam.GetSizeAttr().Set(2.0)
            sxf = UsdGeom.XformCommonAPI(seam.GetPrim())
            if abs(fx) > 0.5:
                sxf.SetScale(Gf.Vec3f(0.005, 0.40, 0.04))
            else:
                sxf.SetScale(Gf.Vec3f(0.50, 0.005, 0.04))
            sxf.SetTranslate(Gf.Vec3d(wx, wy, bz))
            sxf.SetRotate(Gf.Vec3f(0, 0, rot_z),
                          UsdGeom.XformCommonAPI.RotationOrderXYZ)
            bind_material(stage, seam, "M_StretchFilm", (0.60, 0.72, 0.82))
            seams_placed += 1
    return idx + 1 + seams_placed


def _place_hand_truck(stage, idx, x, y, rot_z=0, color=(0.18, 0.18, 0.20)):
    """Two-wheel hand truck (dolly): vertical back-plate, L-shaped foot at the
    base, single tubular handle bar across the top, two rubber wheels on a
    transverse axle. Smaller than a pallet jack; reads as 'parked against
    rack-end'."""
    ang = math.radians(rot_z)
    cos_a, sin_a = math.cos(ang), math.sin(ang)

    def _to_world(lx, ly):
        return x + lx * cos_a - ly * sin_a, y + lx * sin_a + ly * cos_a

    # Back plate — thin upright slab, ~1.1m tall, ~0.45m wide.
    bx, by = _to_world(0, 0)
    plate_path = f"/World/Layout/handtruck_plate_{idx}"
    plate = UsdGeom.Cube.Define(stage, plate_path)
    plate.GetSizeAttr().Set(2.0)
    pxf = UsdGeom.XformCommonAPI(plate.GetPrim())
    pxf.SetScale(Gf.Vec3f(0.025, 0.225, 0.55))
    pxf.SetTranslate(Gf.Vec3d(bx, by, 0.60))
    pxf.SetRotate(Gf.Vec3f(0, 0, rot_z),
                  UsdGeom.XformCommonAPI.RotationOrderXYZ)
    bind_material(stage, plate, "M_PlasticMatte", color)

    # L-foot — flat tongue extending forward at floor level.
    fx_local, fy_local = 0.20, 0.0
    fwx, fwy = _to_world(fx_local, fy_local)
    foot_path = f"/World/Layout/handtruck_foot_{idx}"
    foot = UsdGeom.Cube.Define(stage, foot_path)
    foot.GetSizeAttr().Set(2.0)
    fxf = UsdGeom.XformCommonAPI(foot.GetPrim())
    fxf.SetScale(Gf.Vec3f(0.20, 0.21, 0.015))
    fxf.SetTranslate(Gf.Vec3d(fwx, fwy, 0.025))
    fxf.SetRotate(Gf.Vec3f(0, 0, rot_z),
                  UsdGeom.XformCommonAPI.RotationOrderXYZ)
    bind_material(stage, foot, "M_PlasticMatte", color)

    # Handle bar — single horizontal cylinder across the top of the plate.
    hx, hy = _to_world(0, 0)
    handle_path = f"/World/Layout/handtruck_handle_{idx}"
    handle = UsdGeom.Cylinder.Define(stage, handle_path)
    handle.GetRadiusAttr().Set(0.025)
    handle.GetHeightAttr().Set(0.46)
    handle.GetAxisAttr().Set("Y")
    hxf = UsdGeom.XformCommonAPI(handle.GetPrim())
    hxf.SetTranslate(Gf.Vec3d(hx, hy, 1.18))
    hxf.SetRotate(Gf.Vec3f(0, 0, rot_z),
                  UsdGeom.XformCommonAPI.RotationOrderXYZ)
    bind_material(stage, handle, "M_AgedSteel", (0.10, 0.10, 0.10))

    # Two wheels at the base of the plate, on a transverse axle.
    for wi, sgn in enumerate((-1, 1)):
        wlx, wly = 0.02, sgn * 0.24
        wwx, wwy = _to_world(wlx, wly)
        wheel_path = f"/World/Layout/handtruck_wheel_{idx}_{wi}"
        w = UsdGeom.Cylinder.Define(stage, wheel_path)
        w.GetRadiusAttr().Set(0.10)
        w.GetHeightAttr().Set(0.04)
        w.GetAxisAttr().Set("Y")
        wxf = UsdGeom.XformCommonAPI(w.GetPrim())
        wxf.SetTranslate(Gf.Vec3d(wwx, wwy, 0.10))
        wxf.SetRotate(Gf.Vec3f(0, 0, rot_z),
                      UsdGeom.XformCommonAPI.RotationOrderXYZ)
        bind_material(stage, w, "M_Rubber", (0.08, 0.08, 0.08))

    return idx + 1
