"""Floor-level realism: filler clutter and aisle wear."""

import math
import random

from isaac_backend.layouts.geometry import (
    DEFAULT_CEILING_Z,
    RACK_X_EXTENT,
    RACK_DEPTH,
    CLUTTER_PROPS,
    _build_aisle_records,
    _build_rack_groups,
    _zone_in_dock_band,
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

    rack_pattern = params.get("rack_pattern", "rows")
    use_zone_fallback = (
        not rack_positions
        or rack_pattern in ("none", "perimeter", "clusters")
        or len(rack_positions) < 4
    )

    rxs = [p[0] for p in rack_positions] if rack_positions else []
    rys = [p[1] for p in rack_positions] if rack_positions else []
    if rxs and rys:
        # Rack body extends ±RACK_X_EXTENT/2 along X and ±RACK_DEPTH/2 along Y
        # for racks rotated 90°, so pad by those when computing the dead-zone.
        rzone_xmin = min(rxs) - RACK_X_EXTENT / 2.0 - 0.4
        rzone_xmax = max(rxs) + RACK_X_EXTENT / 2.0 + 0.4
        rzone_ymin = min(rys) - RACK_DEPTH / 2.0 - 0.5
        rzone_ymax = max(rys) + RACK_DEPTH / 2.0 + 0.5
    else:
        rzone_xmin = rzone_xmax = rzone_ymin = rzone_ymax = 0.0

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
        # Wider rotation envelope — real staging is rarely square. Mix in
        # the occasional 90° pivot so the grid doesn't read as one heading.
        if rot is None:
            rot = random.uniform(-35, 35)
            if random.random() < 0.18:
                rot += 90
        idx = _place("pallet", x, y, 0, rot, asset_library, stage, idx)
        count += 1
        # 18% bare pallet — nothing on top, just the deck.
        if random.random() < 0.18:
            return
        roll = random.random()
        if roll < 0.55:
            # Vary stack height: low, medium, or tall pile.
            tall = random.random()
            if tall < 0.30:
                box_size = (0.95, 0.65, 0.30)
                box_off = (0.08, 0.10, 0.10)
            elif tall < 0.75:
                box_size = (1.0, 0.7, 0.45)
                box_off = (0.08, 0.10, 0.12)
            else:
                box_size = (1.05, 0.75, 0.65)
                box_off = (0.10, 0.12, 0.14)
            idx, n = _stack_boxes(x, y, box_size, box_off, asset_library, stage, idx)
            count += n
        elif roll < 0.80:
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

    if use_zone_fallback:
        # Layouts without a contiguous rack block (perimeter / clusters / none /
        # very few racks) can't carve "front/back/side strips" from a rack bbox.
        # Fill the preset's clutter_zones directly with staging pallets and
        # drum clusters. Skip zones owned by the dock-band populator.
        zones = params.get("clutter_zones", []) or []
        for zone in zones:
            zmin = zone.get("bounds_min")
            zmax = zone.get("bounds_max")
            if zmin is None or zmax is None:
                continue
            if _zone_in_dock_band(zmin, zmax, params):
                continue
            density = zone.get("density", params.get("clutter_density", "medium"))
            n_slots = {"low": 4, "medium": 9, "high": 16}.get(density, 9)
            zw = zmax[0] - zmin[0]
            zh = zmax[1] - zmin[1]
            # Slot the zone with a loose grid; jitter each slot heavily so the
            # fill reads as accumulated staging, not CAD-snap.
            cols = max(1, int(round((zw / max(zh, 0.1)) ** 0.5 * (n_slots ** 0.5))))
            rows = max(1, (n_slots + cols - 1) // cols)
            cell_w = zw / cols
            cell_h = zh / rows
            for r in range(rows):
                for c in range(cols):
                    if random.random() < 0.18:
                        continue  # gap rate
                    sx = zmin[0] + (c + 0.5) * cell_w + random.uniform(-cell_w * 0.30, cell_w * 0.30)
                    sy = zmin[1] + (r + 0.5) * cell_h + random.uniform(-cell_h * 0.30, cell_h * 0.30)
                    roll = random.random()
                    if roll < 0.45:
                        _drop_loaded_pallet(sx, sy)
                    elif roll < 0.75:
                        _drop_drum(sx, sy)
                    else:
                        prop = random.choice([p for p in ("crate", "box_large", "box")
                                              if p in asset_library] or ["box"])
                        idx = _place(prop, sx, sy, 0, random.uniform(0, 360),
                                     asset_library, stage, idx)
                        count += 1
        return idx, count

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
                # Heavier per-slot jitter so the grid reads as accumulated
                # placements, not a CAD-snap layout.
                px = x0 + c * col_pitch + random.uniform(-0.45, 0.45)
                py = front_y_min + r * row_pitch + random.uniform(-0.40, 0.40)
                # 30% gap rate (vs 15%) breaks the field into clusters.
                if random.random() < 0.70:
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



def _spawn_aisle_floor_wear(rack_positions, params, stage, idx):
    """Traffic-pattern wear:
      • Main drive aisle (widest gap) gets full-length heavy double tracks.
      • Picking aisles get lighter, intermittent scuffs.
      • Rack-end turnarounds get extra dense scuffing where forklifts pivot.
      • Oil drips concentrate in the main aisle, not random side aisles.
    """
    if not rack_positions:
        return idx, 0
    aisle_info = _build_aisle_records(rack_positions, pad=0.8)
    if not aisle_info:
        return idx, 0

    # Identify the main aisle: widest gap. Everything else is a picker.
    main_aisle = max(aisle_info, key=lambda a: a["gap"])
    count = 0

    def _scuff_along_aisle(a, length, offset, jitter_long=0.0):
        long_mid = (a["lo"] + a["hi"]) / 2.0 + jitter_long
        if a["axis"] == "x":
            return _place_tire_scuff(stage, idx, long_mid, a["mid"] + offset,
                                     length, rot_z=0)
        return _place_tire_scuff(stage, idx, a["mid"] + offset, long_mid,
                                 length, rot_z=90)

    for a in aisle_info:
        is_main = a is main_aisle
        length = a["hi"] - a["lo"]
        if is_main:
            for offset in (-0.55, 0.55):
                idx = _scuff_along_aisle(a, length, offset)
                count += 1
            if random.random() < 0.5:
                idx = _scuff_along_aisle(a, length * 0.6,
                                         random.choice([-0.20, 0.20]))
                count += 1
        else:
            if random.random() < 0.6:
                seg_len = length * random.uniform(0.4, 0.7)
                jitter = random.uniform(-length * 0.15, length * 0.15)
                offset = random.choice([-0.40, 0.40])
                idx = _scuff_along_aisle(a, seg_len, offset, jitter_long=jitter)
                count += 1

    # Rack-end turnaround scuffs at both endpoints for each rack row,
    # regardless of orientation.
    ew_rows, ns_cols = _build_rack_groups(rack_positions)
    for ry_key, xs in ew_rows.items():
        for end_x in (min(xs) - 1.4, max(xs) + 1.4):
            if random.random() < 0.55:
                idx = _place_tire_scuff(stage, idx, end_x, ry_key,
                                        1.4, rot_z=90 + random.uniform(-15, 15))
                count += 1
    for rx_key, ys in ns_cols.items():
        for end_y in (min(ys) - 1.4, max(ys) + 1.4):
            if random.random() < 0.55:
                idx = _place_tire_scuff(stage, idx, rx_key, end_y,
                                        1.4, rot_z=random.uniform(-15, 15))
                count += 1

    # Oil stains: prefer the main aisle, with one plausible drip path.
    def _aisle_random_point(a, edge_inset=1.0, perp_jitter=0.20):
        long_lo = a["lo"] + edge_inset
        long_hi = a["hi"] - edge_inset
        if long_hi <= long_lo:
            long_lo, long_hi = a["lo"], a["hi"]
        long_p = random.uniform(long_lo, long_hi)
        perp = a["mid"] + random.uniform(-perp_jitter, perp_jitter)
        if a["axis"] == "x":
            return long_p, perp
        return perp, long_p

    n_stains = random.randint(2, 3)
    for _ in range(n_stains):
        if random.random() < 0.75:
            ox, oy = _aisle_random_point(main_aisle, perp_jitter=0.25)
            radius = random.uniform(0.28, 0.45)
        else:
            a = random.choice(aisle_info)
            ox, oy = _aisle_random_point(a, perp_jitter=0.20)
            radius = random.uniform(0.20, 0.30)
        idx = _place_oil_stain(stage, idx, ox, oy, radius=radius)
        count += 1

    return idx, count


