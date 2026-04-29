"""
Layout-scale spawn orchestrators.

Each `_spawn_*` here decides positions for a layout subsystem (racks,
pallets, dock area, polish pass, realism extras, …) and delegates the
actual prim authoring to props/placement primitives. Spawners may call
each other where one is the canonical owner of a Y-band or feature
(e.g. `_spawn_floor_filling` defers dock/bulk to their owners).
"""

import math
import random

from .geometry import (
    DEFAULT_CEILING_Z,
    RACK_X_EXTENT,
    RACK_DEPTH,
    WALL_CLEARANCE,
    RACK_CEILING_FILL,
    SHELF_PITCH_FRACTION,
    SHELF_POSITIONS_PER_LEVEL,
    SHELF_PROPS,
    CLUTTER_PROPS,
    RACK_FILL_PROBS,
)
from .placement import (
    _place,
    _place_rows_in_band,
    _stack_boxes,
    _paint_floor_stripe,
    _count_clutter_for_density,
    aw_dump,
)
from .props import (
    _place_column_guard,
    _place_charger_box,
    _place_shelf_placard,
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
    _place_dock_door,
    _place_hazard_hatch,
    _place_sprinkler_head,
    _place_ceiling_pipe_run,
    _place_hi_vis_bollard,
    _place_empty_pallet_stack,
    _place_parking_stall,
    _place_first_aid_kit,
    _place_wall_clock,
    _place_dock_leveler,
    _place_painted_aisle_code,
    _place_aisle_mirror,
    _place_zone_sign,
    _place_conveyor_run,
    _place_office_enclosure,
)


def _spawn_racks_from_zones(params, asset_library, stage, idx):
    """Multi-zone rack dispatcher. Each zone in `rack_zones` carves a
    sub-rectangle out of the storage band (or the full layout if the zone
    asks to ignore the band) and places racks with its own pattern, aisle
    width, height, and orientation. Returns total racks plus a sidecar dict
    `_rack_height_at` so `_populate_rack_shelves` can scale shelves per-zone.
    """
    bmin = params["bounds_min"]
    bmax = params["bounds_max"]
    ceiling_z = params.get("ceiling_z", DEFAULT_CEILING_Z)
    rack_zones = params.get("rack_zones", []) or []

    dock_frac = params.get("dock_zone_frac", 0.25)
    storage_frac = params.get("storage_zone_frac", 0.55)
    span_y = bmax[1] - bmin[1]
    span_x = bmax[0] - bmin[0]
    storage_y_lo = bmin[1] + dock_frac * span_y
    storage_y_hi = storage_y_lo + storage_frac * span_y

    all_positions = []
    height_lookup = {}
    total = 0
    max_height = 0.0

    for i, zone in enumerate(rack_zones):
        full_bounds = bool(zone.get("full_bounds", False))
        if full_bounds:
            base_x_lo, base_x_hi = bmin[0], bmax[0]
            base_y_lo, base_y_hi = bmin[1], bmax[1]
        else:
            base_x_lo, base_x_hi = bmin[0], bmax[0]
            base_y_lo, base_y_hi = storage_y_lo, storage_y_hi

        y_frac = zone.get("y_frac", [0.0, 1.0])
        x_frac = zone.get("x_frac", [0.0, 1.0])
        zy_lo = base_y_lo + y_frac[0] * (base_y_hi - base_y_lo)
        zy_hi = base_y_lo + y_frac[1] * (base_y_hi - base_y_lo)
        zx_lo = base_x_lo + x_frac[0] * (base_x_hi - base_x_lo)
        zx_hi = base_x_lo + x_frac[1] * (base_x_hi - base_x_lo)

        # Inset interior edges so adjacent zones don't merge into one block.
        gap = 0.4
        if y_frac[0] > 0.001:
            zy_lo += gap
        if y_frac[1] < 0.999:
            zy_hi -= gap
        if x_frac[0] > 0.001:
            zx_lo += gap
        if x_frac[1] < 0.999:
            zx_hi -= gap

        if (zy_hi - zy_lo) < 1.5 or (zx_hi - zx_lo) < 1.5:
            print(f"[WARN] rack_zone {i} '{zone.get('name','?')}' "
                  f"too small after inset; skipping")
            continue

        idx, zpos, resolved_h, n = _place_rows_in_band(
            zone, zx_lo, zx_hi, zy_lo, zy_hi, ceiling_z,
            asset_library, stage, idx
        )
        zone_fill = zone.get("rack_fill")
        for p in zpos:
            all_positions.append(p)
            key = (round(p[0], 2), round(p[1], 2))
            height_lookup[key] = (resolved_h, zone_fill)
        total += n
        if resolved_h > max_height:
            max_height = resolved_h

        print(f"[INFO] rack_zone {i} '{zone.get('name','?')}': "
              f"pattern={zone.get('pattern','rows')} "
              f"rows={zone.get('rows','auto')} cols={zone.get('cols','auto')} "
              f"aisle={aw_dump(zone)} h={resolved_h:.2f}m → {n} racks")

    params["_resolved_rack_height"] = max_height or (ceiling_z * RACK_CEILING_FILL)
    params["_rack_height_at"] = height_lookup
    return idx, total, all_positions


