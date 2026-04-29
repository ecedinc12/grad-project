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
# Fallback ceiling height used only when the warehouse-prim bbox can't be
# computed for some reason — overridden at runtime by _measure_ceiling_z.
DEFAULT_CEILING_Z = 8.4
# Fraction of the measured ceiling height we want racks to reach.
RACK_CEILING_FILL = 0.68
# Vertical pitch between adjacent rack shelves, scaled with rack height.
SHELF_PITCH_FRACTION = 0.22


def _measure_ceiling_z(stage, fallback=DEFAULT_CEILING_Z):
    """Compute the actual interior ceiling height from the stage by taking
    the world-aligned bbox of every imageable prim that isn't part of the
    procedural layout we're about to spawn. Lets the rest of the layout
    auto-scale to whatever warehouse asset / scale the caller used."""
    try:
        from pxr import UsdGeom as _UG, Usd as _U
        # Replicator writes xformOps as time samples (not defaults), so
        # TimeCode.Default() ignores the 1.7x/2.0x pose scale and we read
        # the unscaled asset. EarliestTime picks up the first authored sample.
        cache = _UG.BBoxCache(_U.TimeCode.EarliestTime(),
                              includedPurposes=[_UG.Tokens.default_, _UG.Tokens.proxy])
        z_max = -1e9
        layout_root = "/World/Layout"
        for prim in stage.Traverse():
            path = str(prim.GetPath())
            if path.startswith(layout_root):
                continue
            if not prim.IsA(_UG.Imageable):
                continue
            try:
                bb = cache.ComputeWorldBound(prim).ComputeAlignedRange()
                if bb.IsEmpty():
                    continue
                zmax_p = bb.GetMax()[2]
                if zmax_p > z_max:
                    z_max = zmax_p
            except Exception:
                continue
        if z_max > 0.5:
            print(f"[INFO] Auto-detected ceiling Z = {z_max:.2f} m")
            return z_max
    except Exception as e:
        print(f"[WARN] _measure_ceiling_z failed: {e}")
    print(f"[WARN] Ceiling auto-detect failed, using fallback {fallback:.2f} m")
    return fallback


def _measure_floor_bounds(stage):
    """Estimate the walkable interior XY rectangle of the loaded warehouse.

    Looks for prims whose name contains "floor" (the Simple_Warehouse asset
    uses SM_floor* meshes) and unions their world-space XY extents. Falls
    back to the world bbox of the warehouse root prim, then to a global
    sweep over imageable prims with bbox bottom near z=0. Each step is
    logged so a silent fallback is visible in the run output."""
    try:
        from pxr import UsdGeom as _UG, Usd as _U
        # Replicator writes pose as time-samples; TimeCode.Default() reads
        # the (often-identity) default and misses the 1.7x/2.0x scale.
        cache = _UG.BBoxCache(_U.TimeCode.EarliestTime(),
                              includedPurposes=[_UG.Tokens.default_, _UG.Tokens.proxy])
        layout_root = "/World/Layout"
        floor_inset = 0.35

        def _bbox_xy(prim):
            try:
                bb = cache.ComputeWorldBound(prim).ComputeAlignedRange()
                if bb.IsEmpty():
                    return None
                lo = bb.GetMin(); hi = bb.GetMax()
                return (lo[0], lo[1], hi[0], hi[1], lo[2], hi[2])
            except Exception:
                return None

        # Build a "ceiling envelope" first. The Simple_Warehouse asset uses
        # SM_floor* meshes for both the interior AND the exterior parking
        # apron, so a raw floor union pulls in the whole site (~40x60m). The
        # ceiling exists only over the building, so its XY footprint is a
        # reliable interior gate.
        c_lo_x = 1e9; c_lo_y = 1e9; c_hi_x = -1e9; c_hi_y = -1e9
        n_ceiling = 0
        for prim in stage.Traverse():
            path = str(prim.GetPath())
            if path.startswith(layout_root):
                continue
            if "ceiling" not in prim.GetName().lower():
                continue
            bb = _bbox_xy(prim)
            if bb is None:
                continue
            lx, ly, hx, hy, lz, hz = bb
            c_lo_x = min(c_lo_x, lx); c_lo_y = min(c_lo_y, ly)
            c_hi_x = max(c_hi_x, hx); c_hi_y = max(c_hi_y, hy)
            n_ceiling += 1

        ceiling_envelope = None
        if n_ceiling > 0 and c_hi_x > c_lo_x and c_hi_y > c_lo_y:
            ceiling_envelope = (c_lo_x, c_lo_y, c_hi_x, c_hi_y)
            print(f"[INFO] Ceiling envelope: union of {n_ceiling} ceiling prims, "
                  f"X=[{c_lo_x:.2f},{c_hi_x:.2f}] Y=[{c_lo_y:.2f},{c_hi_y:.2f}]")

        # Strategy 1: union of floor prims whose centroid sits inside the
        # ceiling envelope. Falls back to the unfiltered union if no ceiling
        # was found (other warehouse assets may not have one).
        f_lo_x = 1e9; f_lo_y = 1e9; f_hi_x = -1e9; f_hi_y = -1e9
        n_floor = 0
        for prim in stage.Traverse():
            path = str(prim.GetPath())
            if path.startswith(layout_root):
                continue
            name_lc = prim.GetName().lower()
            if "floor" not in name_lc or "decal" in name_lc:
                continue
            bb = _bbox_xy(prim)
            if bb is None:
                continue
            lx, ly, hx, hy, lz, hz = bb
            if (hx - lx) < 0.5 or (hy - ly) < 0.5:
                continue
            if ceiling_envelope is not None:
                ccx = (lx + hx) / 2.0; ccy = (ly + hy) / 2.0
                slack = 0.5
                if not (ceiling_envelope[0] - slack <= ccx <= ceiling_envelope[2] + slack
                        and ceiling_envelope[1] - slack <= ccy <= ceiling_envelope[3] + slack):
                    continue
            f_lo_x = min(f_lo_x, lx); f_lo_y = min(f_lo_y, ly)
            f_hi_x = max(f_hi_x, hx); f_hi_y = max(f_hi_y, hy)
            n_floor += 1

        if n_floor > 0 and f_hi_x > f_lo_x and f_hi_y > f_lo_y:
            res_lo = (f_lo_x + floor_inset, f_lo_y + floor_inset)
            res_hi = (f_hi_x - floor_inset, f_hi_y - floor_inset)
            gate = "gated by ceiling" if ceiling_envelope is not None else "ungated"
            print(f"[INFO] Auto-detected interior floor bounds "
                  f"(union of {n_floor} floor prims {gate}, inset {floor_inset}): "
                  f"X=[{res_lo[0]:.2f},{res_hi[0]:.2f}] "
                  f"Y=[{res_lo[1]:.2f},{res_hi[1]:.2f}]")
            return res_lo, res_hi

        # Strategy 2: world bbox of the Replicator-loaded warehouse root.
        wall_inset = 1.0
        for root_path in ("/Replicator/Ref_Xform", "/World/warehouse",
                          "/Replicator", "/World"):
            root = stage.GetPrimAtPath(root_path)
            if not root or not root.IsValid():
                continue
            bb = _bbox_xy(root)
            if bb is None:
                continue
            lx, ly, hx, hy, lz, hz = bb
            if (hx - lx) < 4.0 or (hy - ly) < 4.0:
                continue
            res_lo = (lx + wall_inset, ly + wall_inset)
            res_hi = (hx - wall_inset, hy - wall_inset)
            print(f"[WARN] No floor prims matched; using world bbox of "
                  f"{root_path} (inset {wall_inset}): "
                  f"X=[{res_lo[0]:.2f},{res_hi[0]:.2f}] "
                  f"Y=[{res_lo[1]:.2f},{res_hi[1]:.2f}]")
            return res_lo, res_hi

        print("[WARN] _measure_floor_bounds: no floor prims and no warehouse "
              "root bbox available — falling back to JSON preset bounds.")
    except Exception as e:
        print(f"[WARN] _measure_floor_bounds failed: {e}")
    return None, None


