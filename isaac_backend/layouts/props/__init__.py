"""Prop placement library.

Submodules group props by domain:
  floor_markings — arrows, painted codes, hazard hatches, parking, stains
  wall_fixtures  — signs, extinguishers, junction boxes, mirrors, panel detail
  ceiling        — overhead lights, sprinklers, pipe runs
  dock           — dock doors, levelers, trucks
  equipment      — operational equipment, bollards, bins, conveyors, structures
"""

from .floor_markings import (
    _place_floor_arrow,
    _place_caution_sign,
    _place_tire_scuff,
    _place_oil_stain,
    _place_hazard_hatch,
    _place_parking_stall,
    _place_painted_aisle_code,
)
from .wall_fixtures import (
    _place_shelf_placard,
    _place_fire_extinguisher,
    _place_exit_sign,
    _place_wall_junction_box,
    _place_aisle_sign,
    _place_wall_panel_seam,
    _place_wall_paint_patch,
    _place_first_aid_kit,
    _place_wall_clock,
    _place_aisle_mirror,
    _place_zone_sign,
    _place_wall_windows,
)
from .ceiling import (
    _place_overhead_light,
    _place_sprinkler_head,
    _place_ceiling_pipe_run,
)
from .dock import (
    _place_dock_door,
    _place_dock_leveler,
    _place_open_dock_door,
    _place_truck_back,
    _place_dock_leveler_ramped,
)
from .equipment import (
    _place_column_guard,
    _place_charger_box,
    _place_trash_bin,
    _place_pack_table,
    _place_cardboard_stack,
    _place_mop_and_bucket,
    _place_hi_vis_bollard,
    _place_empty_pallet_stack,
    _place_conveyor_run,
    _place_office_enclosure,
    _place_pallet_jack,
    _place_mezzanine,
    _place_wrapping_station,
    _place_wrapped_pallet,
    _place_hand_truck,
)

__all__ = [
    "_place_column_guard", "_place_charger_box", "_place_shelf_placard",
    "_place_fire_extinguisher", "_place_exit_sign", "_place_trash_bin",
    "_place_pack_table", "_place_cardboard_stack", "_place_floor_arrow",
    "_place_caution_sign", "_place_wall_junction_box", "_place_overhead_light",
    "_place_aisle_sign", "_place_mop_and_bucket", "_place_tire_scuff",
    "_place_oil_stain", "_place_wall_panel_seam", "_place_wall_paint_patch",
    "_place_dock_door", "_place_hazard_hatch", "_place_sprinkler_head",
    "_place_ceiling_pipe_run", "_place_hi_vis_bollard", "_place_empty_pallet_stack",
    "_place_parking_stall", "_place_first_aid_kit", "_place_wall_clock",
    "_place_dock_leveler", "_place_painted_aisle_code", "_place_aisle_mirror",
    "_place_zone_sign", "_place_conveyor_run", "_place_office_enclosure",
    "_place_pallet_jack", "_place_wall_windows", "_place_mezzanine",
    "_place_open_dock_door", "_place_truck_back", "_place_dock_leveler_ramped",
    "_place_wrapping_station", "_place_wrapped_pallet", "_place_hand_truck",
]
