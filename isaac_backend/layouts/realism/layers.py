"""Composite realism layers — orchestrate other passes."""

import math
import random

from isaac_backend.layouts.geometry import (
    DEFAULT_CEILING_Z,
    RACK_X_EXTENT,
    RACK_DEPTH,
    CLUTTER_PROPS,
    _build_aisle_records,
    _build_rack_groups,
)
from isaac_backend.layouts.placement import (
    _place,
    _stack_boxes,
    _paint_floor_stripe,
    _count_clutter_for_density,
)
from isaac_backend.layouts.props import (
    _place_charger_box,
    _place_fire_extinguisher,
    _place_exit_sign,
    _place_trash_bin,
    _place_pack_table,
    _place_cardboard_stack,
    _place_floor_arrow,
    _place_caution_sign,
    _place_wall_junction_box,
    _place_overhead_light,
    _place_aisle_sign,
    _place_mop_and_bucket,
    _place_tire_scuff,
    _place_oil_stain,
    _place_ceiling_pipe_run,
    _place_sprinkler_head,
    _place_hazard_hatch,
    _place_hi_vis_bollard,
    _place_empty_pallet_stack,
    _place_parking_stall,
    _place_first_aid_kit,
    _place_wall_clock,
    _place_dock_leveler,
    _place_zone_sign,
    _place_office_enclosure,
    _place_conveyor_run,
    _place_aisle_mirror,
    _place_painted_aisle_code,
    _place_pallet_jack,
    _place_wall_windows,
    _place_mezzanine,
    _place_open_dock_door,
    _place_truck_back,
    _place_dock_leveler_ramped,
    _place_wrapping_station,
    _place_wrapped_pallet,
    _place_hand_truck,
    _place_wall_panel_seam,
    _place_wall_paint_patch,
)
from isaac_backend.layouts.materials import bind_material
from pxr import UsdGeom, Gf


def _spawn_realism_layer(rack_positions, params, asset_library, stage, idx):
    """Top-5 realism additions: suspended zone signs, glass-walled office
    enclosure, roller conveyor along the side wall, blind-corner safety
    mirrors at row endpoints, painted floor aisle codes (A-1, B-2…) at row
    entries. Each lives outside the existing polish/realism passes so it can
    be toggled or extended independently."""
    bmin = params["bounds_min"]
    bmax = params["bounds_max"]
    cx = (bmin[0] + bmax[0]) / 2.0
    ceiling_z = params.get("ceiling_z", DEFAULT_CEILING_Z)
    count = 0

    dock_frac = params.get("dock_zone_frac", 0.25)
    storage_frac = params.get("storage_zone_frac", 0.55)
    bulk_frac = max(0.0, 1.0 - dock_frac - storage_frac)
    span_y = bmax[1] - bmin[1]
    sign_z = ceiling_z - 1.0
    zone_specs = [
        ("DOCK", bmin[1] + dock_frac * 0.55 * span_y, (0.95, 0.45, 0.05)),
        ("STORAGE", bmin[1] + (dock_frac + storage_frac * 0.5) * span_y,
         (0.20, 0.55, 0.90)),
    ]
    if bulk_frac > 0.05:
        zone_specs.append(("BULK",
                            bmax[1] - bulk_frac * 0.5 * span_y,
                            (0.30, 0.70, 0.35)))
    for label, sy, band in zone_specs:
        idx = _place_zone_sign(stage, idx, cx, sy, sign_z, label, band)
        count += 1

    office_w, office_d = 3.6, 2.6
    office_cx = bmin[0] + office_w / 2.0 + 0.5
    office_cy = bmax[1] - office_d / 2.0 - 0.5
    idx = _place_office_enclosure(stage, idx, office_cx, office_cy,
                                   width=office_w, depth=office_d,
                                   height=2.2, rot_z=0)
    count += 1

    cv_x = bmax[0] - 1.2
    cv_y_start = bmax[1] - 1.6
    cv_y_end = bmin[1] + dock_frac * span_y + 0.8
    if abs(cv_y_end - cv_y_start) > 4.0:
        idx = _place_conveyor_run(stage, idx, cv_x, cv_y_start,
                                   cv_x, cv_y_end, height=0.80)
        count += 1

    ew_rows, ns_cols = _build_rack_groups(rack_positions)
    # Mirrors at both endpoints of each rack row (EW and NS).
    for key, xs in ew_rows.items():
        x_lo = min(xs) - 1.6
        x_hi = max(xs) + 1.6
        if x_lo > bmin[0] + 0.4:
            idx = _place_aisle_mirror(stage, idx, x_lo, key)
            count += 1
        if x_hi < bmax[0] - 0.4:
            idx = _place_aisle_mirror(stage, idx, x_hi, key)
            count += 1
    for key, ys in ns_cols.items():
        y_lo = min(ys) - 1.6
        y_hi = max(ys) + 1.6
        if y_lo > bmin[1] + 0.4:
            idx = _place_aisle_mirror(stage, idx, key, y_lo)
            count += 1
        if y_hi < bmax[1] - 0.4:
            idx = _place_aisle_mirror(stage, idx, key, y_hi)
            count += 1

    palette = [(0.95, 0.78, 0.10), (0.95, 0.45, 0.05),
               (0.30, 0.70, 0.35), (0.20, 0.55, 0.90),
               (0.85, 0.20, 0.55), (0.55, 0.30, 0.75)]
    code_idx = 0
    for key in sorted(ew_rows.keys()):
        xs = ew_rows[key]
        code_x = max(xs) + 2.4
        if code_x > bmax[0] - 0.6:
            code_x = min(xs) - 2.4
            if code_x < bmin[0] + 0.6:
                continue
        letter = chr(ord("A") + (code_idx % 26))
        code = f"{letter}-{code_idx + 1}"
        idx = _place_painted_aisle_code(stage, idx, code_x, key, code,
                                         rot_z=0,
                                         tile_color=palette[code_idx % len(palette)])
        count += 1
        code_idx += 1
    for key in sorted(ns_cols.keys()):
        ys = ns_cols[key]
        code_y = max(ys) + 2.4
        if code_y > bmax[1] - 0.6:
            code_y = min(ys) - 2.4
            if code_y < bmin[1] + 0.6:
                continue
        letter = chr(ord("A") + (code_idx % 26))
        code = f"{letter}-{code_idx + 1}"
        idx = _place_painted_aisle_code(stage, idx, key, code_y, code,
                                         rot_z=90,
                                         tile_color=palette[code_idx % len(palette)])
        count += 1
        code_idx += 1

    print(f"[INFO] Spawned realism layer: {count} grouped items "
          f"(zone signs / office / conveyor / mirrors / aisle codes)")
    return idx, count