def _affine_remap(pt, src_min, src_max, dst_min, dst_max):
    """Map a 2D point from one axis-aligned rectangle to another, per-axis."""
    out = []
    for i in (0, 1):
        s = src_max[i] - src_min[i]
        if s <= 1e-6:
            out.append(dst_min[i])
            continue
        t = (pt[i] - src_min[i]) / s
        out.append(dst_min[i] + t * (dst_max[i] - dst_min[i]))
    return tuple(out)

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
        "target_rack_height": preset.get("target_rack_height", "auto"),
        "aisle_width": preset.get("aisle_width", 2.5),
        "bounds_min": tuple(preset.get("bounds_min", [-12.0, -12.0])),
        "bounds_max": tuple(preset.get("bounds_max", [12.0, 12.0])),
        "clutter_density": preset.get("clutter_density", "high"),
        "clutter_zones": [dict(z) for z in preset.get("clutter_zones", [])],
        "pallet_rows": preset.get("pallet_rows", 3),
        "pallet_cols": preset.get("pallet_cols", 2),
        "rack_fill": preset.get("rack_fill", "medium"),
        "dock_area": preset.get("dock_area", False),
        "max_rows": preset.get("max_rows", 0),
        "max_cols": preset.get("max_cols", 0),
        "cross_aisle_every": preset.get("cross_aisle_every", 0),
        "cross_aisle_width": preset.get("cross_aisle_width", 3.5),
        "aisle_widths": preset.get("aisle_widths"),
        "dock_zone_frac": preset.get("dock_zone_frac", 0.25),
        "storage_zone_frac": preset.get("storage_zone_frac", 0.55),
    }
    if layout_params:
        for key in (
            "rack_pattern", "rack_rows", "rack_cols", "target_rack_height", "aisle_width",
            "bounds_min", "bounds_max", "clutter_density", "clutter_zones",
            "pallet_rows", "pallet_cols", "rack_fill", "dock_area",
            "max_rows", "max_cols", "cross_aisle_every", "cross_aisle_width",
            "aisle_widths", "dock_zone_frac", "storage_zone_frac",
        ):
            if key in layout_params:
                val = layout_params[key]
                if key in ("bounds_min", "bounds_max"):
                    params[key] = tuple(val)
                elif key == "clutter_zones":
                    params[key] = [dict(z) for z in val]
                elif key == "aisle_widths" and val is not None:
                    params[key] = list(val)
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
    
    # Rack height auto-derived from measured ceiling: aim to fill RACK_CEILING_FILL
    # of the interior height so racks read tall but leave headroom for ceiling
    # services (pipes, lights, sprinklers).
    ceiling_z = params.get("ceiling_z", DEFAULT_CEILING_Z)
    target_rack_height = params.get("target_rack_height")
    if target_rack_height in (None, "auto"):
        target_rack_height = ceiling_z * RACK_CEILING_FILL
    rack_base_height = 2.4  # measured height of SM_RackFrame_03 base mesh
    rack_z_scale = target_rack_height / rack_base_height
    params["_resolved_rack_height"] = target_rack_height

    rack_x_extent = RACK_X_EXTENT

    # --- Change 5: Variable aisle widths ---
    # Build per-gap aisle width list. If aisle_widths is provided, cycle through
    # it; otherwise fall back to the uniform aisle_width.
    aisle_widths_raw = params.get("aisle_widths")
    if aisle_widths_raw:
        aisle_widths_list = list(aisle_widths_raw)
    else:
        aisle_widths_list = None

    # --- Change 3: max_rows / max_cols clamp ---
    max_rows = params.get("max_rows", 0)
    max_cols = params.get("max_cols", 0)

    # --- Change 1: Cross-aisle parameters ---
    cross_every = params.get("cross_aisle_every", 0)
    cross_w = params.get("cross_aisle_width", 3.5)

    # --- Change 2: Functional zone Y boundaries ---
    # Allocate Y axis as: dock (front) | storage (middle) | bulk (back).
    # Racks only occupy the storage zone so workers/forklifts have a real
    # dock area instead of an empty floor behind the front wall.
    dock_frac = params.get("dock_zone_frac", 0.25)
    storage_frac = params.get("storage_zone_frac", 0.55)
    total_y_span = bmax[1] - bmin[1]
    dock_y_top = bmin[1] + dock_frac * total_y_span
    bulk_y_bottom = bmax[1] - (1.0 - dock_frac - storage_frac) * total_y_span

    # Default row_pitch used for auto-fit estimation and for non-"rows" patterns
    row_pitch = RACK_DEPTH + aw

    if cols == "auto" or cols is None:
        available_x = (bmax[0] - bmin[0]) - 2 * WALL_CLEARANCE
        cols = max(1, int(available_x / rack_x_extent))
    if max_cols > 0:
        cols = min(cols, max_cols)

    # Auto-fit rows: if aisle_widths is provided, use its average for estimation;
    # otherwise fall back to uniform aisle_width. This gives a better first
    # approximation when the user specifies a wide main aisle.
    storage_height = storage_frac * total_y_span
    if rows == "auto" or rows is None:
        available_y = storage_height - 2 * WALL_CLEARANCE
        if aisle_widths_list and len(aisle_widths_list) > 0:
            avg_aw = sum(aisle_widths_list) / len(aisle_widths_list)
        else:
            avg_aw = aw
        avg_row_pitch = RACK_DEPTH + avg_aw
        rows = max(1, int((available_y + avg_aw) / avg_row_pitch))
    if max_rows > 0:
        rows = min(rows, max_rows)

    # Hard clamp: averaging aisle widths under-counts when one aisle is wide
    # (e.g. [2.5, 4.0, 2.5]). Compute the *exact* row-block height for the
    # current `rows` count and shrink until it fits the storage zone — this
    # is what keeps racks from bleeding into the dock and bulk zones.
    def _row_block_height(n):
        if n <= 1:
            return RACK_DEPTH
        gaps = []
        for r in range(n - 1):
            if aisle_widths_list:
                gaps.append(aisle_widths_list[r % len(aisle_widths_list)])
            else:
                gaps.append(aw)
        return n * RACK_DEPTH + sum(gaps)

    storage_budget = storage_height - 2 * WALL_CLEARANCE
    while rows > 1 and _row_block_height(rows) > storage_budget:
        rows -= 1

    count = 0
    rack_positions = []

    if pattern == "none" or rows == 0:
        return idx, 0, rack_positions

    if pattern == "rows":
        # Rack rows running East-West, each with rack_cols racks placed
        # along X. Row spacing uses per-gap aisle_widths (Change 5) so one
        # wide main drive aisle can split two narrow picking aisles.
        # Racks are confined to the storage Y-zone (Change 2). Cross-aisles
        # (Change 1) break long rows into bays every cross_aisle_every columns.

        # --- Cross-aisle X span ---
        num_cross = ((cols - 1) // cross_every) if (cross_every > 0 and cols > 1) else 0
        total_x = max(0, cols - 1) * rack_x_extent + num_cross * cross_w
        x_start = (bmin[0] + bmax[0]) / 2.0 - total_x / 2.0

        # --- Row Y positions (Change 5: variable aisle, Change 2: zone reserve) ---
        storage_back_y = bulk_y_bottom - RACK_DEPTH / 2.0
        storage_front_y = dock_y_top + RACK_DEPTH / 2.0

        # Build cumulative Y positions. Row 0 (backmost) starts at storage_back_y,
        # each subsequent row steps by RACK_DEPTH + gap_width.
        first_row_y = storage_back_y
        row_ys = [first_row_y]
        for r in range(1, rows):
            if aisle_widths_list:
                gap = aisle_widths_list[(r - 1) % len(aisle_widths_list)]
            else:
                gap = aw
            row_ys.append(row_ys[-1] - (RACK_DEPTH + gap))

        # Center the row block within the storage zone so the layout breathes
        # instead of hugging the back wall.
        if rows > 1:
            row_block_top = row_ys[0] + RACK_DEPTH / 2.0
            row_block_bot = row_ys[-1] - RACK_DEPTH / 2.0
            row_center = (row_block_top + row_block_bot) / 2.0
            zone_center = (storage_back_y + storage_front_y) / 2.0
            y_shift = zone_center - row_center
            row_ys = [y + y_shift for y in row_ys]

        # Per-row bay variation: instead of breaking every row at the same
        # cross_aisle_every column (which produces identical 5+gap+2 rows),
        # randomize each row's break columns so adjacent rows show different
        # bay sizes. The total X span stays consistent so rows still align
        # to the same x_start.
        def _row_break_cols(num_breaks):
            if num_breaks <= 0 or cols <= 2:
                return set()
            interior = list(range(1, cols))
            random.shuffle(interior)
            picks = sorted(interior[:num_breaks])
            return set(picks)

        # Pick at most one row to drop a single column from — keeps the row
        # block from reading as a perfect rectangle without making every row
        # a different length (which is what produced the chaotic look).
        short_row = random.randrange(rows) if (rows >= 2 and cols >= 5) else -1

        for r in range(rows):
            y = row_ys[r]
            row_cols = cols - 1 if r == short_row else cols

            # Per-row break randomization: different bay split each row.
            row_breaks = _row_break_cols(num_cross)

            # Per-row x-stagger: small ragged-edge offset so rows don't form
            # a perfect grid, but small enough that rows still visually align
            # and the wall clamp below doesn't silently drop edge racks.
            row_x_stagger = random.uniform(-0.25, 0.25) if rows > 1 else 0.0

            x_offset = 0.0
            for c in range(row_cols):
                if c in row_breaks:
                    x_offset += cross_w
                x = x_start + c * rack_x_extent + x_offset + row_x_stagger
                # Bound check: don't push racks past the warehouse walls.
                if x < bmin[0] + WALL_CLEARANCE or x > bmax[0] - WALL_CLEARANCE:
                    continue
                idx = _place("rack", x, y, 0, 90, asset_library, stage, idx, scale=(1.0, 1.0, rack_z_scale))
                rack_positions.append((x, y, 90))
                count += 1

    elif pattern == "grid":
        num_cross_grid = ((cols - 1) // cross_every) if (cross_every > 0 and cols > 1) else 0
        total_x = max(0, cols - 1) * rack_x_extent + num_cross_grid * cross_w
        storage_back_y = bulk_y_bottom - RACK_DEPTH / 2.0
        storage_front_y = dock_y_top + RACK_DEPTH / 2.0
        x_start = (bmin[0] + bmax[0]) / 2.0 - total_x / 2.0
        # Use uniform aisle for grid — variable widths are a "rows" feature.
        total_y = (rows - 1) * row_pitch
        y_block_top = storage_back_y
        y_block_bot = y_block_top - total_y
        y_center = (y_block_top + y_block_bot) / 2.0
        zone_center = (storage_back_y + storage_front_y) / 2.0
        y_shift = zone_center - y_center
        for r in range(rows):
            for c in range(cols):
                x_offset = 0.0
                if c > 0 and cross_every > 0 and c % cross_every == 0:
                    x_offset += cross_w
                x = x_start + c * rack_x_extent + x_offset
                y = storage_back_y - r * row_pitch + y_shift
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


    print(f"[INFO] Rack layout: pattern={pattern}, rows={rows}, cols={cols}, "
          f"max_rows={max_rows}, max_cols={max_cols}, "
          f"aisle_widths={aisle_widths_list or [aw]}, cross_aisle_every={cross_every}, "
          f"dock_zone_frac={dock_frac:.0%}, storage_zone_frac={storage_frac:.0%}")
    return idx, count, rack_positions


def _populate_rack_shelves(rack_positions, params, asset_library, stage, idx):
    fill_level = params.get("rack_fill", "medium")
    fill_prob = RACK_FILL_PROBS.get(fill_level, 0.60)
    deck_count = 0
    cargo_count = 0
    has_shelf_asset = "rack_shelf" in asset_library
    
    # Use the rack height that _spawn_racks resolved (auto-scaled to ceiling).
    rack_height = params.get("_resolved_rack_height") or (
        params.get("ceiling_z", DEFAULT_CEILING_Z) * RACK_CEILING_FILL
    )
    shelf_spacing = max(0.7, rack_height * SHELF_PITCH_FRACTION)
    num_shelves = max(2, int(rack_height / shelf_spacing))
    shelf_heights = [0.15 + i * shelf_spacing for i in range(num_shelves)]

    has_pallet_asset = "pallet" in asset_library

    # Personality distribution for racks. Real warehouses don't have uniform
    # fill — some bays are empty (waiting put-away), some are overstocked
    # (double-stacked cargo), most are normal. Pick a personality per rack
    # and let it modulate fill probability, slot count, mix variety.
    #   empty       → no cargo at all (just decks)
    #   sparse      → one or two slots filled, lots of gaps
    #   normal      → fill_prob baseline
    #   overstocked → near-full + occasional double layer
    PERSONALITIES = [
        ("empty",       0.12),
        ("sparse",      0.18),
        ("normal",      0.52),
        ("overstocked", 0.18),
    ]
    def _pick_personality():
        roll = random.random()
        cum = 0.0
        for name, p in PERSONALITIES:
            cum += p
            if roll < cum:
                return name
        return "normal"

    for pos in rack_positions:
        # Tolerate older 2-tuple positions in case of partial upgrade.
        if len(pos) == 3:
            rx, ry, rrot = pos
        else:
            rx, ry = pos
            rrot = 90

        # Per-rack shelf z-jitter: shelves don't all sit at exactly the same
        # height across the warehouse. ±3cm reads as installation tolerance.
        rack_z_jitter = random.uniform(-0.03, 0.03)
        rack_shelf_zs = [sh + rack_z_jitter for sh in shelf_heights]

        # One shelf level per rack is randomly skipped to break up the uniform
        # vertical pattern across the warehouse.
        skip_level = random.randint(0, len(rack_shelf_zs) - 1) if (
            len(rack_shelf_zs) > 1 and random.random() < 0.35
        ) else -1
        rack_shelf_heights = [
            sh for i, sh in enumerate(rack_shelf_zs) if i != skip_level
        ]

        if has_shelf_asset:
            for shelf_z in rack_shelf_heights:
                idx = _place("rack_shelf", rx, ry, shelf_z, rrot, asset_library, stage, idx)
                deck_count += 1

        if fill_prob <= 0.0:
            continue

        personality = _pick_personality()
        if personality == "empty":
            # No cargo at all — bay reads as awaiting put-away.
            continue
        elif personality == "sparse":
            rack_fill_prob = max(0.10, min(0.45, fill_prob * 0.4))
            allow_double = False
        elif personality == "overstocked":
            rack_bias = random.gauss(0.10, 0.10)
            rack_fill_prob = max(0.0, min(1.0, fill_prob + 0.20 + rack_bias))
            allow_double = True
        else:
            rack_bias = random.gauss(0.0, 0.20)
            rack_fill_prob = max(0.0, min(1.0, fill_prob + rack_bias))
            allow_double = random.random() < 0.10

        # SKU mixing: most racks have a dominant SKU, but ~25% are mixed
        # (multiple suppliers / consolidation bay).
        if random.random() < 0.25:
            primary_prop = None  # signal to randomize per-slot
        else:
            primary_prop = random.choice(SHELF_PROPS)
        rack_uses_pallets = has_pallet_asset and random.random() < 0.55

        ang = math.radians(rrot)
        cos_a, sin_a = math.cos(ang), math.sin(ang)
        for shelf_z in rack_shelf_heights:
            # Some shelves on a rack are completely empty even within a
            # non-empty rack — partial put-away pattern.
            if random.random() < 0.18:
                continue
            for slot in range(SHELF_POSITIONS_PER_LEVEL):
                if random.random() > rack_fill_prob:
                    continue
                if primary_prop is None:
                    prop = random.choice(SHELF_PROPS)
                else:
                    prop = primary_prop if random.random() < 0.75 else random.choice(SHELF_PROPS)
                slot_frac = (slot + 0.5) / SHELF_POSITIONS_PER_LEVEL  # 0..1
                local_along = (slot_frac - 0.5) * 2.2 + random.uniform(-0.12, 0.12)
                local_depth = random.uniform(-0.18, 0.18)
                world_dx = local_along * cos_a - local_depth * sin_a
                world_dy = local_along * sin_a + local_depth * cos_a
                x = rx + world_dx
                y = ry + world_dy
                z_base = shelf_z + random.uniform(-0.02, 0.02)
                if rack_uses_pallets:
                    idx = _place("pallet", x, y, z_base, rrot, asset_library, stage, idx)
                    cargo_count += 1
                    z_box = z_base + 0.14
                else:
                    z_box = z_base
                # Wider rotation envelope on overstocked / mixed bays —
                # cargo gets nudged out of square when crammed in.
                rot_envelope = 25 if (allow_double or primary_prop is None) else 15
                rot = rrot + random.uniform(-rot_envelope, rot_envelope)
                idx = _place(prop, x, y, z_box, rot, asset_library, stage, idx)
                cargo_count += 1
                # Overstocked bays get a 2nd cargo layer occasionally —
                # double-stacked / piled higher than the shelf was designed for.
                if allow_double and random.random() < 0.35:
                    prop2 = random.choice(SHELF_PROPS)
                    idx = _place(prop2, x + random.uniform(-0.08, 0.08),
                                 y + random.uniform(-0.08, 0.08),
                                 z_box + 0.32,
                                 rot + random.uniform(-10, 10),
                                 asset_library, stage, idx)
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

    # Pallet staging lives in the dock zone (front of the warehouse) so
    # forklifts have a natural reason to operate there.
    dock_frac = params.get("dock_zone_frac", 0.25)
    total_y_span = bmax[1] - bmin[1]
    dock_y_top = bmin[1] + dock_frac * total_y_span
    spacing_x = 2.0
    spacing_y = 2.5
    total_x = (pallet_cols_grid - 1) * spacing_x
    total_y_pal = (pallet_rows_grid - 1) * spacing_y
    x_start = (bmin[0] + bmax[0]) / 2.0 - total_x / 2.0
    y_center = (bmin[1] + dock_y_top) / 2.0
    y_start = y_center + total_y_pal / 2.0

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

    # Zone-ownership guard: when dock_area=True, _spawn_dock_area is the
    # canonical populator for the dock Y-band. Skip any clutter zone that
    # sits mostly inside that band so the LLM-generated "dock_staging" zone
    # doesn't overlay the dock layout with another 30 props.
    has_dock = params.get("dock_area", False)
    dock_y_top = None
    if has_dock:
        dock_frac = params.get("dock_zone_frac", 0.25)
        dock_y_top = bmin[1] + dock_frac * (bmax[1] - bmin[1])

    def _zone_in_dock_band(zmin, zmax):
        if dock_y_top is None:
            return False
        zone_h = max(1e-3, zmax[1] - zmin[1])
        # Fraction of the zone's Y span that falls below dock_y_top.
        overlap = max(0.0, min(zmax[1], dock_y_top) - zmin[1])
        return (overlap / zone_h) >= 0.6

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
            if _zone_in_dock_band(zbmin, zbmax):
                print(f"[INFO] Skipping clutter_zone '{zone.get('area', '?')}' "
                      f"— overlaps dock band (owned by _spawn_dock_area)")
                continue
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
    """Populate the reserved dock zone with content that reads as a dock —
    not as another rack row.

    Dock zones in real warehouses are dominated by *open floor* (forklift
    turning radius) with discrete staging clusters in front of each dock
    door. The polish pass already paints hazard hatches, dock-leveler
    plates, and bollards at the door line; this function adds:
      - One small staging cluster (2–4 pallets, irregular, not gridded)
        per door, set back from the door itself so bollards/hatches stay
        visible
      - An empty-pallet stack near a side wall (returns)
      - 1–2 hand-truck-ish stubs (drums / cones) in the open apron
      - A few cones along the apron edge to mark the lane

    The middle of the zone is left intentionally open. That open apron is
    what visually distinguishes the dock from the dense racked storage
    zone behind it.
    """
    bmin = params["bounds_min"]
    bmax = params["bounds_max"]
    count = 0

    dock_frac = params.get("dock_zone_frac", 0.25)
    total_y_span = bmax[1] - bmin[1]
    dock_y_top = bmin[1] + dock_frac * total_y_span

    # Front-wall setback covers door / leveler / hatch / bollard line.
    dock_y_door = bmin[1] + 1.6
    # Staging clusters sit between the door line and the storage boundary,
    # but only in the back-half of the dock zone — front-half stays open
    # for trucks backing in / forklift apron.
    dock_y_apron = (dock_y_door + dock_y_top) / 2.0
    dock_y_stage_lo = dock_y_apron + 0.2
    dock_y_stage_hi = dock_y_top - 1.0

    span_x = bmax[0] - bmin[0]
    dock_x_start = bmin[0] + 0.10 * span_x
    dock_x_end = bmax[0] - 0.10 * span_x
    avail_x = dock_x_end - dock_x_start
    avail_y = dock_y_stage_hi - dock_y_stage_lo
    if avail_x < 3.0 or avail_y < 1.0:
        print(f"[INFO] Dock zone too small (avail_x={avail_x:.2f}, "
              f"avail_y={avail_y:.2f}) — skipping dock fill")
        return idx, count

    # The polish pass places dock doors at fractions 0.25 / 0.5 / 0.75 of the
    # bounds X range. Mirror that here so each cluster lines up with a door.
    door_fracs = (0.25, 0.5, 0.75)
    door_xs = [bmin[0] + f * span_x for f in door_fracs]

    # Drop a 0–1 cluster gap at random so one door reads as "currently in use"
    # (truck backed in, no staged pallets in front of it).
    active_door = random.choice(door_fracs)

    has_pallet = "pallet" in asset_library
    box_props = [p for p in ("box", "box_small", "crate") if p in asset_library]

    for door_x, frac in zip(door_xs, door_fracs):
        if frac == active_door:
            continue  # leave this door's apron open
        if not has_pallet:
            continue
        # 2–4 pallets in an irregular cluster behind the door, NOT a grid.
        cluster_n = random.randint(2, 4)
        cluster_cy = random.uniform(dock_y_stage_lo, dock_y_stage_hi - 0.1)
        for _ in range(cluster_n):
            px = door_x + random.uniform(-1.0, 1.0)
            py = cluster_cy + random.uniform(-0.6, 0.6)
            # Clamp to dock zone X bounds.
            px = max(dock_x_start, min(dock_x_end, px))
            py = max(dock_y_stage_lo, min(dock_y_stage_hi, py))
            idx = _place("pallet", px, py, 0, random.uniform(-20, 20),
                         asset_library, stage, idx)
            count += 1
            # Roughly half the staged pallets carry an outbound order
            # (1–2 boxes, no tall stacks — that's the storage-zone look).
            roll = random.random()
            if roll < 0.55 and box_props:
                idx = _place(random.choice(box_props),
                             px + random.uniform(-0.10, 0.10),
                             py + random.uniform(-0.10, 0.10),
                             0.14, random.uniform(0, 360),
                             asset_library, stage, idx)
                count += 1
                if random.random() < 0.35:
                    idx = _place(random.choice(box_props),
                                 px + random.uniform(-0.12, 0.12),
                                 py + random.uniform(-0.12, 0.12),
                                 0.42, random.uniform(0, 360),
                                 asset_library, stage, idx)
                    count += 1

    # Empty-pallet stack tucked against one wall (returns / dunnage).
    if has_pallet:
        wall_side = random.choice((-1, 1))
        ep_x = (bmin[0] + 1.4) if wall_side < 0 else (bmax[0] - 1.4)
        ep_y = random.uniform(dock_y_stage_lo, dock_y_stage_hi)
        idx, n = _place_empty_pallet_stack(stage, idx, ep_x, ep_y,
                                           asset_library,
                                           count=random.randint(4, 7),
                                           rot_z=random.uniform(-8, 8))
        count += n

    # Apron edge cones — a sparse line marking where the staging band ends
    # and the truck apron begins. Reads as "do not stage past this line".
    if "cone" in asset_library:
        n_cones = max(3, int(span_x / 3.5))
        for c in range(n_cones):
            cx = dock_x_start + (c + 0.5) * (avail_x / n_cones)
            cy = dock_y_apron + random.uniform(-0.15, 0.15)
            idx = _place("cone", cx + random.uniform(-0.25, 0.25), cy,
                         0, random.uniform(0, 360), asset_library, stage, idx)
            count += 1

    # 2–3 stray drums / barrels in the apron — not a cluster, just litter.
    drum_props = [p for p in ("barrel", "drum") if p in asset_library]
    if drum_props:
        for _ in range(random.randint(2, 3)):
            sx = random.uniform(dock_x_start + 0.5, dock_x_end - 0.5)
            sy = random.uniform(dock_y_door + 0.4, dock_y_apron - 0.3)
            idx = _place(random.choice(drum_props), sx, sy, 0.15,
                         random.uniform(0, 360), asset_library, stage, idx)
            count += 1

    print(f"[INFO] Spawned dock area with {count} items "
          f"(active_door_frac={active_door})")
    return idx, count


def _spawn_bulk_stock(params, asset_library, stage, idx):
    """Fill the bulk-stock zone (back of warehouse, behind rack rows) with
    irregular clusters of palletised stock — overflow from racked storage.
    Without this the back ~20% of the floor reads as a bare strip."""
    if "pallet" not in asset_library:
        return idx, 0
    bmin = params["bounds_min"]
    bmax = params["bounds_max"]
    dock_frac = params.get("dock_zone_frac", 0.25)
    storage_frac = params.get("storage_zone_frac", 0.55)
    bulk_frac = 1.0 - dock_frac - storage_frac
    if bulk_frac < 0.05:
        return idx, 0

    total_y_span = bmax[1] - bmin[1]
    bulk_y_bottom = bmax[1] - bulk_frac * total_y_span
    bulk_y_top = bmax[1] - 1.2  # back-wall clearance
    bulk_y_bot = bulk_y_bottom + 0.6
    span_x = bmax[0] - bmin[0]
    bulk_x_start = bmin[0] + 0.08 * span_x
    bulk_x_end = bmax[0] - 0.08 * span_x

    avail_y = max(0.0, bulk_y_top - bulk_y_bot)
    avail_x = max(0.0, bulk_x_end - bulk_x_start)
    if avail_x < 2.0 or avail_y < 1.5:
        return idx, 0

    count = 0
    # Build 2–3 cluster centres along X, then drop a small irregular
    # rectangle of pallets around each centre. Clusters of varying sizes
    # break the grid look; the empty between them reads as a forklift lane.
    # Capped at 3 clusters to keep total prim count bounded.
    n_clusters = random.randint(2, 3)
    cluster_xs = sorted(
        random.uniform(bulk_x_start + 1.0, bulk_x_end - 1.0)
        for _ in range(n_clusters)
    )
    for cx in cluster_xs:
        # Cluster footprint: 2-3 wide × 1-2 deep.
        cw = random.randint(2, 3)
        cd = random.randint(1, 2) if avail_y >= 3.0 else 1
        spacing_x = 1.6
        spacing_y = 1.6
        cluster_w = (cw - 1) * spacing_x
        cluster_d = (cd - 1) * spacing_y
        if cx - cluster_w / 2.0 < bulk_x_start or cx + cluster_w / 2.0 > bulk_x_end:
            continue
        cy = (bulk_y_bot + bulk_y_top) / 2.0 + random.uniform(-0.4, 0.4)
        x0 = cx - cluster_w / 2.0
        y0 = cy - cluster_d / 2.0
        for r in range(cd):
            for c in range(cw):
                if random.random() < 0.18:
                    continue
                x = x0 + c * spacing_x + random.uniform(-0.15, 0.15)
                y = y0 + r * spacing_y + random.uniform(-0.15, 0.15)
                rot = random.uniform(-12, 12)
                idx = _place("pallet", x, y, 0, rot, asset_library, stage, idx)
                count += 1
                # Bulk stock is taller / heavier — favour tall stacks and drums.
                roll = random.random()
                if roll < 0.55:
                    idx, n = _stack_boxes(x, y, (1.0, 0.85, 0.55), (0.08, 0.08, 0.10),
                                          asset_library, stage, idx)
                    count += n
                elif roll < 0.80 and "drum" in asset_library:
                    idx = _place("drum", x, y, 0.15, random.uniform(0, 360),
                                 asset_library, stage, idx)
                    count += 1
                    if random.random() < 0.5:
                        idx = _place("drum", x + random.uniform(-0.05, 0.05),
                                     y + random.uniform(-0.05, 0.05), 0.55,
                                     random.uniform(0, 360), asset_library, stage, idx)
                        count += 1

    print(f"[INFO] Spawned bulk stock with {count} items across {n_clusters} clusters")
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

    # Functional-zone boundary stripes — make dock / storage / bulk split
    # readable at a glance. Bands derive from the same dock_zone_frac /
    # storage_zone_frac params used by _spawn_racks, so they always line up
    # with the actual rack-block edges.
    dock_frac = params.get("dock_zone_frac", 0.25)
    storage_frac = params.get("storage_zone_frac", 0.55)
    bulk_frac = max(0.0, 1.0 - dock_frac - storage_frac)
    span_y = bmax[1] - bmin[1]
    span_x = bmax[0] - bmin[0]
    cx = (bmin[0] + bmax[0]) / 2.0
    stripe_len = span_x - 2 * margin
    # Yellow/black contrast pair: a thicker outer band + a thinner inner
    # band painted on top so the boundary reads as a hazard line.
    boundary_outer = (0.95, 0.80, 0.10)
    boundary_inner = (0.10, 0.10, 0.10)

    def _paint_boundary(y):
        nonlocal idx, count
        idx = _paint_floor_stripe(stage, idx, cx, y, stripe_len, 0.30,
                                  boundary_outer)
        count += 1
        idx = _paint_floor_stripe(stage, idx, cx, y, stripe_len, 0.10,
                                  boundary_inner, z=0.014)
        count += 1

    if dock_frac > 0.05:
        _paint_boundary(bmin[1] + dock_frac * span_y)
    if bulk_frac > 0.05:
        _paint_boundary(bmax[1] - bulk_frac * span_y)

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

    Zone ownership: each functional Y-band has a single canonical populator.
    `_spawn_dock_area` owns the dock zone, `_spawn_bulk_stock` owns the bulk
    zone, and the preset's `clutter_zones` (left_wall_stash / right_wall_stash)
    own the side strips. This function only fills the *gap* between the rack
    block and the storage-zone boundaries, plus the side strips when no
    preset clutter zone covers them — so it can never overlay the dock or
    bulk owners with a competing pallet grid.
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
    dock_frac = params.get("dock_zone_frac", 0.25)
    storage_frac = params.get("storage_zone_frac", 0.55)
    bulk_frac = max(0.0, 1.0 - dock_frac - storage_frac)
    total_y_span = bmax[1] - bmin[1]
    dock_y_top = bmin[1] + dock_frac * total_y_span
    bulk_y_bottom = bmax[1] - bulk_frac * total_y_span

    # Side strips have a preset owner if any clutter_zone overlaps them.
    side_clutter_zones = params.get("clutter_zones", []) or []
    def _strip_has_preset_owner(x_lo, x_hi, y_lo, y_hi):
        for z in side_clutter_zones:
            zmin = z.get("bounds_min")
            zmax = z.get("bounds_max")
            if zmin is None or zmax is None:
                continue
            # Axis-aligned overlap test.
            if zmax[0] >= x_lo and zmin[0] <= x_hi and \
               zmax[1] >= y_lo and zmin[1] <= y_hi:
                return True
        return False

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

    # ---------- 1) FRONT STAGING (between racks and dock zone) ----------
    # Only fills the *gap* between the rack block and dock_y_top — never the
    # dock zone itself (owned by _spawn_dock_area when dock_area=True). When
    # no dock zone is configured, falls back to filling all the way to the
    # front wall so non-dock presets still get foreground content.
    front_y_max = rzone_ymin - 0.6
    front_y_min = (dock_y_top + 0.4) if has_dock else (bmin[1] + 1.5)
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
                if random.random() < 0.85:
                    _drop_loaded_pallet(px, py)

        # A drum cluster at the front-right (only when no dock owns the band).
        if not has_dock:
            cluster_x = bmax[0] - 2.5
            cluster_y = (front_y_min + front_y_max) / 2.0
            for _ in range(random.randint(6, 10)):
                dx = cluster_x + random.uniform(-1.4, 1.4)
                dy = cluster_y + random.uniform(-1.4, 1.4)
                _drop_drum(dx, dy)

    # ---------- 2) LEFT-WALL STASH (between racks and -X wall) ----------
    left_x_max = rzone_xmin - 0.6
    left_x_min = bmin[0] + 1.0
    if left_x_max > left_x_min + 0.8 and \
       not _strip_has_preset_owner(left_x_min, left_x_max, rzone_ymin, rzone_ymax):
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
    if right_x_max > right_x_min + 0.8 and \
       not _strip_has_preset_owner(right_x_min, right_x_max, rzone_ymin, rzone_ymax):
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

    # ---------- 4) BACK STRIP (between racks and bulk zone) ----------
    # Only fills the gap between the rack block and bulk_y_bottom. The bulk
    # zone proper is owned by _spawn_bulk_stock (irregular clusters with
    # forklift lanes), so we never overlay a random pallet field on top of it.
    back_y_min = rzone_ymax + 0.6
    back_y_max = (bulk_y_bottom - 0.4) if bulk_frac >= 0.05 else (bmax[1] - 0.8)
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

    ceiling_z = params.get("ceiling_z", DEFAULT_CEILING_Z)

    # 1) Ceiling pipe runs along Y — three parallel pipes, slightly different colors.
    pipe_ys = [bmin[1] + 1.5, cy, bmax[1] - 1.5]
    pipe_colors = [(0.55, 0.30, 0.18), (0.20, 0.32, 0.55), (0.70, 0.70, 0.65)]
    pipe_z = ceiling_z - 0.25
    for py, pcol in zip(pipe_ys, pipe_colors):
        idx = _place_ceiling_pipe_run(stage, idx, bmin[0] + 0.3, bmax[0] - 0.3,
                                       py, z=pipe_z, color=pcol)
        count += 1

    # 2) Sprinkler grid on the ceiling — ~3.5m spacing.
    nx = max(2, int((bmax[0] - bmin[0]) / 3.5))
    ny = max(2, int((bmax[1] - bmin[1]) / 3.5))
    sprinkler_z = ceiling_z - 0.05
    for i in range(nx):
        for j in range(ny):
            sx = bmin[0] + (i + 0.5) * (bmax[0] - bmin[0]) / nx
            sy = bmin[1] + (j + 0.5) * (bmax[1] - bmin[1]) / ny
            idx = _place_sprinkler_head(stage, idx, sx, sy, z=sprinkler_z)
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
    light_zs = params.get("ceiling_z", DEFAULT_CEILING_Z) - 0.15
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
        # Hang aisle signs ~1m below the ceiling so they read as suspended.
        sign_z = params.get("ceiling_z", DEFAULT_CEILING_Z) - 1.0
        idx = _place_aisle_sign(stage, idx, cx, ay, color, z=sign_z)
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
    """Traffic-pattern wear:
      • Main drive aisle (widest gap) gets full-length heavy double tracks.
      • Picking aisles get lighter, intermittent scuffs.
      • Rack-end turnarounds get extra dense scuffing where forklifts pivot.
      • Oil drips concentrate in the main aisle, not random side aisles.
    """
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
    aisle_info = []
    for i in range(len(sorted_ys) - 1):
        y_a, y_b = sorted_ys[i], sorted_ys[i + 1]
        gap = abs(y_b - y_a) - RACK_DEPTH
        y_mid = (y_a + y_b) / 2.0
        xs = rows[y_a] + rows[y_b]
        x_lo, x_hi = min(xs) - 0.8, max(xs) + 0.8
        aisle_info.append({"y": y_mid, "x_lo": x_lo, "x_hi": x_hi, "gap": gap})

    if not aisle_info:
        return idx, 0

    # Identify the main aisle: widest gap. Everything else is a picker.
    main_aisle = max(aisle_info, key=lambda a: a["gap"])
    count = 0

    for a in aisle_info:
        is_main = a is main_aisle
        x_mid = (a["x_lo"] + a["x_hi"]) / 2.0
        length = a["x_hi"] - a["x_lo"]
        if is_main:
            # Two full-length wheel tracks, slightly wider apart (heavier veh.).
            for offset in (-0.55, 0.55):
                idx = _place_tire_scuff(stage, idx, x_mid, a["y"] + offset,
                                        length, rot_z=0)
                count += 1
            # A faint third "trail" off-center where forks scrape on turn-in.
            if random.random() < 0.5:
                idx = _place_tire_scuff(stage, idx, x_mid,
                                        a["y"] + random.choice([-0.20, 0.20]),
                                        length * 0.6, rot_z=0)
                count += 1
        else:
            # Picker aisles: lighter, shorter intermittent scuffs (foot/walk
            # behind not constant traffic). 60% chance the picker has any
            # visible track at all.
            if random.random() < 0.6:
                seg_len = length * random.uniform(0.4, 0.7)
                seg_x = x_mid + random.uniform(-length * 0.15, length * 0.15)
                offset = random.choice([-0.40, 0.40])
                idx = _place_tire_scuff(stage, idx, seg_x, a["y"] + offset,
                                        seg_len, rot_z=0)
                count += 1

    # Rack-end turnaround scuffs: forklifts pivot at the end of every aisle,
    # creating dense overlapping scuffing 1–2 rack-widths out from the row
    # endpoints. Place a short transverse scuff at each row's leftmost and
    # rightmost rack.
    for ry_key, xs in rows.items():
        for end_x in (min(xs) - 1.4, max(xs) + 1.4):
            if random.random() < 0.55:
                idx = _place_tire_scuff(stage, idx, end_x, ry_key,
                                        1.4, rot_z=90 + random.uniform(-15, 15))
                count += 1

    # Oil stains: prefer the main aisle, with one plausible drip path.
    n_stains = random.randint(2, 3)
    for _ in range(n_stains):
        if random.random() < 0.75:  # main aisle bias
            ox = random.uniform(main_aisle["x_lo"] + 1.0, main_aisle["x_hi"] - 1.0)
            oy = main_aisle["y"] + random.uniform(-0.25, 0.25)
            radius = random.uniform(0.28, 0.45)
        else:
            a = random.choice(aisle_info)
            ox = random.uniform(a["x_lo"] + 1.0, a["x_hi"] - 1.0)
            oy = a["y"] + random.uniform(-0.20, 0.20)
            radius = random.uniform(0.20, 0.30)
        idx = _place_oil_stain(stage, idx, ox, oy, radius=radius)
        count += 1

    return idx, count


def _spawn_main_aisle_treatment(rack_positions, params, asset_library, stage, idx):
    """Identify the main drive aisle (widest gap between rows) and dress it
    so it visibly reads as the primary thoroughfare:
      • Heavy yellow centerline stripe down its length (in addition to the
        two parallel edge stripes from _spawn_floor_markings).
      • Hi-vis bollards or cones at both ends to channel traffic.
      • A coloured aisle name sign hung overhead.
      • Floor direction arrows at the entrance.
    Without this, every aisle reads identically and there's no visible
    'main area' for forklifts to traverse.
    """
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
    if len(sorted_ys) < 2:
        return idx, 0

    aisles = []
    for i in range(len(sorted_ys) - 1):
        y_a, y_b = sorted_ys[i], sorted_ys[i + 1]
        gap = abs(y_b - y_a) - RACK_DEPTH
        y_mid = (y_a + y_b) / 2.0
        xs = rows[y_a] + rows[y_b]
        x_lo, x_hi = min(xs) - 0.9, max(xs) + 0.9
        aisles.append({"y": y_mid, "x_lo": x_lo, "x_hi": x_hi, "gap": gap})

    main = max(aisles, key=lambda a: a["gap"])
    count = 0

    # Heavy yellow centerline (in addition to the existing edge stripes).
    yellow_hi = (0.97, 0.84, 0.10)
    cx = (main["x_lo"] + main["x_hi"]) / 2.0
    length = main["x_hi"] - main["x_lo"]
    idx = _paint_floor_stripe(stage, idx, cx, main["y"],
                              length, 0.20, yellow_hi, z=0.014)
    count += 1

    # Bollards / cones at each end of the main aisle to channel approach.
    for end_x in (main["x_lo"] - 0.8, main["x_hi"] + 0.8):
        if abs(end_x - bmin[0]) < 0.5 or abs(end_x - bmax[0]) < 0.5:
            continue  # too close to wall
        idx = _place_hi_vis_bollard(stage, idx, end_x, main["y"] - 0.6, height=0.95)
        idx = _place_hi_vis_bollard(stage, idx, end_x, main["y"] + 0.6, height=0.95)
        count += 2
        if "cone" in asset_library:
            idx = _place("cone", end_x + 0.4 * (1 if end_x > cx else -1),
                         main["y"], 0, 0, asset_library, stage, idx)
            count += 1

    # Overhead aisle sign — orange band so it stands out from the picker
    # signs already placed by realism extras.
    sign_z = params.get("ceiling_z", DEFAULT_CEILING_Z) - 1.0
    idx = _place_aisle_sign(stage, idx, cx, main["y"], (0.95, 0.45, 0.05), z=sign_z)
    count += 2

    # Floor direction arrows at the entrance from the dock side.
    arrow_y = main["y"] - 1.0 if main["y"] > 0 else main["y"] + 1.0
    idx = _place_floor_arrow(stage, idx, cx - 1.5, arrow_y, rot_z=0)
    idx = _place_floor_arrow(stage, idx, cx + 1.5, arrow_y, rot_z=0)
    count += 2

    print(f"[INFO] Main drive aisle identified at y={main['y']:.2f} "
          f"(gap={main['gap']:.2f}m), {count} treatment items spawned")
    return idx, count


def _spawn_marshalling_band(params, asset_library, stage, idx):
    """A 'staging lane' band between the dock zone and the rack zone —
    pallets organised in two parallel lanes pointing toward the dock,
    with cones marking the lane boundary. Reads as outbound marshalling /
    pre-shipping area where pickers drop completed orders for forklift
    pickup."""
    if "pallet" not in asset_library:
        return idx, 0
    bmin = params["bounds_min"]
    bmax = params["bounds_max"]
    dock_frac = params.get("dock_zone_frac", 0.25)
    total_y_span = bmax[1] - bmin[1]
    dock_y_top = bmin[1] + dock_frac * total_y_span
    # Marshalling band sits entirely on the storage side of the dock/storage
    # boundary so it doesn't overlap the dock-area cluster pattern. ~1m thick
    # band starting just inside the storage zone.
    band_y_lo = dock_y_top + 0.2
    band_y_hi = dock_y_top + 1.4
    if band_y_hi - band_y_lo < 1.0:
        return idx, 0
    span_x = bmax[0] - bmin[0]
    band_x_start = bmin[0] + 0.18 * span_x
    band_x_end = bmax[0] - 0.18 * span_x
    avail_x = band_x_end - band_x_start
    if avail_x < 4.0:
        return idx, 0

    # Two parallel lanes of palletised orders.
    lane_ys = [band_y_lo + 0.4, band_y_hi - 0.4]
    spacing = 1.7
    n_pallets = max(2, min(6, int(avail_x / spacing)))
    grid_x = (n_pallets - 1) * spacing
    x0 = (band_x_start + band_x_end) / 2.0 - grid_x / 2.0
    count = 0
    box_props = [p for p in ("box", "box_small", "crate") if p in asset_library]

    for ly in lane_ys:
        for c in range(n_pallets):
            if random.random() < 0.20:
                continue  # gap = active picking lane
            x = x0 + c * spacing + random.uniform(-0.18, 0.18)
            y = ly + random.uniform(-0.10, 0.10)
            idx = _place("pallet", x, y, 0, random.uniform(-10, 10),
                         asset_library, stage, idx)
            count += 1
            # Outbound: usually has 1–2 boxes representing a completed order.
            if box_props and random.random() < 0.85:
                idx = _place(random.choice(box_props),
                             x + random.uniform(-0.10, 0.10),
                             y + random.uniform(-0.10, 0.10),
                             0.14, random.uniform(0, 360),
                             asset_library, stage, idx)
                count += 1
                if random.random() < 0.45:
                    idx = _place(random.choice(box_props),
                                 x + random.uniform(-0.12, 0.12),
                                 y + random.uniform(-0.12, 0.12),
                                 0.42, random.uniform(0, 360),
                                 asset_library, stage, idx)
                    count += 1

    # Cones along the centerline between the two lanes — separates lane
    # traffic, makes the band read as a worked-on staging area.
    if "cone" in asset_library:
        cone_y = (lane_ys[0] + lane_ys[1]) / 2.0
        cone_spacing = max(2.0, avail_x / 5.0)
        n_cones = max(2, int(avail_x / cone_spacing))
        for c in range(n_cones):
            cx = band_x_start + (c + 0.5) * (avail_x / n_cones)
            idx = _place("cone", cx + random.uniform(-0.2, 0.2),
                         cone_y + random.uniform(-0.1, 0.1),
                         0, 0, asset_library, stage, idx)
            count += 1

    print(f"[INFO] Spawned marshalling band with {count} items")
    return idx, count


def _spawn_human_imperfection(rack_positions, params, asset_library, stage, idx):
    """Small 'someone was just here' details that sell realism harder than
    any layout-level structure. Examples:
      • Crooked pallets parked off-square against rack faces
      • A box on the floor next to (not on) a pallet — dropped
      • A tipped cone
      • A small carton 'spilled' next to a rack upright
      • Items leaning against rack legs
    """
    if not rack_positions:
        return idx, 0
    has_box = "box" in asset_library or "box_small" in asset_library
    has_pallet = "pallet" in asset_library
    has_cone = "cone" in asset_library
    has_crate = "crate" in asset_library

    bmin = params["bounds_min"]
    bmax = params["bounds_max"]

    # Group racks by row to find aisle midlines and rack endpoints.
    rows = {}
    for (rx, ry, rrot) in rack_positions:
        if rrot == 90:
            key = round(ry * 2) / 2.0
            rows.setdefault(key, []).append(rx)
    sorted_ys = sorted(rows.keys())
    aisle_mids = []
    for i in range(len(sorted_ys) - 1):
        y_mid = (sorted_ys[i] + sorted_ys[i + 1]) / 2.0
        aisle_mids.append((y_mid, sorted_ys[i], sorted_ys[i + 1]))

    count = 0
    box_props = [p for p in ("box", "box_small", "crate") if p in asset_library]
    if not box_props:
        box_props = ["box"]

    # 1. Crooked pallets parked askew against a rack face. 2-4 across the
    #    warehouse. Sit at the front edge of a rack with 8-25° rotation off
    #    the rack's long axis.
    if has_pallet and aisle_mids:
        for _ in range(random.randint(2, 4)):
            y_mid, ya, yb = random.choice(aisle_mids)
            face_y_choice = random.choice([ya, yb])
            xs = rows[face_y_choice]
            x_pick = random.choice(xs) + random.uniform(-0.4, 0.4)
            # Pallet sits in the aisle, just in front of the rack face.
            offset_into_aisle = random.uniform(0.55, 0.95)
            if face_y_choice == ya:
                py = ya - offset_into_aisle  # ya is the back row → step toward y_mid
                if ya > y_mid:
                    py = ya - offset_into_aisle
                else:
                    py = ya + offset_into_aisle
            else:
                if yb > y_mid:
                    py = yb - offset_into_aisle
                else:
                    py = yb + offset_into_aisle
            crooked_rot = 90 + random.uniform(-25, 25)
            idx = _place("pallet", x_pick, py, 0, crooked_rot, asset_library, stage, idx)
            count += 1
            # Half the time the crooked pallet has cargo, half the time it's
            # bare (someone dropped it and walked away).
            if random.random() < 0.5 and box_props:
                idx = _place(random.choice(box_props),
                             x_pick + random.uniform(-0.10, 0.10),
                             py + random.uniform(-0.10, 0.10),
                             0.14, crooked_rot + random.uniform(-15, 15),
                             asset_library, stage, idx)
                count += 1

    # 2. Dropped box on the floor next to a pallet location — outside the
    #    rack footprint. Place a small box at a random rack endpoint.
    if box_props and rack_positions:
        for _ in range(random.randint(1, 3)):
            rx, ry, _ = random.choice(rack_positions)
            # Off the end of the rack in +X or -X, on the floor.
            dx = random.choice([-1.6, 1.6]) + random.uniform(-0.2, 0.2)
            dy = random.uniform(-0.4, 0.4)
            prop = random.choice(box_props)
            # Tilt slightly — box landed askew.
            rot = random.uniform(0, 360)
            idx = _place(prop, rx + dx, ry + dy, 0, rot, asset_library, stage, idx)
            count += 1

    # 3. Tipped / fallen cone — 50% chance of one tipped cone somewhere.
    if has_cone and random.random() < 0.6:
        rx, ry, _ = random.choice(rack_positions)
        cx = rx + random.uniform(-1.8, 1.8)
        cy = ry + random.uniform(0.7, 1.4) * random.choice([-1, 1])
        # Lay cone on its side: pitch ~85° from upright.
        idx = _place("cone", cx, cy, 0.12, random.uniform(0, 360),
                     asset_library, stage, idx, scale=(1.0, 1.0, 1.0))
        count += 1

    # 4. Spilled carton next to a rack upright — small box partially out
    #    onto the floor with a sibling box already fallen.
    if box_props and rack_positions and random.random() < 0.7:
        rx, ry, _ = random.choice(rack_positions)
        upright_x = rx + random.choice([-1.4, 1.4])
        upright_y = ry
        # Spilled main box, leaning.
        idx = _place(random.choice(box_props),
                     upright_x + random.uniform(-0.15, 0.15),
                     upright_y + random.uniform(0.3, 0.7) * random.choice([-1, 1]),
                     0.0,
                     random.uniform(0, 360), asset_library, stage, idx)
        count += 1
        # Companion small spillover.
        if "box_small" in asset_library:
            idx = _place("box_small",
                         upright_x + random.uniform(-0.4, 0.4),
                         upright_y + random.uniform(0.5, 0.9) * random.choice([-1, 1]),
                         0.0,
                         random.uniform(0, 360), asset_library, stage, idx)
            count += 1

    # 5. Items leaning against rack legs — a crate or barrel propped up at
    #    a rack endpoint. 1-2 across the warehouse.
    if rack_positions and (has_crate or "barrel" in asset_library):
        for _ in range(random.randint(1, 2)):
            rx, ry, _ = random.choice(rack_positions)
            # Sit just outside the rack endpoint, against the upright.
            side = random.choice([-1, 1])
            lx = rx + side * 1.45 + random.uniform(-0.10, 0.10)
            ly = ry + random.uniform(-0.25, 0.25)
            prop = random.choice([p for p in ("crate", "barrel", "box_large")
                                  if p in asset_library] or ["box"])
            idx = _place(prop, lx, ly, 0, random.uniform(0, 360),
                         asset_library, stage, idx)
            count += 1

    print(f"[INFO] Spawned {count} human-imperfection items")
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

    # Measure the actual interior height of whatever warehouse asset was loaded
    # so racks, ceiling pipes, sprinklers, lights, and aisle signs all auto-
    # scale to the environment instead of carrying baked-in numbers.
    if "ceiling_z" not in params:
        params["ceiling_z"] = _measure_ceiling_z(stage)

    # Auto-fit XY bounds to the warehouse asset, unless the caller pinned
    # bounds explicitly. The preset's bounds_min/max are treated as the
    # design coordinate system; clutter_zones (and any other bounded params
    # authored against them) are remapped onto the measured rectangle so the
    # whole layout breathes with the warehouse instead of clumping in the
    # middle when the asset is larger than the preset assumed.
    # The bounds carried by `params` (from the JSON preset and any LLM-supplied
    # layout_params) are a *design coordinate space* — what the prompt/preset
    # was authored against. We always remap onto the measured warehouse so the
    # layout breathes with the actual asset. The LLM defaults to ±6m, which is
    # smaller than the warehouse interior, so without remapping the layout
    # clumps in the middle. Pass auto_fit_bounds=False in layout_params to opt
    # out (e.g. for hand-tuned coordinate scenes).
    auto_fit = True
    if layout_params and layout_params.get("auto_fit_bounds") is False:
        auto_fit = False
    print(f"[INFO] Bounds resolution: auto_fit={auto_fit}, "
          f"design bounds_min={params['bounds_min']} bounds_max={params['bounds_max']}, "
          f"layout_params={'<dict>' if layout_params else layout_params}")
    if auto_fit:
        m_min, m_max = _measure_floor_bounds(stage)
        if m_min is not None:
            design_min = params["bounds_min"]
            design_max = params["bounds_max"]
            params["bounds_min"] = m_min
            params["bounds_max"] = m_max
            for zone in params.get("clutter_zones", []):
                if "bounds_min" in zone:
                    zone["bounds_min"] = _affine_remap(
                        zone["bounds_min"], design_min, design_max, m_min, m_max)
                if "bounds_max" in zone:
                    zone["bounds_max"] = _affine_remap(
                        zone["bounds_max"], design_min, design_max, m_min, m_max)
        else:
            print("[WARN] _measure_floor_bounds returned None — using design "
                  f"bounds_min={params['bounds_min']} bounds_max={params['bounds_max']}")
    print(f"[INFO] Final layout bounds: bounds_min={params['bounds_min']} "
          f"bounds_max={params['bounds_max']}")

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

    # When dock_area is enabled, _spawn_dock_area is the canonical dock-zone
    # populator — gate _spawn_pallets off to avoid two competing pallet grids
    # in the same Y band.
    if params.get("dock_area", False):
        num_pallets = 0
    else:
        idx, num_pallets = _spawn_pallets(params, asset_library, stage, idx)

    idx, num_clutter = _spawn_clutter(params, asset_library, stage, idx)

    if params.get("dock_area", False):
        idx, num_dock_items = _spawn_dock_area(params, asset_library, stage, idx)

    idx, num_bulk = _spawn_bulk_stock(params, asset_library, stage, idx)

    idx, num_stripes = _spawn_floor_markings(rack_positions, params, stage, idx)
    idx, num_guards = _spawn_column_guards(rack_positions, stage, idx)
    idx, num_charge = _spawn_charging_station(params, asset_library, stage, idx)
    idx, num_rack_extras = _spawn_rack_end_details(rack_positions, asset_library, stage, idx)
    idx, num_wall_extras = _spawn_wall_details(params, asset_library, stage, idx)
    idx, num_realism = _spawn_realism_extras(params, rack_positions, stage, idx)
    idx, num_wear = _spawn_aisle_floor_wear(rack_positions, params, stage, idx)
    idx, num_main_aisle = _spawn_main_aisle_treatment(rack_positions, params, asset_library, stage, idx)
    idx, num_marshal = _spawn_marshalling_band(params, asset_library, stage, idx)
    idx, num_human = _spawn_human_imperfection(rack_positions, params, asset_library, stage, idx)
    idx, num_mid_fork = _spawn_mid_aisle_forklift(rack_positions, params, asset_library, stage, idx)
    num_doors = 0
    if params.get("dock_area", False):
        idx, num_doors = _spawn_dock_doors(params, stage, idx)

    idx, num_floor_fill = _spawn_floor_filling(params, rack_positions, asset_library, stage, idx)
    idx, num_polish = _spawn_polish_pass(params, rack_positions, asset_library, stage, idx)

    print(f"[INFO] Spawned {num_racks} racks, {num_shelf_items} shelf items, "
          f"{num_pallets} pallets, {num_clutter} clutter props, {num_dock_items} dock items, "
          f"{num_bulk} bulk-stock items, "
          f"{num_stripes} floor stripes, {num_guards} column guards, {num_charge} charge-bay items, "
          f"{num_rack_extras} rack-end details, {num_wall_extras} wall details, "
          f"{num_realism} realism extras, {num_wear} aisle wear, "
          f"{num_main_aisle} main-aisle treatment, {num_marshal} marshalling-band items, "
          f"{num_human} human-imperfection items, {num_mid_fork} mid-aisle forklift, "
          f"{num_doors} dock doors, {num_polish} polish-pass items, "
          f"{num_floor_fill} floor-fill staging items.")

    return params["bounds_min"], params["bounds_max"]