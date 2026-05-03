"""
Procedural Layout Generator

Reads layout presets from assets/layouts.json, merges with user overrides,
and spawns racks, rack shelf inventory, pallets (loaded), dock areas,
and clutter props into the USD stage.
"""

from .geometry import (
    LAYOUTS,
    _measure_ceiling_z,
    _measure_floor_bounds,
    _affine_remap,
    _resolve_params,
)
from .materials import reset_material_cache
from .rack import (
    _spawn_racks,
    _populate_rack_shelves,
    _spawn_column_guards,
    _spawn_rack_end_details,
)
from .dock import (
    _spawn_pallets,
    _spawn_dock_area,
    _spawn_bulk_stock,
    _spawn_dock_doors,
)
from .marking import (
    _spawn_floor_markings,
    _spawn_main_aisle_treatment,
    _spawn_marshalling_band,
    _spawn_pedestrian_crossing_paint,
)
from .realism import (
    _spawn_clutter,
    _spawn_charging_station,
    _spawn_wall_details,
    _spawn_realism_extras,
    _spawn_aisle_floor_wear,
    _spawn_human_imperfection,
    _spawn_mid_aisle_forklift,
    _spawn_floor_filling,
    _spawn_polish_pass,
    _spawn_realism_layer,
    _spawn_realism_layer_2,
    _spawn_atmosphere_clutter,
)


