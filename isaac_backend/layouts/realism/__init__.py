"""Realism-detail spawners.

Submodules group passes by domain:
  floor       — floor filling, aisle wear
  walls       — wall fixtures, panel seams
  atmosphere  — incidental clutter, polish pass, ceiling/atmosphere props
  equipment   — static equipment (chargers, parked forklifts)
  wear        — material wear and human-imperfection items
  layers      — composite passes that orchestrate the above
"""

from .floor import _spawn_floor_filling, _spawn_aisle_floor_wear
from .walls import _spawn_wall_details, _spawn_wall_panel_seams
from .atmosphere import _spawn_clutter, _spawn_polish_pass, _spawn_atmosphere_clutter
from .equipment import _spawn_charging_station, _spawn_mid_aisle_forklift
from .wear import _spawn_realism_extras, _spawn_human_imperfection
from .layers import _spawn_realism_layer, _spawn_realism_layer_2

__all__ = [
    "_spawn_clutter", "_spawn_charging_station", "_spawn_wall_details",
    "_spawn_realism_extras", "_spawn_aisle_floor_wear", "_spawn_human_imperfection",
    "_spawn_mid_aisle_forklift", "_spawn_floor_filling", "_spawn_polish_pass",
    "_spawn_realism_layer", "_spawn_realism_layer_2", "_spawn_atmosphere_clutter",
    "_spawn_wall_panel_seams",
]
