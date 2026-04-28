"""
Procedural Layout Generator

Reads layout presets from assets/layouts.json, merges with user overrides,
and spawns racks, rack shelf inventory, pallets (loaded), dock areas,
and clutter props into the USD stage.
"""

import os
import json
import math
import random
from pxr import UsdGeom, Gf, UsdPhysics
import omni.usd
import omni.kit.commands
from isaac_backend.semantics import apply_usd_semantics

LAYOUTS_PATH = os.path.join(os.path.dirname(__file__), "..", "assets", "layouts.json")
try:
    with open(LAYOUTS_PATH) as f:
        LAYOUTS = json.load(f)
except Exception:
    LAYOUTS = {}

SHELF_PROPS = ["box", "box_small", "box_large", "crate"]
PALLET_CARGO_PROPS = ["box", "box_small", "box_large", "barrel", "drum", "crate"]
CLUTTER_PROPS = ["box", "box_small", "box_large", "barrel", "drum", "cone", "pallet", "crate"]
SHELF_POSITIONS_PER_LEVEL = 5

# SM_RackFrame_03 footprint after the 90° rotation we apply: 2.8m along the
# row direction (X) × 1.1m deep (Y). Used both for placement pitch and for
# converting the JSON `aisle_width` (gap-between-racks) into row pitch.
RACK_X_EXTENT = 2.8
RACK_DEPTH = 1.1
# Tight wall margin so racks dress the perimeter instead of leaving the walls
# reading as a bare frame around a central clump.
WALL_CLEARANCE = 0.9

RACK_FILL_PROBS = {
    "empty": 0.0,
    "sparse": 0.30,
    "medium": 0.60,
    "full": 0.90,
}

SEMANTIC_MAP = {
    "box": "box",
    "box_small": "box",
    "box_large": "box",
    "crate": "box",
    "barrel": "barrel",
    "drum": "barrel",
    "cone": "cone",
    "pallet": "pallet",
    "rack": "rack",
}


def _resolve_params(layout_name, layout_params, layouts):
    preset = layouts.get(layout_name, layouts.get("standard_warehouse", {}))
    params = {
        "rack_pattern": preset.get("rack_pattern", "rows"),
        "rack_rows": preset.get("rack_rows", "auto"),
        "rack_cols": preset.get("rack_cols", "auto"),
        "target_rack_height": preset.get("target_rack_height", 4.5),
        "aisle_width": preset.get("aisle_width", 2.5),
        "bounds_min": tuple(preset.get("bounds_min", [-12.0, -12.0])),
        "bounds_max": tuple(preset.get("bounds_max", [12.0, 12.0])),
        "clutter_density": preset.get("clutter_density", "high"),
        "clutter_zones": [dict(z) for z in preset.get("clutter_zones", [])],
        "pallet_rows": preset.get("pallet_rows", 3),
        "pallet_cols": preset.get("pallet_cols", 2),
        "rack_fill": preset.get("rack_fill", "medium"),
        "dock_area": preset.get("dock_area", False),
    }
    if layout_params:
        for key in (
            "rack_pattern", "rack_rows", "rack_cols", "target_rack_height", "aisle_width",
            "bounds_min", "bounds_max", "clutter_density", "clutter_zones",
            "pallet_rows", "pallet_cols", "rack_fill", "dock_area",
        ):
            if key in layout_params:
                val = layout_params[key]
                if key in ("bounds_min", "bounds_max"):
                    params[key] = tuple(val)
                elif key == "clutter_zones":
                    params[key] = [dict(z) for z in val]
                else:
                    params[key] = val
    return params


def _paint_floor_stripe(stage, idx, x, y, length_x, length_y, color, z=0.012):
    """Thin colored cuboid laid on the floor — used for aisle paint, hatched zones."""
    path = f"/World/Layout/floor_stripe_{idx}"
    cube = UsdGeom.Cube.Define(stage, path)
    cube.GetSizeAttr().Set(2.0)  # default unit cube of size 2 (extents ±1)
    prim = cube.GetPrim()
    xf = UsdGeom.XformCommonAPI(prim)
    # Cube default is 2x2x2 → scale halves give the desired full extents.
    xf.SetScale(Gf.Vec3f(length_x / 2.0, length_y / 2.0, 0.012))
    xf.SetTranslate(Gf.Vec3d(x, y, z))
    cube.CreateDisplayColorAttr([Gf.Vec3f(*color)])
    return idx + 1


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
    cyl.CreateDisplayColorAttr([Gf.Vec3f(0.95, 0.78, 0.05)])
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
        band.CreateDisplayColorAttr([Gf.Vec3f(0.05, 0.05, 0.05)])
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
    cube.CreateDisplayColorAttr([Gf.Vec3f(0.32, 0.34, 0.38)])
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
    cube.CreateDisplayColorAttr([Gf.Vec3f(0.95, 0.95, 0.92)])
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
        band.CreateDisplayColorAttr([Gf.Vec3f(*band_color)])
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
    cyl.CreateDisplayColorAttr([Gf.Vec3f(0.78, 0.08, 0.07)])
    # Backplate
    bp_path = f"/World/Layout/fire_ext_plate_{idx}"
    plate = UsdGeom.Cube.Define(stage, bp_path)
    plate.GetSizeAttr().Set(2.0)
    pxf = UsdGeom.XformCommonAPI(plate.GetPrim())
    pxf.SetScale(Gf.Vec3f(0.18, 0.02, 0.32))
    pxf.SetTranslate(Gf.Vec3d(x, y - 0.06, 1.10))
    plate.CreateDisplayColorAttr([Gf.Vec3f(0.85, 0.85, 0.82)])
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
    cube.CreateDisplayColorAttr([Gf.Vec3f(0.10, 0.85, 0.25)])
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
    cyl.CreateDisplayColorAttr([Gf.Vec3f(*color)])
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
    cube.CreateDisplayColorAttr([Gf.Vec3f(0.55, 0.40, 0.25)])
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
        leg.CreateDisplayColorAttr([Gf.Vec3f(0.45, 0.32, 0.18)])
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
    cube.CreateDisplayColorAttr([Gf.Vec3f(0.72, 0.55, 0.32)])
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
    sh.CreateDisplayColorAttr([Gf.Vec3f(*yellow)])
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
        hd.CreateDisplayColorAttr([Gf.Vec3f(*yellow)])
    return idx + 3


def _place(asset_id, x, y, z, rot_z, asset_library, stage, idx, scale=None):
    usd = asset_library.get(asset_id)
    if not usd:
        return idx
    path = f"/World/Layout/{asset_id}_{idx}"
    omni.kit.commands.execute(
        "CreateReferenceCommand",
        usd_context=omni.usd.get_context(),
        path_to=path,
        asset_path=usd,
        instanceable=False,
    )
    prim = stage.GetPrimAtPath(path)
    if not prim.IsValid():
        return idx + 1
    xf = UsdGeom.XformCommonAPI(prim)
    xf.SetTranslate(Gf.Vec3d(x, y, z))
    xf.SetRotate(Gf.Vec3f(0, 0, rot_z), UsdGeom.XformCommonAPI.RotationOrderXYZ)
    if scale is not None:
        if isinstance(scale, (tuple, list)):
            xf.SetScale(Gf.Vec3f(float(scale[0]), float(scale[1]), float(scale[2])))
        else:
            xf.SetScale(Gf.Vec3f(scale, scale, scale))
    semantic_class = SEMANTIC_MAP.get(asset_id, asset_id)
    apply_usd_semantics(prim, semantic_class)
    # Static collision so navmesh routes workers and vehicles around layout items.
    # CollisionAPI only (no RigidBodyAPI) keeps items stationary.
    if not prim.HasAPI(UsdPhysics.CollisionAPI):
        UsdPhysics.CollisionAPI.Apply(prim)
    return idx + 1


