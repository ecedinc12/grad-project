"""Wear and human-imperfection details."""

import math
import random

from isaac_backend.layouts.geometry import (
    DEFAULT_CEILING_Z,
    RACK_X_EXTENT,
    RACK_DEPTH,
    CLUTTER_PROPS,
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


