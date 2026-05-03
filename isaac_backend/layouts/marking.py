"""Floor marking spawners — aisle stripes, zone boundaries, main-drive
treatment, and marshalling-band staging details."""

import random

from .geometry import (
    DEFAULT_CEILING_Z,
    RACK_DEPTH,
)
from .placement import (
    _place,
    _paint_floor_stripe,
)
from .props import (
    _place_hi_vis_bollard,
    _place_aisle_sign,
    _place_floor_arrow,
)


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


def _spawn_pedestrian_crossing_paint(params, stage, idx):
    """Paint vehicle-lane edges, walkway boundary, and a zebra crosswalk
    centered on the pedestrian_crossing zone. Only meaningful when the
    layout defines walkway / vehicle_lane / pedestrian_crossing clutter
    zones — silently no-ops otherwise."""
    zones = {z.get("area"): z for z in params.get("clutter_zones", []) or []}
    crossing = zones.get("pedestrian_crossing")
    vehicle = zones.get("vehicle_lane")
    walkway = zones.get("walkway")
    if not crossing or not vehicle:
        return idx, 0

    yellow = (0.95, 0.80, 0.10)
    white = (0.95, 0.95, 0.95)
    count = 0

    vx_lo, vy_lo = vehicle["bounds_min"]
    vx_hi, vy_hi = vehicle["bounds_max"]
    cx = (vx_lo + vx_hi) / 2.0
    vehicle_len = vx_hi - vx_lo

    # Yellow vehicle-lane edge stripes (top + bottom of vehicle_lane band).
    for y_edge in (vy_lo, vy_hi):
        idx = _paint_floor_stripe(stage, idx, cx, y_edge,
                                  vehicle_len, 0.12, yellow)
        count += 1

    # Walkway boundary stripe — yellow line on the vehicle-side edge of
    # the walkway so pedestrian zone reads distinct from drive zone.
    if walkway:
        wy_lo, _ = walkway["bounds_min"]
        wx_lo, _ = walkway["bounds_min"]
        wx_hi, _ = walkway["bounds_max"]
        idx = _paint_floor_stripe(stage, idx, (wx_lo + wx_hi) / 2.0, wy_lo,
                                  wx_hi - wx_lo, 0.10, yellow)
        count += 1

    # Zebra crosswalk: white bands across the vehicle lane, centered on
    # crossing zone X-extent, spanning the full vehicle band Y.
    cw_x_lo, _ = crossing["bounds_min"]
    cw_x_hi, _ = crossing["bounds_max"]
    cw_w = cw_x_hi - cw_x_lo
    band_w = 0.30
    gap = 0.25
    pitch = band_w + gap
    n_bands = max(3, int(cw_w / pitch))
    band_y_len = vy_hi - vy_lo
    band_y_mid = (vy_lo + vy_hi) / 2.0
    for i in range(n_bands):
        x = cw_x_lo + (i + 0.5) * (cw_w / n_bands)
        idx = _paint_floor_stripe(stage, idx, x, band_y_mid,
                                  band_w, band_y_len, white, z=0.013)
        count += 1

    print(f"[INFO] Spawned pedestrian-crossing paint: {count} stripes "
          f"(crosswalk + lane edges)")
    return idx, count