def _spawn_racks(params, asset_library, stage, idx):
    pattern = params["rack_pattern"]
    rows = params["rack_rows"]
    cols = params["rack_cols"]
    aw = params["aisle_width"]
    bmin = params["bounds_min"]
    bmax = params["bounds_max"]
    
    target_rack_height = params.get("target_rack_height", 4.5)
    rack_base_height = 2.4  # measured height of SM_RackFrame_03 base mesh
    rack_z_scale = target_rack_height / rack_base_height

    rack_x_extent = RACK_X_EXTENT
    # Row pitch = rack body + aisle gap. The JSON `aisle_width` is the gap a
    # forklift/worker actually walks through, not the center-to-center spacing.
    row_pitch = RACK_DEPTH + aw

    if cols == "auto" or cols is None:
        available_x = (bmax[0] - bmin[0]) - 2 * WALL_CLEARANCE
        cols = max(1, int(available_x / rack_x_extent))
    if rows == "auto" or rows is None:
        available_y = (bmax[1] - bmin[1]) - 2 * WALL_CLEARANCE
        # rows*RACK_DEPTH + (rows-1)*aw <= available_y  →  rows <= (available_y + aw) / row_pitch
        rows = max(1, int((available_y + aw) / row_pitch))

    count = 0
    rack_positions = []

    if pattern == "none" or rows == 0:
        return idx, 0, rack_positions

    if pattern == "rows":
        # rack_rows parallel rows running East-West, each with rack_cols racks
        # placed back-to-back along X. Row spacing is RACK_DEPTH + aw so that
        # aw ends up as the actual walkable aisle gap between rack bodies.
        # Backmost row sits one wall-clearance off the back (+Y) wall; the
        # rest of the rows extend forward from there, leaving the front of
        # the warehouse open for the dock/entry zone.
        total_x = max(0, cols - 1) * rack_x_extent
        total_y = (rows - 1) * row_pitch
        x_start = (bmin[0] + bmax[0]) / 2.0 - total_x / 2.0
        y_back = bmax[1] - WALL_CLEARANCE - RACK_DEPTH / 2.0
        y_start = y_back - total_y
        for r in range(rows):
            y = y_start + r * row_pitch
            for c in range(cols):
                x = x_start + c * rack_x_extent
                idx = _place("rack", x, y, 0, 90, asset_library, stage, idx, scale=(1.0, 1.0, rack_z_scale))
                rack_positions.append((x, y, 90))
                count += 1

    elif pattern == "grid":
        total_x = max(0, cols - 1) * rack_x_extent
        total_y = (rows - 1) * row_pitch
        x_start = (bmin[0] + bmax[0]) / 2.0 - total_x / 2.0
        y_back = bmax[1] - WALL_CLEARANCE - RACK_DEPTH / 2.0
        y_start = y_back - total_y
        for r in range(rows):
            for c in range(cols):
                x = x_start + c * rack_x_extent
                y = y_start + r * row_pitch
                idx = _place("rack", x, y, 0, 90, asset_library, stage, idx, scale=(1.0, 1.0, rack_z_scale))
                rack_positions.append((x, y, 90))
                count += 1

    elif pattern == "L-shape":
        total_span_h = (rows - 1) * aw
        y_start_h = (bmin[1] + bmax[1]) / 2.0 - total_span_h / 2.0
        x_h = bmin[0] + (bmax[0] - bmin[0]) * 0.25
        for r in range(rows):
            y = y_start_h + r * aw
            idx = _place("rack", x_h, y, 0, 90, asset_library, stage, idx, scale=(1.0, 1.0, rack_z_scale))
            rack_positions.append((x_h, y, 90))
            count += 1
        total_span_v = max(2, rows - 1) * aw
        x_start_v = x_h + aw
        y_bottom = bmin[1] + (bmax[1] - bmin[1]) * 0.25
        for c in range(max(2, rows - 1)):
            x = x_start_v + c * aw
            idx = _place("rack", x, y_bottom, 0, 0, asset_library, stage, idx, scale=(1.0, 1.0, rack_z_scale))
            rack_positions.append((x, y_bottom, 0))
            count += 1

    elif pattern == "perimeter":
        total_x = (cols - 1) * aw
        total_y = (rows - 1) * aw
        y_bottom = bmin[1] + (bmax[1] - bmin[1]) * 0.1
        y_top = bmax[1] - (bmax[1] - bmin[1]) * 0.1
        x_start = (bmin[0] + bmax[0]) / 2.0 - total_x / 2.0
        for c in range(cols):
            x = x_start + c * aw
            idx = _place("rack", x, y_bottom, 0, 0, asset_library, stage, idx, scale=(1.0, 1.0, rack_z_scale))
            idx = _place("rack", x, y_top, 0, 90, asset_library, stage, idx, scale=(1.0, 1.0, rack_z_scale))
            rack_positions.extend([(x, y_bottom, 0), (x, y_top, 90)])
            count += 2
        x_left = bmin[0] + (bmax[0] - bmin[0]) * 0.1
        x_right = bmax[0] - (bmax[0] - bmin[0]) * 0.1
        y_start_v = (bmin[1] + bmax[1]) / 2.0 - total_y / 2.0
        for r in range(rows):
            y = y_start_v + r * aw
            idx = _place("rack", x_left, y, 0, 0, asset_library, stage, idx, scale=(1.0, 1.0, rack_z_scale))
            idx = _place("rack", x_right, y, 0, 0, asset_library, stage, idx, scale=(1.0, 1.0, rack_z_scale))
            rack_positions.extend([(x_left, y, 0), (x_right, y, 0)])
            count += 2

    elif pattern == "clusters":
        cx = (bmin[0] + bmax[0]) / 2.0
        cy = (bmin[1] + bmax[1]) / 2.0
        total_y = (rows - 1) * aw
        y_start = cy - total_y / 2.0
        for r in range(rows):
            y = y_start + r * aw
            if r % 2 == 0:
                idx = _place("rack", cx, y, 0, 90, asset_library, stage, idx, scale=(1.0, 1.0, rack_z_scale))
                rack_positions.append((cx, y, 90))
                count += 1




    return idx, count, rack_positions