def generate_layout(layout_name, layout_params, asset_library, stage):
    reset_material_cache()
    params = _resolve_params(layout_name, layout_params, LAYOUTS)

    # Measure the actual interior height of whatever warehouse asset was loaded
    # so racks, ceiling pipes, sprinklers, lights, and aisle signs all auto-
    # scale to the environment instead of carrying baked-in numbers.
    if "ceiling_z" not in params:
        params["ceiling_z"] = _measure_ceiling_z(stage)

    # Auto-fit XY bounds to the warehouse asset, unless the caller pinned
    # bounds explicitly. The preset's bounds_min/max are treated as the
    # design coordinate system; clutter_zones (and any other bounded params
    # authored against them) are remapped onto the measured rectangle so the
    # whole layout breathes with the warehouse instead of clumping in the
    # middle when the asset is larger than the preset assumed.
    # The bounds carried by `params` (from the JSON preset and any LLM-supplied
    # layout_params) are a *design coordinate space* — what the prompt/preset
    # was authored against. We always remap onto the measured warehouse so the
    # layout breathes with the actual asset. The LLM defaults to ±6m, which is
    # smaller than the warehouse interior, so without remapping the layout
    # clumps in the middle. Pass auto_fit_bounds=False in layout_params to opt
    # out (e.g. for hand-tuned coordinate scenes).
    auto_fit = True
    if layout_params and layout_params.get("auto_fit_bounds") is False:
        auto_fit = False
    print(f"[INFO] Bounds resolution: auto_fit={auto_fit}, "
          f"design bounds_min={params['bounds_min']} bounds_max={params['bounds_max']}, "
          f"layout_params={'<dict>' if layout_params else layout_params}")
    if auto_fit:
        m_min, m_max = _measure_floor_bounds(stage)
        if m_min is not None:
            design_min = params["bounds_min"]
            design_max = params["bounds_max"]
            params["bounds_min"] = m_min
            params["bounds_max"] = m_max
            for zone in params.get("clutter_zones", []):
                if "bounds_min" in zone:
                    zone["bounds_min"] = _affine_remap(
                        zone["bounds_min"], design_min, design_max, m_min, m_max)
                if "bounds_max" in zone:
                    zone["bounds_max"] = _affine_remap(
                        zone["bounds_max"], design_min, design_max, m_min, m_max)
        else:
            print("[WARN] _measure_floor_bounds returned None — using design "
                  f"bounds_min={params['bounds_min']} bounds_max={params['bounds_max']}")
    print(f"[INFO] Final layout bounds: bounds_min={params['bounds_min']} "
          f"bounds_max={params['bounds_max']}")

    idx = 0
    num_racks = 0
    num_pallets = 0
    num_clutter = 0
    num_shelf_items = 0
    num_dock_items = 0

    idx, num_racks, rack_positions = _spawn_racks(params, asset_library, stage, idx)

    idx, num_shelf_items = _populate_rack_shelves(
        rack_positions, params, asset_library, stage, idx
    )

    # When dock_area is enabled, _spawn_dock_area is the canonical dock-zone
    # populator — gate _spawn_pallets off to avoid two competing pallet grids
    # in the same Y band.
    if params.get("dock_area", False):
        num_pallets = 0
    else:
        idx, num_pallets = _spawn_pallets(params, asset_library, stage, idx)

    idx, num_clutter = _spawn_clutter(params, asset_library, stage, idx)

    if params.get("dock_area", False):
        idx, num_dock_items = _spawn_dock_area(params, asset_library, stage, idx)

    idx, num_bulk = _spawn_bulk_stock(params, asset_library, stage, idx)

    idx, num_stripes = _spawn_floor_markings(rack_positions, params, stage, idx)
    idx, num_guards = _spawn_column_guards(rack_positions, stage, idx)
    idx, num_charge = _spawn_charging_station(params, asset_library, stage, idx)
    idx, num_rack_extras = _spawn_rack_end_details(rack_positions, asset_library, stage, idx)
    idx, num_wall_extras = _spawn_wall_details(params, asset_library, stage, idx)
    idx, num_realism = _spawn_realism_extras(params, rack_positions, stage, idx)
    idx, num_wear = _spawn_aisle_floor_wear(rack_positions, params, stage, idx)
    idx, num_main_aisle = _spawn_main_aisle_treatment(rack_positions, params, asset_library, stage, idx)
    idx, num_marshal = _spawn_marshalling_band(params, asset_library, stage, idx)
    idx, num_human = _spawn_human_imperfection(rack_positions, params, asset_library, stage, idx)
    idx, num_mid_fork = _spawn_mid_aisle_forklift(rack_positions, params, asset_library, stage, idx)
    num_doors = 0
    if params.get("dock_area", False):
        idx, num_doors = _spawn_dock_doors(params, stage, idx)

    idx, num_floor_fill = _spawn_floor_filling(params, rack_positions, asset_library, stage, idx)
    idx, num_polish = _spawn_polish_pass(params, rack_positions, asset_library, stage, idx)
    idx, num_realism_layer = _spawn_realism_layer(rack_positions, params, asset_library, stage, idx)
    idx, num_realism_layer_2 = _spawn_realism_layer_2(rack_positions, params, asset_library, stage, idx)
    idx, num_atmosphere = _spawn_atmosphere_clutter(rack_positions, params, asset_library, stage, idx)

    num_crosswalk = 0
    if layout_name == "pedestrian_crossing":
        idx, num_crosswalk = _spawn_pedestrian_crossing_paint(params, stage, idx)

    print(f"[INFO] Spawned {num_racks} racks, {num_shelf_items} shelf items, "
          f"{num_pallets} pallets, {num_clutter} clutter props, {num_dock_items} dock items, "
          f"{num_bulk} bulk-stock items, "
          f"{num_stripes} floor stripes, {num_guards} column guards, {num_charge} charge-bay items, "
          f"{num_rack_extras} rack-end details, {num_wall_extras} wall details, "
          f"{num_realism} realism extras, {num_wear} aisle wear, "
          f"{num_main_aisle} main-aisle treatment, {num_marshal} marshalling-band items, "
          f"{num_human} human-imperfection items, {num_mid_fork} mid-aisle forklift, "
          f"{num_doors} dock doors, {num_polish} polish-pass items, "
          f"{num_floor_fill} floor-fill staging items, "
          f"{num_realism_layer} realism-layer items, "
          f"{num_realism_layer_2} realism-layer-2 items, "
          f"{num_atmosphere} atmosphere-clutter items, "
          f"{num_crosswalk} crosswalk-paint stripes.")

    return params["bounds_min"], params["bounds_max"]


__all__ = ["generate_layout", "LAYOUTS"]