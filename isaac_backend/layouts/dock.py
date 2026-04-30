"""Dock area spawners — pallet grids, dock-door clusters, bulk-stock
overflow, and the front-of-warehouse staging functions."""

import random

from .placement import (
    _place,
    _stack_boxes,
)
from .props import (
    _place_dock_door,
    _place_empty_pallet_stack,
)


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


def _spawn_dock_area(params, asset_library, stage, idx):
    """Populate the reserved dock zone with content that reads as a dock —
    not as another rack row.

    Dock zones in real warehouses are dominated by *open floor* (forklift
    turning radius) with discrete staging clusters in front of each dock
    door. The polish pass already places hazard hatches, dock-leveler
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