def _populate_rack_shelves(rack_positions, params, asset_library, stage, idx):
    fill_level = params.get("rack_fill", "medium")
    fill_prob = RACK_FILL_PROBS.get(fill_level, 0.60)
    deck_count = 0
    cargo_count = 0
    has_shelf_asset = "rack_shelf" in asset_library
    
    target_rack_height = params.get("target_rack_height", 4.5)
    shelf_spacing = 0.9
    num_shelves = int(target_rack_height / shelf_spacing)
    shelf_heights = [0.15 + i * shelf_spacing for i in range(num_shelves)]

    has_pallet_asset = "pallet" in asset_library

    for pos in rack_positions:
        # Tolerate older 2-tuple positions in case of partial upgrade.
        if len(pos) == 3:
            rx, ry, rrot = pos
        else:
            rx, ry = pos
            rrot = 90

        # One shelf level per rack is randomly skipped to break up the uniform
        # vertical pattern across the warehouse — empty/missing decks read as
        # a stocking-in-progress shelving unit.
        skip_level = random.randint(0, len(shelf_heights) - 1) if (
            len(shelf_heights) > 1 and random.random() < 0.35
        ) else -1
        rack_shelf_heights = [
            sh for i, sh in enumerate(shelf_heights) if i != skip_level
        ]

        # Place a horizontal deck plank at each shelf level so the rack reads
        # as a real loaded shelving unit instead of a bare frame.
        if has_shelf_asset:
            for shelf_z in rack_shelf_heights:
                idx = _place("rack_shelf", rx, ry, shelf_z, rrot, asset_library, stage, idx)
                deck_count += 1

        if fill_prob <= 0.0:
            continue

        # Per-rack fill bias so some bays look overstocked, some near-empty —
        # uniform fill across all racks reads as artificial.
        rack_bias = random.gauss(0.0, 0.25)
        rack_fill_prob = max(0.0, min(1.0, fill_prob + rack_bias))
        # One dominant SKU per rack with occasional mixing — looks more like real stocking.
        primary_prop = random.choice(SHELF_PROPS)
        # Some racks store cargo on pallets (palletized SKUs), others bare-shelf.
        rack_uses_pallets = has_pallet_asset and random.random() < 0.55

        ang = math.radians(rrot)
        cos_a, sin_a = math.cos(ang), math.sin(ang)
        for shelf_z in rack_shelf_heights:
            for slot in range(SHELF_POSITIONS_PER_LEVEL):
                if random.random() > rack_fill_prob:
                    continue
                prop = primary_prop if random.random() < 0.7 else random.choice(SHELF_PROPS)
                # Distribute slots evenly along the shelf length, with mild jitter.
                slot_frac = (slot + 0.5) / SHELF_POSITIONS_PER_LEVEL  # 0..1
                local_along = (slot_frac - 0.5) * 2.2 + random.uniform(-0.10, 0.10)
                local_depth = random.uniform(-0.18, 0.18)
                # Rotate local (along, depth) → world (x, y) using rack orientation.
                world_dx = local_along * cos_a - local_depth * sin_a
                world_dy = local_along * sin_a + local_depth * cos_a
                x = rx + world_dx
                y = ry + world_dy
                # Palletized racks: thin pallet under the cargo, cargo lifted
                # by pallet thickness. Reads much better than floating boxes.
                z_base = shelf_z + random.uniform(-0.02, 0.02)
                if rack_uses_pallets:
                    idx = _place("pallet", x, y, z_base, rrot, asset_library, stage, idx)
                    cargo_count += 1
                    z_box = z_base + 0.14
                else:
                    z_box = z_base
                rot = rrot + random.uniform(-15, 15)
                idx = _place(prop, x, y, z_box, rot, asset_library, stage, idx)
                cargo_count += 1

    print(f"[INFO] Populated rack shelves: {deck_count} decks, {cargo_count} cargo items "
          f"(fill={fill_level}, prob={fill_prob:.0%})")
    return idx, deck_count + cargo_count


def _stack_boxes(x, y, probs, jitters, asset_library, stage, idx):
    """Stack up to 3 boxes on a pallet at (x, y).

    probs:   (p_first, p_second, p_third) — probability of placing each layer.
    jitters: (j0, j1, j2) — ±XY jitter (metres) per layer.

    Returns updated idx and count of items placed.
    """
    layers = [
        (random.choice(["box", "box_small", "box_large", "crate"]), 0.15, 15),
        (random.choice(["box", "box_small", "crate"]),               0.45, 15),
        (random.choice(["box_small", "crate"]),                      0.72, 10),
    ]
    count = 0
    for (prop, z, rot_max), prob, jitter in zip(layers, probs, jitters):
        if random.random() >= prob:
            break
        idx = _place(prop,
                     x + random.uniform(-jitter, jitter),
                     y + random.uniform(-jitter, jitter),
                     z, random.uniform(-rot_max, rot_max),
                     asset_library, stage, idx)
        count += 1
    return idx, count


def _spawn_pallets(params, asset_library, stage, idx):
    pallet_rows_grid = params["pallet_rows"]
    pallet_cols_grid = params["pallet_cols"]
    bmin = params["bounds_min"]
    bmax = params["bounds_max"]
    count = 0

    if pallet_rows_grid == 0 or pallet_cols_grid == 0:
        return idx, 0

    spacing_x = 2.0
    spacing_y = 2.5
    total_x = (pallet_cols_grid - 1) * spacing_x
    total_y = (pallet_rows_grid - 1) * spacing_y
    x_start = (bmin[0] + bmax[0]) / 2.0 - total_x / 2.0
    y_start = bmax[1] - 0.5

    for r in range(pallet_rows_grid):
        for c in range(pallet_cols_grid):
            x = x_start + c * spacing_x + random.uniform(-0.12, 0.12)
            y = y_start - r * spacing_y + random.uniform(-0.12, 0.12)
            idx = _place("pallet", x, y, 0, random.uniform(-8, 8), asset_library, stage, idx)
            count += 1

            cargo_roll = random.random()
            if cargo_roll < 0.70:
                idx, n = _stack_boxes(x, y, (1.0, 0.65, 0.35), (0.08, 0.10, 0.12), asset_library, stage, idx)
                count += n
            elif cargo_roll < 0.90:
                barrel_prop = random.choice(["barrel", "drum"])
                idx = _place(barrel_prop, x + random.uniform(-0.05, 0.05),
                              y + random.uniform(-0.05, 0.05), 0.15,
                              random.uniform(0, 360), asset_library, stage, idx)
                count += 1
                if random.random() < 0.4:
                    idx = _place(random.choice(["barrel", "drum"]),
                                  x + random.uniform(-0.05, 0.05),
                                  y + random.uniform(-0.05, 0.05), 0.55,
                                  random.uniform(0, 360), asset_library, stage, idx)
                    count += 1

    return idx, count


def _count_clutter_for_density(density):
    return {"low": 8, "medium": 18, "high": 30}.get(density, 18)


def _spawn_clutter(params, asset_library, stage, idx):
    density = params["clutter_density"]
    zones = params.get("clutter_zones", [])
    bmin = params["bounds_min"]
    bmax = params["bounds_max"]
    count = 0

    if zones:
        for zone in zones:
            n = _count_clutter_for_density(zone.get("density", density))
            types = zone.get("types", CLUTTER_PROPS)
            available_types = [t for t in types if t in asset_library]
            if not available_types:
                available_types = [t for t in CLUTTER_PROPS if t in asset_library]
                if not available_types:
                    available_types = ["box"]
            zbmin = tuple(zone.get("bounds_min", bmin))
            zbmax = tuple(zone.get("bounds_max", bmax))
            for _ in range(n):
                prop = random.choice(available_types)
                x = random.uniform(zbmin[0], zbmax[0])
                y = random.uniform(zbmin[1], zbmax[1])
                rot = random.uniform(0, 360)
                idx = _place(prop, x, y, 0, rot, asset_library, stage, idx)
                count += 1
    else:
        n = _count_clutter_for_density(density)
        available_types = [p for p in CLUTTER_PROPS if p in asset_library]
        if not available_types:
            available_types = ["box"]
        for _ in range(n):
            prop = random.choice(available_types)
            x = random.uniform(bmin[0], bmax[0])
            y = random.uniform(bmin[1], bmax[1])
            rot = random.uniform(0, 360)
            idx = _place(prop, x, y, 0, rot, asset_library, stage, idx)
            count += 1

    return idx, count


