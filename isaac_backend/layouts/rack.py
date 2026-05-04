"""Rack layout spawners — multi-zone rack dispatching, row placement,
shelf population, and rack-end column guards and placards."""

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
    RACK_FILL_PROBS,
)
from .placement import (
    _place,
    _place_rows_in_band,
    aw_dump,
)
from .props import (
    _place_column_guard,
    _place_shelf_placard,
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
        ("empty",       0.04),
        ("sparse",      0.12),
        ("normal",      0.62),
        ("overstocked", 0.22),
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
            rack_fill_prob = max(0.25, min(0.55, fill_prob * 0.6))
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
        rack_cargo_placed = 0
        for shelf_z in rack_shelf_heights:
            # Some shelves on a rack are completely empty even within a
            # non-empty rack — partial put-away pattern.
            if random.random() < 0.18:
                continue
            for slot in range(SHELF_POSITIONS_PER_LEVEL):
                if random.random() > rack_fill_prob:
                    continue
                rack_cargo_placed += 1
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

        # No-empty-rack guarantee: any non-"empty" personality rack with
        # zero cargo gets at least one item on a random shelf so detector
        # sees rack+cargo co-occurrence rather than bare frames.
        if rack_cargo_placed == 0 and rack_shelf_heights:
            shelf_z = random.choice(rack_shelf_heights)
            slot_frac = random.uniform(0.2, 0.8)
            local_along = (slot_frac - 0.5) * 2.2
            world_dx = local_along * cos_a
            world_dy = local_along * sin_a
            x = rx + world_dx
            y = ry + world_dy
            prop = random.choice(SHELF_PROPS)
            idx = _place(prop, x, y, shelf_z + 0.02,
                         rrot + random.uniform(-15, 15),
                         asset_library, stage, idx)
            cargo_count += 1

    print(f"[INFO] Populated rack shelves: {deck_count} decks, {cargo_count} cargo items "
          f"(global_fill={fill_level_global}, prob={fill_prob_global:.0%}, "
          f"per_zone_overrides={len(height_lookup)})")
    return idx, deck_count + cargo_count


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