def _spawn_realism_layer_2(rack_positions, params, asset_library, stage, idx):
    """Second realism batch: mezzanine catwalk along one wall, an open dock
    door + truck silhouette + ramped leveler, a stretch-wrap station + 1-2
    wrapped pallets in the marshalling band, light-blue glazed wall windows
    along both long walls (skipping the mezzanine span on its wall), and 3
    manual pallet jacks (rack-end / mid-aisle / marshalling)."""
    bmin = params["bounds_min"]
    bmax = params["bounds_max"]
    span_y = bmax[1] - bmin[1]
    span_x = bmax[0] - bmin[0]
    cx = (bmin[0] + bmax[0]) / 2.0
    cy = (bmin[1] + bmax[1]) / 2.0
    has_dock = params.get("dock_area", False)
    dock_frac = params.get("dock_zone_frac", 0.25)
    dock_y_top = bmin[1] + dock_frac * span_y
    count = 0

    # 1) Mezzanine along the +X wall, back-third. Gate independent of dock so
    # standard layouts also get the elevated catwalk silhouette.
    mezz_y_lo = (dock_y_top + 1.5) if has_dock else (bmin[1] + 0.30 * span_y)
    mezz_y_hi = bmax[1] - 1.5
    mezz_active = mezz_y_hi - mezz_y_lo >= 4.0
    if mezz_active:
        idx = _place_mezzanine(stage, idx, bmax[0] - 0.30,
                                mezz_y_lo, mezz_y_hi,
                                depth=2.2, height=3.4, side=-1)
        count += 1

    # 2) Open dock door + truck silhouette + ramped leveler.
    if has_dock:
        door_w = 2.6
        spacing = door_w + 1.4
        n_doors = max(1, int((span_x - 2.0) / spacing))
        total_w = (n_doors - 1) * spacing
        x_start = cx - total_w / 2.0
        open_idx = params.get("_open_dock_door_idx", n_doors // 2)
        open_idx = max(0, min(n_doors - 1, open_idx))
        open_x = x_start + open_idx * spacing
        wall_y = bmin[1] + 0.06
        idx = _place_open_dock_door(stage, idx, open_x, wall_y,
                                     width=door_w, height=3.2)
        idx = _place_dock_leveler_ramped(stage, idx,
                                          open_x, wall_y - 0.65,
                                          width=door_w - 0.2,
                                          depth=1.4, tilt_deg=10)
        idx = _place_truck_back(stage, idx, open_x, wall_y - 3.0,
                                 width=door_w, depth=4.5, height=3.0)
        count += 3

    # 3) Wrapping station + 1-2 wrapped pallets. Without a dock, drop into the
    # back-center band so standard layouts still get one.
    if has_dock:
        wrap_y = dock_y_top + 0.7
    else:
        wrap_y = cy + 0.20 * span_y
    wrap_x = cx - 4.0
    if "pallet" in asset_library:
        idx = _place_wrapping_station(stage, idx, wrap_x, wrap_y, rot_z=0)
        idx = _place_wrapped_pallet(stage, idx, wrap_x, wrap_y,
                                     asset_library, rot_z=0)
        idx = _place_wrapped_pallet(stage, idx, wrap_x + 1.6, wrap_y - 0.10,
                                     asset_library,
                                     rot_z=random.uniform(-10, 10))
        count += 3

    # 4) Wall windows.
    win_y_lo = bmin[1] + 1.2
    win_y_hi = bmax[1] - 1.2
    if mezz_active:
        idx = _place_wall_windows(stage, idx, bmax[0] - 0.05,
                                    win_y_lo, mezz_y_lo - 0.6,
                                    n_windows=3, z_center=2.2)
    else:
        idx = _place_wall_windows(stage, idx, bmax[0] - 0.05,
                                    win_y_lo, win_y_hi,
                                    n_windows=5, z_center=2.4)
    # -X wall: avoid the office (back-left corner used by realism_layer 1).
    idx = _place_wall_windows(stage, idx, bmin[0] + 0.05,
                                win_y_lo, bmax[1] - 4.0,
                                n_windows=4, z_center=2.4)
    count += 2

    # 5) Pallet jacks: 3 rack-end + up to 2 mid-aisle + (dock-only) marshalling.
    ew_rows, ns_cols = _build_rack_groups(rack_positions)
    jack_palette = [
        (0.85, 0.20, 0.20),
        (0.20, 0.45, 0.65),
        (0.85, 0.65, 0.10),
        (0.30, 0.55, 0.30),
        (0.55, 0.30, 0.55),
    ]
    # Pool both orientations as candidate rack-end anchors.
    rack_end_candidates = []  # list of (anchor_x, anchor_y, rot)
    for row_key, xs in ew_rows.items():
        for side in (-1, 1):
            anchor_x = (max(xs) + 1.55) if side > 0 else (min(xs) - 1.55)
            rot = random.uniform(-30, 30) + (0 if side > 0 else 180)
            rack_end_candidates.append((anchor_x,
                                        row_key + random.uniform(-0.30, 0.30),
                                        rot))
    for col_key, ys in ns_cols.items():
        for side in (-1, 1):
            anchor_y = (max(ys) + 1.55) if side > 0 else (min(ys) - 1.55)
            rot = random.uniform(-30, 30) + (90 if side > 0 else 270)
            rack_end_candidates.append((col_key + random.uniform(-0.30, 0.30),
                                        anchor_y,
                                        rot))
    random.shuffle(rack_end_candidates)
    for (ax, ay, ar) in rack_end_candidates[:3]:
        idx = _place_pallet_jack(stage, idx, ax, ay, rot_z=ar,
                                  color=random.choice(jack_palette))
        count += 1

    # Mid-aisle jacks: pick up to 2 aisles across both orientations.
    aisles = _build_aisle_records(rack_positions, pad=0.0)
    random.shuffle(aisles)
    for a in aisles[:2]:
        long_center = (a["lo"] + a["hi"]) / 2.0
        long_p = long_center + random.uniform(-1.5, 1.5)
        if a["axis"] == "x":
            mid_x, mid_y = long_p, a["mid"]
        else:
            mid_x, mid_y = a["mid"], long_p
        idx = _place_pallet_jack(stage, idx, mid_x, mid_y,
                                  rot_z=random.uniform(0, 360),
                                  color=random.choice(jack_palette))
        count += 1
    if has_dock:
        idx = _place_pallet_jack(stage, idx, cx + 3.0,
                                  dock_y_top + 0.9,
                                  rot_z=random.uniform(0, 360),
                                  color=random.choice(jack_palette))
        count += 1

    print(f"[INFO] Spawned realism-layer 2: {count} grouped items "
          f"(mezzanine / open dock / wrap station / windows / pallet jacks)")
    return idx, count


