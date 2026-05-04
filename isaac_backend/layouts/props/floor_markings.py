"""Floor markings: arrows, painted codes, hazard hatches, parking, stains."""

import math
import random

from pxr import UsdGeom, Gf, UsdPhysics

from isaac_backend.layouts.geometry import DEFAULT_CEILING_Z
from isaac_backend.layouts.placement import _place, _draw_floor_glyph, _GLYPH_3x5
from isaac_backend.layouts.materials import bind_material


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



def _place_tire_scuff(stage, idx, x, y, length, rot_z=0):
    """Broken stripe down an aisle centerline — forklift tire residue. Drawn
    as a chain of short dark-brown segments so it reads as worn rubber,
    not a solid line of paint."""
    # Darker than before — earlier (0.22, 0.16, 0.12) was washed out by
    # ceiling-bank flood and read as faint smudges from camera distance.
    color = (0.10, 0.07, 0.05)
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
        # Wider strip (0.14 vs 0.10) reads better at typical camera height.
        sxf.SetScale(Gf.Vec3f(seg_len / 2.0, 0.14, 0.006))
        sxf.SetTranslate(Gf.Vec3d(wx, wy, 0.022))
        sxf.SetRotate(Gf.Vec3f(0, 0, rot_z), UsdGeom.XformCommonAPI.RotationOrderXYZ)
        bind_material(stage, cube, "M_PaintedConcrete", color)
    return idx + 1



def _place_oil_stain(stage, idx, x, y, radius=0.55):
    """Irregular puddle — cluster of flat near-black blobs with a dark sheen."""
    # Near-black so the stain reads as oil at distance instead of a faint
    # grey patch. Previous (0.12, 0.10, 0.08) blended into concrete.
    base_color = (0.04, 0.03, 0.02)
    for b in range(random.randint(7, 11)):
        ang = random.uniform(0, 2 * math.pi)
        r = random.uniform(0.0, radius)
        bx = x + r * math.cos(ang)
        by = y + r * math.sin(ang)
        sx = random.uniform(0.18, 0.36)
        sy = random.uniform(0.18, 0.36)
        path = f"/World/Layout/oil_blob_{idx}_{b}"
        cube = UsdGeom.Cube.Define(stage, path)
        cube.GetSizeAttr().Set(2.0)
        oxf = UsdGeom.XformCommonAPI(cube.GetPrim())
        oxf.SetScale(Gf.Vec3f(sx, sy, 0.005))
        oxf.SetTranslate(Gf.Vec3d(bx, by, 0.024))
        oxf.SetRotate(Gf.Vec3f(0, 0, random.uniform(0, 90)),
                      UsdGeom.XformCommonAPI.RotationOrderXYZ)
        bind_material(stage, cube, "M_OilFilm", base_color)
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