def _spawn_dock_area(params, asset_library, stage, idx):
    bmin = params["bounds_min"]
    bmax = params["bounds_max"]
    count = 0

    dock_x_start = bmin[0] + 2.0
    dock_x_end = bmin[0] + 9.0
    dock_y_start = bmin[1] + 1.0
    dock_y_end = bmin[1] + 5.0

    dock_pallet_rows = 2
    dock_pallet_cols = 4
    spacing_x = 1.8
    spacing_y = 2.0

    dock_y_total = (dock_pallet_rows - 1) * spacing_y
    dock_y_center = (dock_y_start + dock_y_end) / 2.0
    dock_y_base = dock_y_center - dock_y_total / 2.0

    for r in range(dock_pallet_rows):
        for c in range(dock_pallet_cols):
            x = dock_x_start + c * spacing_x + random.uniform(-0.2, 0.2)
            y = dock_y_base + r * spacing_y + random.uniform(-0.2, 0.2)
            idx = _place("pallet", x, y, 0, random.uniform(-15, 15), asset_library, stage, idx)
            count += 1
            # Dock pallets always carry at least one box; second/third are probabilistic.
            idx, n = _stack_boxes(x, y, (1.0, 0.70, 0.40), (0.10, 0.12, 0.12), asset_library, stage, idx)
            count += n

    for _ in range(random.randint(3, 6)):
        x = random.uniform(dock_x_start - 1.0, dock_x_end + 1.0)
        y = random.uniform(dock_y_start - 1.0, dock_y_end + 1.0)
        prop = random.choice(["barrel", "drum", "box_large", "cone"])
        if prop not in asset_library:
            prop = "box"
        idx = _place(prop, x, y, 0, random.uniform(0, 360), asset_library, stage, idx)
        count += 1

    print(f"[INFO] Spawned dock area with {count} items")
    return idx, count


def _spawn_floor_markings(rack_positions, params, stage, idx):
    """Yellow aisle paint between rows, hatched corners at endpoints."""
    if not rack_positions:
        return idx, 0
    bmin = params["bounds_min"]
    bmax = params["bounds_max"]
    yellow = (0.92, 0.78, 0.10)
    count = 0

    # Group racks by row (same y, allowing for clusters/grid). Keys snapped to 0.5m.
    rows = {}
    for (rx, ry, rrot) in rack_positions:
        if rrot == 90:
            key = round(ry * 2) / 2.0
            rows.setdefault(key, []).append(rx)

    sorted_ys = sorted(rows.keys())
    for i in range(len(sorted_ys) - 1):
        y_a, y_b = sorted_ys[i], sorted_ys[i + 1]
        y_mid = (y_a + y_b) / 2.0
        xs = rows[y_a] + rows[y_b]
        x_lo, x_hi = min(xs) - 1.0, max(xs) + 1.0
        # Two parallel yellow stripes 0.4m apart bracketing the aisle centerline.
        for offset in (-0.20, 0.20):
            idx = _paint_floor_stripe(stage, idx, (x_lo + x_hi) / 2.0,
                                      y_mid + offset, x_hi - x_lo, 0.10, yellow)
            count += 1

    # Perimeter safety border just inside the warehouse walls.
    border_color = (0.85, 0.72, 0.10)
    margin = 0.4
    for y_edge in (bmin[1] + margin, bmax[1] - margin):
        idx = _paint_floor_stripe(stage, idx, (bmin[0] + bmax[0]) / 2.0, y_edge,
                                  (bmax[0] - bmin[0]) - 2 * margin, 0.10, border_color)
        count += 1
    return idx, count


def _spawn_column_guards(rack_positions, stage, idx):
    if not rack_positions:
        return idx, 0
    # Cluster racks by row again, place a guard at each row's leftmost and rightmost end.
    rows = {}
    for (rx, ry, rrot) in rack_positions:
        if rrot == 90:
            key = round(ry * 2) / 2.0
            rows.setdefault(key, []).append((rx, ry))
    count = 0
    for key, items in rows.items():
        items.sort()
        (lx, ly) = items[0]
        (rx, ry) = items[-1]
        idx = _place_column_guard(stage, idx, lx - 1.5, ly)
        idx = _place_column_guard(stage, idx, rx + 1.5, ry)
        count += 2
    return idx, count


def _spawn_rack_end_details(rack_positions, asset_library, stage, idx):
    """Placards on rack uprights, plus an occasional leaning pallet or tipped box at row ends."""
    if not rack_positions:
        return idx, 0
    rows = {}
    for (rx, ry, rrot) in rack_positions:
        if rrot == 90:
            key = round(ry * 2) / 2.0
            rows.setdefault(key, []).append((rx, ry))
    count = 0
    # Each row gets a stable color band so all placards in a row read as
    # belonging to the same numbered aisle (A row = blue, B row = orange…).
    band_palette = [(0.20, 0.55, 0.90), (0.90, 0.40, 0.20),
                    (0.30, 0.70, 0.35), (0.85, 0.20, 0.55),
                    (0.95, 0.78, 0.10), (0.55, 0.30, 0.75)]
    for row_i, (key, items) in enumerate(sorted(rows.items())):
        items.sort()
        row_color = band_palette[row_i % len(band_palette)]
        # Placard at every rack upright (each rack contributes two)
        for (rx, ry) in items:
            for upright_dx in (-1.35, 1.35):
                idx = _place_shelf_placard(stage, idx, rx + upright_dx, ry - 0.55,
                                            1.45, 0, band_color=row_color)
                count += 1
        # Leaning empty pallet at one end of the row
        (lx, ly) = items[0]
        if "pallet" in asset_library and random.random() < 0.7:
            idx = _place("pallet", lx - 1.4, ly - 0.6, 0.55, random.uniform(70, 90),
                         asset_library, stage, idx)
            count += 1
        # Tipped box on its side near the other end
        (rx_end, ry_end) = items[-1]
        if random.random() < 0.6:
            prop = random.choice(["box", "box_large", "crate"])
            if prop in asset_library:
                idx = _place(prop, rx_end + 1.6, ry_end + 0.4, 0.20,
                             random.uniform(60, 110), asset_library, stage, idx)
                count += 1
    return idx, count


def _spawn_wall_details(params, asset_library, stage, idx):
    """Fire extinguishers, exit signs, trash bins, pack station, flattened-cardboard stack."""
    bmin = params["bounds_min"]
    bmax = params["bounds_max"]
    cx = (bmin[0] + bmax[0]) / 2.0
    cy = (bmin[1] + bmax[1]) / 2.0
    count = 0

    # Fire extinguishers — one per long wall, mid-span.
    margin = 0.25
    idx = _place_fire_extinguisher(stage, idx, bmin[0] + margin, cy - 1.5)
    idx = _place_fire_extinguisher(stage, idx, bmax[0] - margin, cy + 1.5)
    count += 4  # each placement adds 2 prims

    # Exit signs — front and back walls.
    idx = _place_exit_sign(stage, idx, cx, bmin[1] + margin)
    idx = _place_exit_sign(stage, idx, cx, bmax[1] - margin)
    count += 2

    # Trash + recycling bins paired in a corner.
    idx = _place_trash_bin(stage, idx, bmax[0] - 0.6, bmin[1] + 0.7, color=(0.20, 0.45, 0.20))
    idx = _place_trash_bin(stage, idx, bmax[0] - 0.6, bmin[1] + 1.3, color=(0.18, 0.32, 0.62))
    count += 2

    # Pack/wrap station along the back wall with a stacked cargo on top.
    pt_x = cx + 3.5
    pt_y = bmax[1] - 0.9
    idx = _place_pack_table(stage, idx, pt_x, pt_y, rot_z=0)
    count += 1
    if "box_small" in asset_library:
        idx = _place("box_small", pt_x - 0.3, pt_y, 0.95, random.uniform(-15, 15),
                     asset_library, stage, idx)
        idx = _place("box_small", pt_x + 0.25, pt_y - 0.05, 0.95, random.uniform(-15, 15),
                     asset_library, stage, idx)
        count += 2

    # Flattened-cardboard stack tucked next to the bins.
    idx = _place_cardboard_stack(stage, idx, bmax[0] - 0.7, bmin[1] + 2.1,
                                 rot_z=random.uniform(-10, 10), sheets=10)
    count += 1

    # Floor arrows at the warehouse entry approach (pointing into the floor).
    idx = _place_floor_arrow(stage, idx, cx - 2.0, bmin[1] + 1.5, rot_z=90)
    idx = _place_floor_arrow(stage, idx, cx + 2.0, bmin[1] + 1.5, rot_z=90)
    count += 6  # each adds 3 prims
    return idx, count


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
        cube.CreateDisplayColorAttr([Gf.Vec3f(*yellow)])
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
    cube.CreateDisplayColorAttr([Gf.Vec3f(0.45, 0.47, 0.50)])
    return idx + 1


