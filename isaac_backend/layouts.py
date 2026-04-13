"""
Procedural Layout Generator

Reads layout presets from assets/layouts.json, merges with user overrides,
and spawns racks, pallets, and clutter props into the USD stage.
"""

import os
import json
import random
from pxr import UsdGeom, Gf
import omni.usd
import omni.kit.commands
from isaac_backend.semantics import apply_usd_semantics

LAYOUTS_PATH = os.path.join(os.path.dirname(__file__), "..", "assets", "layouts.json")
try:
    with open(LAYOUTS_PATH) as f:
        LAYOUTS = json.load(f)
except Exception:
    LAYOUTS = {}


def _resolve_params(layout_name, layout_params, layouts):
    preset = layouts.get(layout_name, layouts.get("standard_warehouse", {}))
    params = {
        "rack_pattern": preset.get("rack_pattern", "rows"),
        "rack_rows": preset.get("rack_rows", 5),
        "rack_cols": preset.get("rack_cols", 1),
        "aisle_width": preset.get("aisle_width", 2.0),
        "bounds_min": tuple(preset.get("bounds_min", [-5.0, -5.0])),
        "bounds_max": tuple(preset.get("bounds_max", [5.0, 5.0])),
        "clutter_density": preset.get("clutter_density", "medium"),
        "clutter_zones": [dict(z) for z in preset.get("clutter_zones", [])],
        "pallet_rows": preset.get("pallet_rows", 2),
        "pallet_cols": preset.get("pallet_cols", 1),
    }
    if layout_params:
        for key in (
            "rack_pattern", "rack_rows", "rack_cols", "aisle_width",
            "bounds_min", "bounds_max", "clutter_density", "clutter_zones",
            "pallet_rows", "pallet_cols",
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


def _place(asset_id, x, y, z, rot_z, asset_library, stage, idx):
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
    apply_usd_semantics(path, asset_id)
    return idx + 1


def _spawn_racks(params, asset_library, stage, idx):
    pattern = params["rack_pattern"]
    rows = params["rack_rows"]
    cols = params["rack_cols"]
    aw = params["aisle_width"]
    bmin = params["bounds_min"]
    bmax = params["bounds_max"]
    count = 0

    if pattern == "none" or rows == 0:
        return idx, 0

    if pattern == "rows":
        total_span = (rows - 1) * aw
        y_start = (bmin[1] + bmax[1]) / 2.0 - total_span / 2.0
        for r in range(rows):
            y = y_start + r * aw
            x_center = (bmin[0] + bmax[0]) / 2.0
            idx = _place("rack", x_center, y, 0, 90, asset_library, stage, idx)
            count += 1

    elif pattern == "grid":
        total_x = (cols - 1) * aw
        total_y = (rows - 1) * aw
        x_start = (bmin[0] + bmax[0]) / 2.0 - total_x / 2.0
        y_start = (bmin[1] + bmax[1]) / 2.0 - total_y / 2.0
        for r in range(rows):
            for c in range(cols):
                x = x_start + c * aw
                y = y_start + r * aw
                idx = _place("rack", x, y, 0, 90, asset_library, stage, idx)
                count += 1

    elif pattern == "L-shape":
        total_span_h = (rows - 1) * aw
        y_start_h = (bmin[1] + bmax[1]) / 2.0 - total_span_h / 2.0
        x_h = bmin[0] + (bmax[0] - bmin[0]) * 0.25
        for r in range(rows):
            y = y_start_h + r * aw
            idx = _place("rack", x_h, y, 0, 90, asset_library, stage, idx)
            count += 1
        total_span_v = max(2, rows - 1) * aw
        x_start_v = x_h + aw
        y_bottom = bmin[1] + (bmax[1] - bmin[1]) * 0.25
        for c in range(max(2, rows - 1)):
            x = x_start_v + c * aw
            idx = _place("rack", x, y_bottom, 0, 0, asset_library, stage, idx)
            count += 1

    elif pattern == "perimeter":
        cx = (bmin[0] + bmax[0]) / 2.0
        cy = (bmin[1] + bmax[1]) / 2.0
        margin = 1.0
        y_top = bmax[1] - margin
        y_bottom = bmin[1] + margin
        for i in range(rows):
            frac = (i + 0.5) / rows
            x = bmin[0] + frac * (bmax[0] - bmin[0])
            idx = _place("rack", x, y_top, 0, 90, asset_library, stage, idx)
            idx = _place("rack", x, y_bottom, 0, 90, asset_library, stage, idx)
            count += 2
        x_left = bmin[0] + margin
        x_right = bmax[0] - margin
        for i in range(max(1, rows - 2)):
            frac = (i + 0.5) / max(1, rows - 2)
            y = bmin[1] + frac * (bmax[1] - bmin[1])
            idx = _place("rack", x_left, y, 0, 0, asset_library, stage, idx)
            idx = _place("rack", x_right, y, 0, 0, asset_library, stage, idx)
            count += 2

    elif pattern == "clusters":
        n_clusters = max(1, cols)
        cluster_rows = rows
        total_cluster_span = (n_clusters - 1) * 2 * aw
        x_start = (bmin[0] + bmax[0]) / 2.0 - total_cluster_span / 2.0
        y_center = (bmin[1] + bmax[1]) / 2.0
        for ci in range(n_clusters):
            cx = x_start + ci * 2 * aw
            total_y = (cluster_rows - 1) * aw
            y_start = y_center - total_y / 2.0
            for r in range(cluster_rows):
                y = y_start + r * aw
                idx = _place("rack", cx, y, 0, 90, asset_library, stage, idx)
                count += 1

    return idx, count


def _spawn_pallets(params, asset_library, stage, idx):
    pallet_rows = params["pallet_rows"]
    pallet_cols = params["pallet_cols"]
    bmin = params["bounds_min"]
    bmax = params["bounds_max"]
    count = 0

    if pallet_rows == 0 or pallet_cols == 0:
        return idx, 0

    spacing_x = 2.0
    spacing_y = 2.5
    total_x = (pallet_cols - 1) * spacing_x
    total_y = (pallet_rows - 1) * spacing_y
    x_start = (bmin[0] + bmax[0]) / 2.0 - total_x / 2.0
    y_start = bmin[1] + 1.0

    for r in range(pallet_rows):
        for c in range(pallet_cols):
            x = x_start + c * spacing_x + random.uniform(-0.3, 0.3)
            y = y_start + r * spacing_y + random.uniform(-0.3, 0.3)
            rot = random.uniform(-20, 20)
            idx = _place("pallet", x, y, 0, rot, asset_library, stage, idx)
            count += 1

    return idx, count


def _count_clutter_for_density(density):
    return {"low": 5, "medium": 12, "high": 20}.get(density, 12)


def _spawn_clutter(params, asset_library, stage, idx):
    density = params["clutter_density"]
    zones = params.get("clutter_zones", [])
    bmin = params["bounds_min"]
    bmax = params["bounds_max"]
    count = 0

    prop_types = ["box", "barrel", "cone", "pallet"]

    if zones:
        for zone in zones:
            n = _count_clutter_for_density(zone.get("density", density))
            types = zone.get("types", prop_types)
            zbmin = tuple(zone.get("bounds_min", bmin))
            zbmax = tuple(zone.get("bounds_max", bmax))
            for _ in range(n):
                prop = random.choice(types)
                x = random.uniform(zbmin[0], zbmax[0])
                y = random.uniform(zbmin[1], zbmax[1])
                rot = random.uniform(0, 360)
                idx = _place(prop, x, y, 0, rot, asset_library, stage, idx)
                count += 1
    else:
        n = _count_clutter_for_density(density)
        for _ in range(n):
            prop = random.choice(prop_types)
            x = random.uniform(bmin[0], bmax[0])
            y = random.uniform(bmin[1], bmax[1])
            rot = random.uniform(0, 360)
            idx = _place(prop, x, y, 0, rot, asset_library, stage, idx)
            count += 1

    return idx, count


def generate_layout(layout_name, layout_params, asset_library, stage):
    params = _resolve_params(layout_name, layout_params, LAYOUTS)

    idx = 0
    num_racks = 0
    num_pallets = 0
    num_clutter = 0

    idx, num_racks = _spawn_racks(params, asset_library, stage, idx)
    idx, num_pallets = _spawn_pallets(params, asset_library, stage, idx)
    idx, num_clutter = _spawn_clutter(params, asset_library, stage, idx)

    print(f"[INFO] Spawned {num_racks} racks, {num_pallets} pallets, {num_clutter} clutter props.")

    return params["bounds_min"], params["bounds_max"]