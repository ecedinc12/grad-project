"""Static equipment props: chargers, parked forklifts."""

import math
import random

from isaac_backend.layouts.geometry import (
    DEFAULT_CEILING_Z,
    RACK_X_EXTENT,
    RACK_DEPTH,
    CLUTTER_PROPS,
    _build_aisle_records,
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



def _spawn_mid_aisle_forklift(rack_positions, params, asset_library, stage, idx):
    """Drop a second forklift parked mid-aisle to imply active operations."""
    if "forklift" not in asset_library or not rack_positions:
        return idx, 0
    aisles = _build_aisle_records(rack_positions, pad=0.0)
    if not aisles:
        return idx, 0

    # Pick the aisle whose perpendicular center is closest to warehouse center.
    bmin = params["bounds_min"]
    bmax = params["bounds_max"]
    cx = (bmin[0] + bmax[0]) / 2.0
    cy = (bmin[1] + bmax[1]) / 2.0
    def _aisle_dist(a):
        return abs(a["mid"] - (cy if a["axis"] == "x" else cx))
    aisles.sort(key=_aisle_dist)
    a = aisles[0]
    long_center = (a["lo"] + a["hi"]) / 2.0
    long_p = long_center + random.uniform(-1.5, 1.5)
    perp_p = a["mid"] + random.uniform(-0.15, 0.15)

    if a["axis"] == "x":
        fx, fy = long_p, perp_p
        rot = random.choice([0, 180]) + random.uniform(-8, 8)
    else:
        fx, fy = perp_p, long_p
        rot = random.choice([90, 270]) + random.uniform(-8, 8)

    idx = _place("forklift", fx, fy, 0, rot, asset_library, stage, idx)
    count = 1
    if "pallet" in asset_library:
        ang = math.radians(rot)
        cos_a, sin_a = math.cos(ang), math.sin(ang)
        local_fx = 1.2
        px = fx + local_fx * cos_a
        py = fy + local_fx * sin_a
        idx = _place("pallet", px, py, 0.18, rot, asset_library, stage, idx)
        count += 1
        idx, n = _stack_boxes(px, py, (1.0, 0.7, 0.35),
                              (0.06, 0.08, 0.10), asset_library, stage, idx)
        count += n
    return idx, count