def _spawn_racks(params, asset_library, stage, idx):
    if params.get("rack_zones"):
        return _spawn_racks_from_zones(params, asset_library, stage, idx)

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
    fill_level_global = params.get("rack_fill", "medium")
    fill_prob_global = RACK_FILL_PROBS.get(fill_level_global, 0.60)
    deck_count = 0
    cargo_count = 0
    has_shelf_asset = "rack_shelf" in asset_library

    # Per-rack height/fill sidecar populated by _spawn_racks_from_zones.
    # When absent (single-zone path), every rack falls back to the
    # warehouse-wide resolved height + fill level.
    height_lookup = params.get("_rack_height_at", {}) or {}
    rack_height_global = params.get("_resolved_rack_height") or (
        params.get("ceiling_z", DEFAULT_CEILING_Z) * RACK_CEILING_FILL
    )

    def _shelf_heights_for(h):
        spacing = max(0.7, h * SHELF_PITCH_FRACTION)
        n = max(2, int(h / spacing))
        return [0.15 + i * spacing for i in range(n)]

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

        key = (round(rx, 2), round(ry, 2))
        if key in height_lookup:
            this_height, zone_fill = height_lookup[key]
            fill_prob = RACK_FILL_PROBS.get(zone_fill or fill_level_global,
                                            fill_prob_global)
        else:
            this_height = rack_height_global
            fill_prob = fill_prob_global
        shelf_heights = _shelf_heights_for(this_height)

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
          f"(global_fill={fill_level_global}, prob={fill_prob_global:.0%}, "
          f"per_zone_overrides={len(height_lookup)})")
    return idx, deck_count + cargo_count


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

    rows = {}
    for (rx, ry, rrot) in rack_positions:
        if rrot == 90:
            key = round(ry * 2) / 2.0
            rows.setdefault(key, []).append(rx)
    for key, xs in rows.items():
        x_lo = min(xs) - 1.6
        x_hi = max(xs) + 1.6
        if x_lo > bmin[0] + 0.4:
            idx = _place_aisle_mirror(stage, idx, x_lo, key)
            count += 1
        if x_hi < bmax[0] - 0.4:
            idx = _place_aisle_mirror(stage, idx, x_hi, key)
            count += 1

    palette = [(0.95, 0.78, 0.10), (0.95, 0.45, 0.05),
               (0.30, 0.70, 0.35), (0.20, 0.55, 0.90),
               (0.85, 0.20, 0.55), (0.55, 0.30, 0.75)]
    for ri, key in enumerate(sorted(rows.keys())):
        xs = rows[key]
        code_x = max(xs) + 2.4
        if code_x > bmax[0] - 0.6:
            code_x = min(xs) - 2.4
            if code_x < bmin[0] + 0.6:
                continue
        letter = chr(ord("A") + (ri % 26))
        code = f"{letter}-{ri + 1}"
        idx = _place_painted_aisle_code(stage, idx, code_x, key, code,
                                         rot_z=0,
                                         tile_color=palette[ri % len(palette)])
        count += 1

    print(f"[INFO] Spawned realism layer: {count} grouped items "
          f"(zone signs / office / conveyor / mirrors / aisle codes)")
    return idx, count
