"""Wall-level realism: fixtures, panel seams."""

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



def _spawn_wall_panel_seams(params, stage, idx):
    """Vertical seam strips every ~1.2m along all four walls + a few off-hue
    paint patches per long wall. Breaks the solid-color wall read so back
    walls don't look like a single flat plane."""
    bmin = params["bounds_min"]
    bmax = params["bounds_max"]
    ceiling_z = params.get("ceiling_z", DEFAULT_CEILING_Z)
    seam_h = min(4.5, ceiling_z - 0.4)
    pitch = 1.20
    eps = 0.04
    count = 0

    # Long walls (run along Y, normal ±X) — seams stride in Y.
    span_y = bmax[1] - bmin[1]
    n_y = max(2, int(span_y / pitch))
    for j in range(1, n_y):
        wy = bmin[1] + j * (span_y / n_y)
        for wall_x in (bmin[0] + eps, bmax[0] - eps):
            idx = _place_wall_panel_seam(stage, idx, wall_x, wy,
                                         axis="y", height=seam_h)
            count += 1

    # Short walls (run along X, normal ±Y) — seams stride in X.
    span_x = bmax[0] - bmin[0]
    n_x = max(2, int(span_x / pitch))
    for i in range(1, n_x):
        wx = bmin[0] + i * (span_x / n_x)
        for wall_y in (bmin[1] + eps, bmax[1] - eps):
            idx = _place_wall_panel_seam(stage, idx, wx, wall_y,
                                         axis="x", height=seam_h)
            count += 1

    # Off-hue paint patches — 2-3 per long wall, base orange ±0.05 hue jitter.
    base_orange = (0.78, 0.42, 0.12)
    for wall_x, ax in ((bmin[0] + eps + 0.005, "y"),
                       (bmax[0] - eps - 0.005, "y")):
        for _ in range(random.randint(2, 3)):
            py = random.uniform(bmin[1] + 1.0, bmax[1] - 1.0)
            color = (
                max(0.0, min(1.0, base_orange[0] + random.uniform(-0.08, 0.06))),
                max(0.0, min(1.0, base_orange[1] + random.uniform(-0.08, 0.06))),
                max(0.0, min(1.0, base_orange[2] + random.uniform(-0.04, 0.06))),
            )
            idx = _place_wall_paint_patch(stage, idx, wall_x, py, axis=ax,
                                          color=color,
                                          width=random.uniform(1.2, 2.4),
                                          height=random.uniform(1.4, 2.4))
            count += 1
    for wall_y, ax in ((bmin[1] + eps + 0.005, "x"),
                       (bmax[1] - eps - 0.005, "x")):
        for _ in range(random.randint(1, 2)):
            px = random.uniform(bmin[0] + 1.0, bmax[0] - 1.0)
            color = (
                max(0.0, min(1.0, base_orange[0] + random.uniform(-0.08, 0.06))),
                max(0.0, min(1.0, base_orange[1] + random.uniform(-0.08, 0.06))),
                max(0.0, min(1.0, base_orange[2] + random.uniform(-0.04, 0.06))),
            )
            idx = _place_wall_paint_patch(stage, idx, px, wall_y, axis=ax,
                                          color=color,
                                          width=random.uniform(1.2, 2.4),
                                          height=random.uniform(1.4, 2.4))
            count += 1

    print(f"[INFO] Spawned {count} wall panel seams + paint patches")
    return idx, count