def _place_overhead_light(stage, idx, x, y, z=4.5, length=2.0):
    """Long thin white cuboid as a ceiling strip light."""
    path = f"/World/Layout/ceil_light_{idx}"
    cube = UsdGeom.Cube.Define(stage, path)
    cube.GetSizeAttr().Set(2.0)
    prim = cube.GetPrim()
    xf = UsdGeom.XformCommonAPI(prim)
    xf.SetScale(Gf.Vec3f(length / 2.0, 0.10, 0.04))
    xf.SetTranslate(Gf.Vec3d(x, y, z))
    cube.CreateDisplayColorAttr([Gf.Vec3f(0.96, 0.96, 0.92)])
    return idx + 1


def _place_aisle_sign(stage, idx, x, y, band_color, z=2.8):
    """Small hanging aisle-number placard with a colored band."""
    body_path = f"/World/Layout/aisle_sign_{idx}"
    body = UsdGeom.Cube.Define(stage, body_path)
    body.GetSizeAttr().Set(2.0)
    bxf = UsdGeom.XformCommonAPI(body.GetPrim())
    bxf.SetScale(Gf.Vec3f(0.22, 0.02, 0.16))
    bxf.SetTranslate(Gf.Vec3d(x, y, z))
    body.CreateDisplayColorAttr([Gf.Vec3f(0.96, 0.96, 0.94)])
    band_path = f"/World/Layout/aisle_sign_band_{idx}"
    band = UsdGeom.Cube.Define(stage, band_path)
    band.GetSizeAttr().Set(2.0)
    cxf = UsdGeom.XformCommonAPI(band.GetPrim())
    cxf.SetScale(Gf.Vec3f(0.22, 0.025, 0.04))
    cxf.SetTranslate(Gf.Vec3d(x, y, z + 0.18))
    band.CreateDisplayColorAttr([Gf.Vec3f(*band_color)])
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
    cyl.CreateDisplayColorAttr([Gf.Vec3f(0.92, 0.78, 0.10)])
    broom_path = f"/World/Layout/broom_handle_{idx}"
    broom = UsdGeom.Cube.Define(stage, broom_path)
    broom.GetSizeAttr().Set(2.0)
    hxf = UsdGeom.XformCommonAPI(broom.GetPrim())
    hxf.SetScale(Gf.Vec3f(0.015, 0.015, 0.65))
    hxf.SetTranslate(Gf.Vec3d(x + 0.18, y + 0.05, 0.75))
    hxf.SetRotate(Gf.Vec3f(0, 14, 0), UsdGeom.XformCommonAPI.RotationOrderXYZ)
    broom.CreateDisplayColorAttr([Gf.Vec3f(0.55, 0.38, 0.20)])
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
        cube.CreateDisplayColorAttr([Gf.Vec3f(*color)])
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
        cube.CreateDisplayColorAttr([Gf.Vec3f(*base_color)])
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
        cube.CreateDisplayColorAttr([Gf.Vec3f(*panel_color)])
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
        cube.CreateDisplayColorAttr([Gf.Vec3f(*frame_color)])
    head_path = f"/World/Layout/dock_header_{idx}"
    head = UsdGeom.Cube.Define(stage, head_path)
    head.GetSizeAttr().Set(2.0)
    hxf = UsdGeom.XformCommonAPI(head.GetPrim())
    hxf.SetScale(Gf.Vec3f(width / 2.0 + 0.08, 0.06, 0.10))
    hxf.SetTranslate(Gf.Vec3d(x, y, height + 0.05))
    hxf.SetRotate(Gf.Vec3f(0, 0, rot_z), UsdGeom.XformCommonAPI.RotationOrderXYZ)
    head.CreateDisplayColorAttr([Gf.Vec3f(*frame_color)])
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
    bp.CreateDisplayColorAttr([Gf.Vec3f(*yellow)])
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
        sp.CreateDisplayColorAttr([Gf.Vec3f(*black)])
    return idx + 1 + (stripes // 2)


def _place_sprinkler_head(stage, idx, x, y, z=4.85):
    """Small red-tipped sprinkler head pendant from the ceiling."""
    body_path = f"/World/Layout/sprinkler_{idx}"
    body = UsdGeom.Cylinder.Define(stage, body_path)
    body.GetRadiusAttr().Set(0.04)
    body.GetHeightAttr().Set(0.12)
    body.GetAxisAttr().Set("Z")
    bxf = UsdGeom.XformCommonAPI(body.GetPrim())
    bxf.SetTranslate(Gf.Vec3d(x, y, z))
    body.CreateDisplayColorAttr([Gf.Vec3f(0.65, 0.65, 0.62)])
    bulb_path = f"/World/Layout/sprinkler_bulb_{idx}"
    bulb = UsdGeom.Sphere.Define(stage, bulb_path)
    bulb.GetRadiusAttr().Set(0.035)
    sxf = UsdGeom.XformCommonAPI(bulb.GetPrim())
    sxf.SetTranslate(Gf.Vec3d(x, y, z - 0.09))
    bulb.CreateDisplayColorAttr([Gf.Vec3f(0.85, 0.10, 0.10)])
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
    cyl.CreateDisplayColorAttr([Gf.Vec3f(*color)])
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
    base.CreateDisplayColorAttr([Gf.Vec3f(0.95, 0.78, 0.05)])
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
        band.CreateDisplayColorAttr([Gf.Vec3f(0.06, 0.06, 0.06)])
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
            cube.CreateDisplayColorAttr([Gf.Vec3f(0.55, 0.40, 0.22)])
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
        cube.CreateDisplayColorAttr([Gf.Vec3f(*color)])
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
    cube.CreateDisplayColorAttr([Gf.Vec3f(0.95, 0.95, 0.92)])
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
        bar.CreateDisplayColorAttr([Gf.Vec3f(*color)])
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
    cyl.CreateDisplayColorAttr([Gf.Vec3f(0.95, 0.95, 0.92)])
    # Minute & hour hands as thin cubes
    for hi, (sx, sz, sy_off, color) in enumerate(((0.005, 0.14, -0.04, (0.10, 0.10, 0.10)),
                                                   (0.005, 0.10, -0.04, (0.10, 0.10, 0.10)))):
        h_path = f"/World/Layout/clock_hand_{idx}_{hi}"
        hand = UsdGeom.Cube.Define(stage, h_path)
        hand.GetSizeAttr().Set(2.0)
        hxf = UsdGeom.XformCommonAPI(hand.GetPrim())
        hxf.SetScale(Gf.Vec3f(sx, 0.005, sz))
        hxf.SetTranslate(Gf.Vec3d(x, y + sy_off, z + sz / 2.0))
        hand.CreateDisplayColorAttr([Gf.Vec3f(*color)])
    return idx + 3


def _place_dock_leveler(stage, idx, x, y, width=2.4, depth=1.0):
    """Steel dock leveler plate just inside the dock door — slight ramp tone."""
    path = f"/World/Layout/leveler_{idx}"
    cube = UsdGeom.Cube.Define(stage, path)
    cube.GetSizeAttr().Set(2.0)
    xf = UsdGeom.XformCommonAPI(cube.GetPrim())
    xf.SetScale(Gf.Vec3f(width / 2.0, depth / 2.0, 0.025))
    xf.SetTranslate(Gf.Vec3d(x, y, 0.025))
    cube.CreateDisplayColorAttr([Gf.Vec3f(0.42, 0.42, 0.45)])
    return idx + 1


def _spawn_floor_filling(params, rack_positions, asset_library, stage, idx):
    """Fill the dead space outside the rack footprint with staging pallets,
    drum clusters, and crate piles so the warehouse doesn't read as a clump
    of racks in the middle of an empty box.

    Computes the rack-zone bounding rectangle from rack_positions, then drops
    activity zones in the strips between that rectangle and the warehouse
    walls — front (toward -Y), left (toward -X), right (toward +X). Avoids
    the dock-area corner if dock_area=True.
    """
    bmin = params["bounds_min"]
    bmax = params["bounds_max"]
    if not rack_positions:
        return idx, 0

    rxs = [p[0] for p in rack_positions]
    rys = [p[1] for p in rack_positions]
    # Rack body extends ±RACK_X_EXTENT/2 along X and ±RACK_DEPTH/2 along Y
    # for racks rotated 90°, so pad by those when computing the dead-zone.
    rzone_xmin = min(rxs) - RACK_X_EXTENT / 2.0 - 0.4
    rzone_xmax = max(rxs) + RACK_X_EXTENT / 2.0 + 0.4
    rzone_ymin = min(rys) - RACK_DEPTH / 2.0 - 0.5
    rzone_ymax = max(rys) + RACK_DEPTH / 2.0 + 0.5

    has_dock = params.get("dock_area", False)
    dock_xmax = bmin[0] + 9.0
    dock_ymax = bmin[1] + 5.0

    count = 0

    def _drop_loaded_pallet(x, y, rot=None):
        nonlocal idx, count
        if "pallet" not in asset_library:
            return
        rot = random.uniform(-12, 12) if rot is None else rot
        idx = _place("pallet", x, y, 0, rot, asset_library, stage, idx)
        count += 1
        roll = random.random()
        if roll < 0.6:
            idx, n = _stack_boxes(x, y, (1.0, 0.7, 0.4),
                                  (0.08, 0.10, 0.12), asset_library, stage, idx)
            count += n
        elif roll < 0.85:
            for layer_z in (0.18, 0.55):
                if random.random() > 0.65:
                    break
                bp = random.choice([p for p in ("barrel", "drum") if p in asset_library] or ["box"])
                idx = _place(bp, x + random.uniform(-0.05, 0.05),
                             y + random.uniform(-0.05, 0.05), layer_z,
                             random.uniform(0, 360), asset_library, stage, idx)
                count += 1
        else:
            prop = random.choice([p for p in ("crate", "box_large") if p in asset_library] or ["box"])
            idx = _place(prop, x, y, 0.18, random.uniform(0, 360),
                         asset_library, stage, idx)
            count += 1

    def _drop_drum(x, y, height=0.15):
        nonlocal idx, count
        prop = random.choice([p for p in ("barrel", "drum") if p in asset_library] or ["box"])
        idx = _place(prop, x, y, height, random.uniform(0, 360),
                     asset_library, stage, idx)
        count += 1

    # ---------- 1) FRONT STAGING (between racks and -Y wall) ----------
    front_y_max = rzone_ymin - 0.6
    front_y_min = bmin[1] + 1.5
    if front_y_max > front_y_min + 1.0:
        # Pallet staging grid — two/three rows of loaded pallets.
        n_rows = 2 if (front_y_max - front_y_min) < 4.5 else 3
        n_cols = max(3, int((bmax[0] - bmin[0] - 3.0) / 1.9))
        col_pitch = (bmax[0] - bmin[0] - 3.0) / max(1, n_cols - 1)
        row_pitch = (front_y_max - front_y_min - 0.5) / max(1, n_rows - 1)
        x0 = bmin[0] + 1.5
        for r in range(n_rows):
            for c in range(n_cols):
                px = x0 + c * col_pitch + random.uniform(-0.18, 0.18)
                py = front_y_min + r * row_pitch + random.uniform(-0.15, 0.15)
                if has_dock and px < dock_xmax and py < dock_ymax:
                    continue  # leave room for the dock zone
                if random.random() < 0.85:
                    _drop_loaded_pallet(px, py)

        # A drum cluster at the front-right (when no dock there).
        cluster_x = bmax[0] - 2.5
        cluster_y = (front_y_min + front_y_max) / 2.0
        for _ in range(random.randint(6, 10)):
            dx = cluster_x + random.uniform(-1.4, 1.4)
            dy = cluster_y + random.uniform(-1.4, 1.4)
            if has_dock and dx < dock_xmax and dy < dock_ymax:
                continue
            _drop_drum(dx, dy)

    # ---------- 2) LEFT-WALL STASH (between racks and -X wall) ----------
    left_x_max = rzone_xmin - 0.6
    left_x_min = bmin[0] + 1.0
    if left_x_max > left_x_min + 0.8:
        # Skip the band near the charging station (around y = bmin[1] + 0.75 * span).
        charge_y = bmin[1] + (bmax[1] - bmin[1]) * 0.75
        for _ in range(random.randint(8, 14)):
            sx = random.uniform(left_x_min, left_x_max)
            sy = random.uniform(rzone_ymin, rzone_ymax)
            if abs(sy - charge_y) < 1.5:
                continue
            roll = random.random()
            if roll < 0.5:
                _drop_drum(sx, sy)
            elif roll < 0.8:
                prop = random.choice([p for p in ("crate", "box_large", "box") if p in asset_library] or ["box"])
                idx = _place(prop, sx, sy, 0, random.uniform(0, 360),
                             asset_library, stage, idx)
                count += 1
            else:
                _drop_loaded_pallet(sx, sy)

    # ---------- 3) RIGHT-WALL STASH (between racks and +X wall) ----------
    right_x_min = rzone_xmax + 0.6
    right_x_max = bmax[0] - 1.0
    if right_x_max > right_x_min + 0.8:
        for _ in range(random.randint(8, 14)):
            sx = random.uniform(right_x_min, right_x_max)
            sy = random.uniform(rzone_ymin, rzone_ymax)
            roll = random.random()
            if roll < 0.45:
                _drop_loaded_pallet(sx, sy)
            elif roll < 0.75:
                _drop_drum(sx, sy)
            else:
                prop = random.choice([p for p in ("box_large", "crate", "box") if p in asset_library] or ["box"])
                idx = _place(prop, sx, sy, 0, random.uniform(0, 360),
                             asset_library, stage, idx)
                count += 1

    # ---------- 4) BACK STRIP (if any room behind racks) ----------
    back_y_min = rzone_ymax + 0.6
    back_y_max = bmax[1] - 0.8
    if back_y_max > back_y_min + 0.8:
        n = random.randint(5, 10)
        for _ in range(n):
            bx = random.uniform(bmin[0] + 1.5, bmax[0] - 1.5)
            by = random.uniform(back_y_min, back_y_max)
            if random.random() < 0.6:
                _drop_loaded_pallet(bx, by)
            else:
                _drop_drum(bx, by)

    return idx, count


def _spawn_polish_pass(params, rack_positions, asset_library, stage, idx):
    """Hazard hatching, ceiling pipe runs, sprinkler grid, hi-vis bollards at dock,
    empty-pallet stacks, forklift parking stall, first-aid kit, wall clock,
    and dock-door leveler plates."""
    bmin = params["bounds_min"]
    bmax = params["bounds_max"]
    cx = (bmin[0] + bmax[0]) / 2.0
    cy = (bmin[1] + bmax[1]) / 2.0
    count = 0

    # 1) Ceiling pipe runs along Y — three parallel pipes, slightly different colors.
    pipe_ys = [bmin[1] + 1.5, cy, bmax[1] - 1.5]
    pipe_colors = [(0.55, 0.30, 0.18), (0.20, 0.32, 0.55), (0.70, 0.70, 0.65)]
    for py, pcol in zip(pipe_ys, pipe_colors):
        idx = _place_ceiling_pipe_run(stage, idx, bmin[0] + 0.3, bmax[0] - 0.3,
                                       py, z=4.65, color=pcol)
        count += 1

    # 2) Sprinkler grid on the ceiling — ~3.5m spacing.
    nx = max(2, int((bmax[0] - bmin[0]) / 3.5))
    ny = max(2, int((bmax[1] - bmin[1]) / 3.5))
    for i in range(nx):
        for j in range(ny):
            sx = bmin[0] + (i + 0.5) * (bmax[0] - bmin[0]) / nx
            sy = bmin[1] + (j + 0.5) * (bmax[1] - bmin[1]) / ny
            idx = _place_sprinkler_head(stage, idx, sx, sy, z=4.85)
            count += 2

    # 3) Hazard hatching at front-wall dock approach (3 patches).
    if params.get("dock_area", False):
        for k, frac in enumerate((0.25, 0.5, 0.75)):
            hx = bmin[0] + frac * (bmax[0] - bmin[0])
            hy = bmin[1] + 1.4
            idx = _place_hazard_hatch(stage, idx, hx, hy, width=1.6, depth=0.6,
                                       rot_z=0, stripes=8)
            count += 1

        # 4) Hi-vis bollards bracketing each hatch.
        for frac in (0.25, 0.5, 0.75):
            hx = bmin[0] + frac * (bmax[0] - bmin[0])
            for off in (-1.0, 1.0):
                idx = _place_hi_vis_bollard(stage, idx, hx + off, bmin[1] + 1.4)
                count += 1

        # 5) Dock leveler plate centered on each hatch (just inside the door line).
        for frac in (0.25, 0.5, 0.75):
            hx = bmin[0] + frac * (bmax[0] - bmin[0])
            idx = _place_dock_leveler(stage, idx, hx, bmin[1] + 0.85)
            count += 1

    # 6) Empty-pallet stack tucked at the back-right corner.
    idx, n = _place_empty_pallet_stack(stage, idx,
                                       bmax[0] - 1.4, bmax[1] - 1.6,
                                       asset_library, count=6,
                                       rot_z=random.uniform(-5, 5))
    count += n

    # 7) Forklift parking stall painted on the floor in the charging bay area.
    wall_x = bmin[0] + 1.2
    base_y = bmin[1] + (bmax[1] - bmin[1]) * 0.75
    idx = _place_parking_stall(stage, idx, wall_x + 1.2, base_y + 0.3,
                               width=2.0, depth=3.0, rot_z=0)
    count += 1

    # 8) First-aid kit on the right wall (shoulder height).
    idx = _place_first_aid_kit(stage, idx, bmax[0] - 0.18, cy - 2.5, z=1.55)
    count += 1

    # 9) Wall clock high on the back wall.
    idx = _place_wall_clock(stage, idx, cx + 1.0, bmax[1] - 0.18, z=2.6)
    count += 1

    return idx, count


def _spawn_realism_extras(params, rack_positions, stage, idx):
    """Caution signs in aisles, junction boxes on walls, ceiling strip lights,
    aisle-number placards, mop bucket near bins."""
    bmin = params["bounds_min"]
    bmax = params["bounds_max"]
    cx = (bmin[0] + bmax[0]) / 2.0
    count = 0

    # Caution signs scattered in 1-3 aisle midpoints.
    rows = {}
    for (rx, ry, rrot) in rack_positions:
        if rrot == 90:
            key = round(ry * 2) / 2.0
            rows.setdefault(key, []).append(rx)
    sorted_ys = sorted(rows.keys())
    aisle_mids = []
    for i in range(len(sorted_ys) - 1):
        y_mid = (sorted_ys[i] + sorted_ys[i + 1]) / 2.0
        xs = rows[sorted_ys[i]] + rows[sorted_ys[i + 1]]
        aisle_mids.append((sum(xs) / len(xs), y_mid))
    random.shuffle(aisle_mids)
    for (ax, ay) in aisle_mids[:min(2, len(aisle_mids))]:
        idx = _place_caution_sign(stage, idx, ax + random.uniform(-0.5, 0.5),
                                  ay + random.uniform(-0.3, 0.3),
                                  rot_z=random.uniform(0, 360))
        count += 2

    # Junction boxes along both long walls at ~3m spacing.
    margin = 0.20
    span = bmax[1] - bmin[1]
    n_boxes = max(2, int(span / 3.0))
    for j in range(n_boxes):
        frac = (j + 0.5) / n_boxes
        wy = bmin[1] + frac * span
        idx = _place_wall_junction_box(stage, idx, bmin[0] + margin, wy, z=1.4)
        idx = _place_wall_junction_box(stage, idx, bmax[0] - margin, wy, z=1.55)
        count += 2

    # Ceiling strip lights on a grid above the aisle rows.
    light_zs = 4.5
    n_lights_x = max(2, int((bmax[0] - bmin[0]) / 4.0))
    light_ys = sorted_ys if sorted_ys else [(bmin[1] + bmax[1]) / 2.0]
    for ly in light_ys:
        for k in range(n_lights_x):
            frac = (k + 0.5) / n_lights_x
            lx = bmin[0] + frac * (bmax[0] - bmin[0])
            idx = _place_overhead_light(stage, idx, lx, ly, z=light_zs, length=2.4)
            count += 1

    # Aisle-number sign at the entry side of each aisle.
    band_palette = [(0.20, 0.55, 0.90), (0.90, 0.40, 0.20),
                    (0.30, 0.70, 0.35), (0.85, 0.20, 0.55),
                    (0.95, 0.78, 0.10)]
    for i, (_, ay) in enumerate(aisle_mids):
        color = band_palette[i % len(band_palette)]
        idx = _place_aisle_sign(stage, idx, cx, ay, color, z=2.8)
        count += 2

    # Mop + bucket tucked next to the bin corner used in _spawn_wall_details.
    idx = _place_mop_and_bucket(stage, idx, bmax[0] - 1.2, bmin[1] + 0.9)
    count += 2

    return idx, count


def _spawn_charging_station(params, asset_library, stage, idx):
    """Parked forklift + a couple of charger cabinets along the left wall,
    plus a dark oil stain underneath."""
    if "forklift" not in asset_library:
        return idx, 0
    bmin = params["bounds_min"]
    bmax = params["bounds_max"]
    wall_x = bmin[0] + 1.2
    base_y = bmin[1] + (bmax[1] - bmin[1]) * 0.75
    count = 0
    # Two charger cabinets against the wall.
    for j in range(2):
        idx = _place_charger_box(stage, idx, wall_x - 0.4, base_y + j * 1.1, rot_z=0)
        count += 1
    # Parked forklift facing into the floor (90° → nose along +X).
    idx = _place("forklift", wall_x + 1.2, base_y + 0.5, 0, 90, asset_library, stage, idx)
    count += 1
    # Oil stain pooled below where the forklift drips between shifts.
    idx = _place_oil_stain(stage, idx, wall_x + 1.2, base_y + 0.4, radius=0.55)
    count += 1
    # Cone in front to mark the charging bay.
    if "cone" in asset_library:
        idx = _place("cone", wall_x + 2.6, base_y - 0.3, 0, 0, asset_library, stage, idx)
        count += 1
    return idx, count


def _spawn_dock_doors(params, stage, idx):
    """Roll-up sectional doors along the front (-Y) wall — one per typical
    bay-width along the wall, evenly spaced."""
    bmin = params["bounds_min"]
    bmax = params["bounds_max"]
    wall_y = bmin[1] + 0.06  # just inside the wall
    span_x = bmax[0] - bmin[0]
    door_w = 2.6
    spacing = door_w + 1.4
    n_doors = max(1, int((span_x - 2.0) / spacing))
    total_w = (n_doors - 1) * spacing
    x_start = (bmin[0] + bmax[0]) / 2.0 - total_w / 2.0
    count = 0
    for d in range(n_doors):
        x = x_start + d * spacing
        idx = _place_dock_door(stage, idx, x, wall_y, width=door_w, height=3.2, rot_z=0)
        count += 1
    return idx, count


def _spawn_aisle_floor_wear(rack_positions, params, stage, idx):
    """Tire scuffs running down each aisle centerline, plus an oil stain in
    one random aisle for variety."""
    if not rack_positions:
        return idx, 0
    bmin = params["bounds_min"]
    bmax = params["bounds_max"]
    rows = {}
    for (rx, ry, rrot) in rack_positions:
        if rrot == 90:
            key = round(ry * 2) / 2.0
            rows.setdefault(key, []).append(rx)
    sorted_ys = sorted(rows.keys())
    aisle_mids = []
    for i in range(len(sorted_ys) - 1):
        y_mid = (sorted_ys[i] + sorted_ys[i + 1]) / 2.0
        xs = rows[sorted_ys[i]] + rows[sorted_ys[i + 1]]
        x_lo, x_hi = min(xs) - 0.8, max(xs) + 0.8
        aisle_mids.append((y_mid, x_lo, x_hi))
    count = 0
    for (y_mid, x_lo, x_hi) in aisle_mids:
        # Two parallel scuff tracks ~1.0m apart — left and right wheel tracks.
        for offset in (-0.50, 0.50):
            idx = _place_tire_scuff(stage, idx, (x_lo + x_hi) / 2.0,
                                    y_mid + offset, x_hi - x_lo, rot_z=0)
            count += 1
    if aisle_mids and random.random() < 0.7:
        y_mid, x_lo, x_hi = random.choice(aisle_mids)
        ox = random.uniform(x_lo + 1.0, x_hi - 1.0)
        idx = _place_oil_stain(stage, idx, ox, y_mid + random.uniform(-0.2, 0.2),
                               radius=0.35)
        count += 1
    return idx, count


def _spawn_mid_aisle_forklift(rack_positions, params, asset_library, stage, idx):
    """Drop a second forklift parked mid-aisle to imply active operations."""
    if "forklift" not in asset_library or not rack_positions:
        return idx, 0
    rows = {}
    for (rx, ry, rrot) in rack_positions:
        if rrot == 90:
            key = round(ry * 2) / 2.0
            rows.setdefault(key, []).append(rx)
    sorted_ys = sorted(rows.keys())
    if len(sorted_ys) < 2:
        return idx, 0
    # Pick the aisle nearest the warehouse center.
    cy = (params["bounds_min"][1] + params["bounds_max"][1]) / 2.0
    aisle_mids = []
    for i in range(len(sorted_ys) - 1):
        y_mid = (sorted_ys[i] + sorted_ys[i + 1]) / 2.0
        xs = rows[sorted_ys[i]] + rows[sorted_ys[i + 1]]
        aisle_mids.append((y_mid, sum(xs) / len(xs)))
    aisle_mids.sort(key=lambda t: abs(t[0] - cy))
    y_mid, x_center = aisle_mids[0]
    fx = x_center + random.uniform(-1.5, 1.5)
    fy = y_mid + random.uniform(-0.15, 0.15)
    rot = random.choice([0, 180]) + random.uniform(-8, 8)
    idx = _place("forklift", fx, fy, 0, rot, asset_library, stage, idx)
    count = 1
    # Loaded pallet on the forks if available.
    if "pallet" in asset_library:
        ang = math.radians(rot)
        cos_a, sin_a = math.cos(ang), math.sin(ang)
        # Forks extend along +X in the forklift's local frame.
        local_fx = 1.2
        px = fx + local_fx * cos_a
        py = fy + local_fx * sin_a
        idx = _place("pallet", px, py, 0.18, rot, asset_library, stage, idx)
        count += 1
        # Stack of boxes on the pallet.
        idx, n = _stack_boxes(px, py, (1.0, 0.7, 0.35),
                              (0.06, 0.08, 0.10), asset_library, stage, idx)
        count += n
    return idx, count


def generate_layout(layout_name, layout_params, asset_library, stage):
    params = _resolve_params(layout_name, layout_params, LAYOUTS)

    idx = 0
    num_racks = 0
    num_pallets = 0
    num_clutter = 0
    num_shelf_items = 0
    num_dock_items = 0

    idx, num_racks, rack_positions = _spawn_racks(params, asset_library, stage, idx)

    idx, num_shelf_items = _populate_rack_shelves(
        rack_positions, params, asset_library, stage, idx
    )

    idx, num_pallets = _spawn_pallets(params, asset_library, stage, idx)

    idx, num_clutter = _spawn_clutter(params, asset_library, stage, idx)

    if params.get("dock_area", False):
        idx, num_dock_items = _spawn_dock_area(params, asset_library, stage, idx)

    idx, num_stripes = _spawn_floor_markings(rack_positions, params, stage, idx)
    idx, num_guards = _spawn_column_guards(rack_positions, stage, idx)
    idx, num_charge = _spawn_charging_station(params, asset_library, stage, idx)
    idx, num_rack_extras = _spawn_rack_end_details(rack_positions, asset_library, stage, idx)
    idx, num_wall_extras = _spawn_wall_details(params, asset_library, stage, idx)
    idx, num_realism = _spawn_realism_extras(params, rack_positions, stage, idx)
    idx, num_wear = _spawn_aisle_floor_wear(rack_positions, params, stage, idx)
    idx, num_mid_fork = _spawn_mid_aisle_forklift(rack_positions, params, asset_library, stage, idx)
    num_doors = 0
    if params.get("dock_area", False):
        idx, num_doors = _spawn_dock_doors(params, stage, idx)

    idx, num_floor_fill = _spawn_floor_filling(params, rack_positions, asset_library, stage, idx)
    idx, num_polish = _spawn_polish_pass(params, rack_positions, asset_library, stage, idx)

    print(f"[INFO] Spawned {num_racks} racks, {num_shelf_items} shelf items, "
          f"{num_pallets} pallets, {num_clutter} clutter props, {num_dock_items} dock items, "
          f"{num_stripes} floor stripes, {num_guards} column guards, {num_charge} charge-bay items, "
          f"{num_rack_extras} rack-end details, {num_wall_extras} wall details, "
          f"{num_realism} realism extras, {num_wear} aisle wear, {num_mid_fork} mid-aisle forklift, "
          f"{num_doors} dock doors, {num_polish} polish-pass items, "
          f"{num_floor_fill} floor-fill staging items.")

    return params["bounds_min"], params["bounds_max"]