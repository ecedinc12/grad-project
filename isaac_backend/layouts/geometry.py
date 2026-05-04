"""
Layout geometry, presets, and measurement.

Holds the layout preset registry (loaded from assets/layouts.json), the
shared numeric constants used across rack/prop placement, the
warehouse-space measurement helpers (ceiling height, floor bounds), the
preset+override resolution function, and the affine remap used to drag
zone bounds onto the measured warehouse rectangle.
"""

import os
import json


LAYOUTS_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "assets", "layouts.json")
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


RACK_FILL_PROBS = {
    "empty": 0.0,
    "sparse": 0.45,
    "medium": 0.78,
    "full": 0.95,
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
        "rack_zones": [dict(z) for z in preset.get("rack_zones", [])],
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
            "rack_zones",
            "pallet_rows", "pallet_cols", "rack_fill", "dock_area",
            "max_rows", "max_cols", "cross_aisle_every", "cross_aisle_width",
            "aisle_widths", "dock_zone_frac", "storage_zone_frac",
        ):
            if key in layout_params:
                val = layout_params[key]
                if key in ("bounds_min", "bounds_max"):
                    params[key] = tuple(val)
                elif key in ("clutter_zones", "rack_zones"):
                    params[key] = [dict(z) for z in val]
                elif key == "aisle_widths" and val is not None:
                    params[key] = list(val)
                else:
                    params[key] = val
    return params
