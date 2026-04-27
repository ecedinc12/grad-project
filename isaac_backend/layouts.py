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
SHELF_HEIGHTS = [0.15, 0.85, 1.55]
SHELF_POSITIONS_PER_LEVEL = 4

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
        "rack_rows": preset.get("rack_rows", 8),
        "rack_cols": preset.get("rack_cols", 2),
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
            "rack_pattern", "rack_rows", "rack_cols", "aisle_width",
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
    count = 0
    rack_positions = []

    if pattern == "none" or rows == 0:
        return idx, 0, rack_positions

    if pattern == "rows":
        # rack_rows parallel rows running East-West, each with rack_cols racks
        # placed back-to-back along X. aw is the Y aisle gap between rows.
        rack_x_extent = 2.8  # SM_RackFrame_03 length when rotated 90°
        total_x = max(0, cols - 1) * rack_x_extent
        total_y = (rows - 1) * aw
        x_start = (bmin[0] + bmax[0]) / 2.0 - total_x / 2.0
        y_start = (bmin[1] + bmax[1]) / 2.0 - total_y / 2.0
        for r in range(rows):
            y = y_start + r * aw
            for c in range(cols):
                x = x_start + c * rack_x_extent
                idx = _place("rack", x, y, 0, 90, asset_library, stage, idx)
                rack_positions.append((x, y, 90))
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
                rack_positions.append((x, y, 90))
                count += 1

    elif pattern == "L-shape":
        total_span_h = (rows - 1) * aw
        y_start_h = (bmin[1] + bmax[1]) / 2.0 - total_span_h / 2.0
        x_h = bmin[0] + (bmax[0] - bmin[0]) * 0.25
        for r in range(rows):
            y = y_start_h + r * aw
            idx = _place("rack", x_h, y, 0, 90, asset_library, stage, idx)
            rack_positions.append((x_h, y, 90))
            count += 1
        total_span_v = max(2, rows - 1) * aw
        x_start_v = x_h + aw
        y_bottom = bmin[1] + (bmax[1] - bmin[1]) * 0.25
        for c in range(max(2, rows - 1)):
            x = x_start_v + c * aw
            idx = _place("rack", x, y_bottom, 0, 0, asset_library, stage, idx)
            rack_positions.append((x, y_bottom, 0))
            count += 1

    elif pattern == "perimeter":
        margin = 1.0
        y_top = bmax[1] - margin
        y_bottom = bmin[1] + margin
        for i in range(rows):
            frac = (i + 0.5) / rows
            x = bmin[0] + frac * (bmax[0] - bmin[0])
            idx = _place("rack", x, y_top, 0, 90, asset_library, stage, idx)
            rack_positions.append((x, y_top, 90))
            idx = _place("rack", x, y_bottom, 0, 90, asset_library, stage, idx)
            rack_positions.append((x, y_bottom, 90))
            count += 2
        x_left = bmin[0] + margin
        x_right = bmax[0] - margin
        for i in range(max(1, rows - 2)):
            frac = (i + 0.5) / max(1, rows - 2)
            y = bmin[1] + frac * (bmax[1] - bmin[1])
            idx = _place("rack", x_left, y, 0, 0, asset_library, stage, idx)
            rack_positions.append((x_left, y, 0))
            idx = _place("rack", x_right, y, 0, 0, asset_library, stage, idx)
            rack_positions.append((x_right, y, 0))
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
                rack_positions.append((cx, y, 90))
                count += 1

    return idx, count, rack_positions


def _populate_rack_shelves(rack_positions, params, asset_library, stage, idx):
    fill_level = params.get("rack_fill", "medium")
    fill_prob = RACK_FILL_PROBS.get(fill_level, 0.60)
    deck_count = 0
    cargo_count = 0
    has_shelf_asset = "rack_shelf" in asset_library

    for pos in rack_positions:
        # Tolerate older 2-tuple positions in case of partial upgrade.
        if len(pos) == 3:
            rx, ry, rrot = pos
        else:
            rx, ry = pos
            rrot = 90

        # Place a horizontal deck plank at each shelf level so the rack reads
        # as a real loaded shelving unit instead of a bare frame.
        if has_shelf_asset:
            for shelf_z in SHELF_HEIGHTS:
                idx = _place("rack_shelf", rx, ry, shelf_z, rrot, asset_library, stage, idx)
                deck_count += 1

        if fill_prob <= 0.0:
            continue

        ang = math.radians(rrot)
        cos_a, sin_a = math.cos(ang), math.sin(ang)
        for shelf_z in SHELF_HEIGHTS:
            for slot in range(SHELF_POSITIONS_PER_LEVEL):
                if random.random() > fill_prob:
                    continue
                prop = random.choice(SHELF_PROPS)
                # Distribute slots evenly along the shelf length, with mild jitter.
                slot_frac = (slot + 0.5) / SHELF_POSITIONS_PER_LEVEL  # 0..1
                local_along = (slot_frac - 0.5) * 2.2 + random.uniform(-0.10, 0.10)
                local_depth = random.uniform(-0.18, 0.18)
                # Rotate local (along, depth) → world (x, y) using rack orientation.
                world_dx = local_along * cos_a - local_depth * sin_a
                world_dy = local_along * sin_a + local_depth * cos_a
                x = rx + world_dx
                y = ry + world_dy
                z = shelf_z + random.uniform(-0.02, 0.02)
                rot = rrot + random.uniform(-15, 15)
                idx = _place(prop, x, y, z, rot, asset_library, stage, idx)
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

    print(f"[INFO] Spawned {num_racks} racks, {num_shelf_items} shelf items, "
          f"{num_pallets} pallets, {num_clutter} clutter props, {num_dock_items} dock items.")

    return params["bounds_min"], params["bounds_max"]