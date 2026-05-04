"""Wall fixtures: signs, extinguishers, junction boxes, mirrors, panel details."""

import math
import random

from pxr import UsdGeom, Gf, UsdPhysics

from isaac_backend.layouts.geometry import DEFAULT_CEILING_Z
from isaac_backend.layouts.placement import _place, _draw_floor_glyph, _GLYPH_3x5
from isaac_backend.layouts.materials import bind_material


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



def _place_wall_panel_seam(stage, idx, x, y, axis="x", height=4.5,
                           color=(0.18, 0.16, 0.14)):
    """Thin vertical dark strip flush with a wall — reads as a panel seam
    between prefabricated wall sections. axis='x' for walls running along
    X (perpendicular to Y), axis='y' for walls running along Y."""
    path = f"/World/Layout/wall_seam_{idx}"
    cube = UsdGeom.Cube.Define(stage, path)
    cube.GetSizeAttr().Set(2.0)
    sxf = UsdGeom.XformCommonAPI(cube.GetPrim())
    if axis == "x":
        # Wall running along X — seam is thin in X, tall in Z, depth in Y.
        sxf.SetScale(Gf.Vec3f(0.025, 0.005, height / 2.0))
    else:
        # Wall running along Y — seam is thin in Y.
        sxf.SetScale(Gf.Vec3f(0.005, 0.025, height / 2.0))
    sxf.SetTranslate(Gf.Vec3d(x, y, height / 2.0 + 0.02))
    bind_material(stage, cube, "M_PaintedWall", color)
    return idx + 1



def _place_wall_paint_patch(stage, idx, x, y, axis="x", color=(0.62, 0.32, 0.10),
                            width=1.6, height=2.0):
    """Faded paint rectangle flush with a wall — breaks up solid-color
    wall by overlaying a slightly off-hue patch where panels were repainted."""
    path = f"/World/Layout/wall_patch_{idx}"
    cube = UsdGeom.Cube.Define(stage, path)
    cube.GetSizeAttr().Set(2.0)
    pxf = UsdGeom.XformCommonAPI(cube.GetPrim())
    if axis == "x":
        pxf.SetScale(Gf.Vec3f(width / 2.0, 0.004, height / 2.0))
    else:
        pxf.SetScale(Gf.Vec3f(0.004, width / 2.0, height / 2.0))
    pxf.SetTranslate(Gf.Vec3d(x, y, height / 2.0 + 0.4))
    bind_material(stage, cube, "M_PaintedWall", color)
    return idx + 1



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


