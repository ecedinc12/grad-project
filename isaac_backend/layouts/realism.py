"""Realism-detail spawners — clutter, wall fixtures, floor-filling dead
space, polish-pass ceiling/floor details, charging stations, floor wear,
human-imperfection items, mid-aisle forklifts, and the realism-layer pass."""

import math
import random

from .geometry import (
    DEFAULT_CEILING_Z,
    RACK_X_EXTENT,
    RACK_DEPTH,
    CLUTTER_PROPS,
)
from .placement import (
    _place,
    _stack_boxes,
    _paint_floor_stripe,
    _count_clutter_for_density,
)
from .props import (
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
)
from .materials import bind_material
from pxr import UsdGeom, Gf


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


def _spawn_realism_layer_2(rack_positions, params, asset_library, stage, idx):
    """Second realism batch: mezzanine catwalk along one wall, an open dock
    door + truck silhouette + ramped leveler, a stretch-wrap station + 1-2
    wrapped pallets in the marshalling band, light-blue glazed wall windows
    along both long walls (skipping the mezzanine span on its wall), and 3
    manual pallet jacks (rack-end / mid-aisle / marshalling)."""
    bmin = params["bounds_min"]
    bmax = params["bounds_max"]
    span_y = bmax[1] - bmin[1]
    span_x = bmax[0] - bmin[0]
    cx = (bmin[0] + bmax[0]) / 2.0
    cy = (bmin[1] + bmax[1]) / 2.0
    has_dock = params.get("dock_area", False)
    dock_frac = params.get("dock_zone_frac", 0.25)
    dock_y_top = bmin[1] + dock_frac * span_y
    count = 0

    # 1) Mezzanine along the +X wall, back-third. Gate independent of dock so
    # standard layouts also get the elevated catwalk silhouette.
    mezz_y_lo = (dock_y_top + 1.5) if has_dock else (bmin[1] + 0.30 * span_y)
    mezz_y_hi = bmax[1] - 1.5
    mezz_active = mezz_y_hi - mezz_y_lo >= 4.0
    if mezz_active:
        idx = _place_mezzanine(stage, idx, bmax[0] - 0.30,
                                mezz_y_lo, mezz_y_hi,
                                depth=2.2, height=3.4, side=-1)
        count += 1

    # 2) Open dock door + truck silhouette + ramped leveler.
    if has_dock:
        door_w = 2.6
        spacing = door_w + 1.4
        n_doors = max(1, int((span_x - 2.0) / spacing))
        total_w = (n_doors - 1) * spacing
        x_start = cx - total_w / 2.0
        open_idx = params.get("_open_dock_door_idx", n_doors // 2)
        open_idx = max(0, min(n_doors - 1, open_idx))
        open_x = x_start + open_idx * spacing
        wall_y = bmin[1] + 0.06
        idx = _place_open_dock_door(stage, idx, open_x, wall_y,
                                     width=door_w, height=3.2)
        idx = _place_dock_leveler_ramped(stage, idx,
                                          open_x, wall_y - 0.65,
                                          width=door_w - 0.2,
                                          depth=1.4, tilt_deg=10)
        idx = _place_truck_back(stage, idx, open_x, wall_y - 3.0,
                                 width=door_w, depth=4.5, height=3.0)
        count += 3

    # 3) Wrapping station + 1-2 wrapped pallets. Without a dock, drop into the
    # back-center band so standard layouts still get one.
    if has_dock:
        wrap_y = dock_y_top + 0.7
    else:
        wrap_y = cy + 0.20 * span_y
    wrap_x = cx - 4.0
    if "pallet" in asset_library:
        idx = _place_wrapping_station(stage, idx, wrap_x, wrap_y, rot_z=0)
        idx = _place_wrapped_pallet(stage, idx, wrap_x, wrap_y,
                                     asset_library, rot_z=0)
        idx = _place_wrapped_pallet(stage, idx, wrap_x + 1.6, wrap_y - 0.10,
                                     asset_library,
                                     rot_z=random.uniform(-10, 10))
        count += 3

    # 4) Wall windows.
    win_y_lo = bmin[1] + 1.2
    win_y_hi = bmax[1] - 1.2
    if mezz_active:
        idx = _place_wall_windows(stage, idx, bmax[0] - 0.05,
                                    win_y_lo, mezz_y_lo - 0.6,
                                    n_windows=3, z_center=2.2)
    else:
        idx = _place_wall_windows(stage, idx, bmax[0] - 0.05,
                                    win_y_lo, win_y_hi,
                                    n_windows=5, z_center=2.4)
    # -X wall: avoid the office (back-left corner used by realism_layer 1).
    idx = _place_wall_windows(stage, idx, bmin[0] + 0.05,
                                win_y_lo, bmax[1] - 4.0,
                                n_windows=4, z_center=2.4)
    count += 2

    # 5) Pallet jacks: 3 rack-end + up to 2 mid-aisle + (dock-only) marshalling.
    rows = {}
    for (rx, ry, rrot) in rack_positions:
        if rrot == 90:
            key = round(ry * 2) / 2.0
            rows.setdefault(key, []).append(rx)
    jack_palette = [
        (0.85, 0.20, 0.20),
        (0.20, 0.45, 0.65),
        (0.85, 0.65, 0.10),
        (0.30, 0.55, 0.30),
        (0.55, 0.30, 0.55),
    ]
    if rows:
        row_keys = list(rows.keys())
        random.shuffle(row_keys)
        for row_key in row_keys[:3]:
            xs = rows[row_key]
            side = random.choice((-1, 1))
            anchor_x = (max(xs) + 1.55) if side > 0 else (min(xs) - 1.55)
            idx = _place_pallet_jack(stage, idx,
                                      anchor_x,
                                      row_key + random.uniform(-0.30, 0.30),
                                      rot_z=random.uniform(-30, 30) + (0 if side > 0 else 180),
                                      color=random.choice(jack_palette))
            count += 1
        sorted_keys = sorted(rows.keys())
        # Up to 2 mid-aisle jacks in the gaps between adjacent rack rows.
        gap_pairs = list(zip(sorted_keys, sorted_keys[1:]))
        random.shuffle(gap_pairs)
        for (a, b) in gap_pairs[:2]:
            mid_y = (a + b) / 2.0
            xs0 = rows[a] + rows[b]
            mid_x = sum(xs0) / len(xs0) + random.uniform(-1.5, 1.5)
            idx = _place_pallet_jack(stage, idx, mid_x, mid_y,
                                      rot_z=random.uniform(0, 360),
                                      color=random.choice(jack_palette))
            count += 1
    if has_dock:
        idx = _place_pallet_jack(stage, idx, cx + 3.0,
                                  dock_y_top + 0.9,
                                  rot_z=random.uniform(0, 360),
                                  color=random.choice(jack_palette))
        count += 1

    print(f"[INFO] Spawned realism-layer 2: {count} grouped items "
          f"(mezzanine / open dock / wrap station / windows / pallet jacks)")
    return idx, count


def _spawn_atmosphere_clutter(rack_positions, params, asset_library, stage, idx):
    """Final pass: scatter human-activity markers — fallen single boxes, tilted
    cones, dropped cardboard sheets, hand trucks, leaning empty pallets, and
    wall safety posters. Runs after realism-layer-2 so positions can dodge
    rack-occupied bands and existing pallet jacks heuristically."""
    bmin = params["bounds_min"]
    bmax = params["bounds_max"]
    span_x = bmax[0] - bmin[0]
    span_y = bmax[1] - bmin[1]
    cx = (bmin[0] + bmax[0]) / 2.0
    cy = (bmin[1] + bmax[1]) / 2.0
    has_dock = params.get("dock_area", False)
    dock_frac = params.get("dock_zone_frac", 0.25)
    dock_y_top = bmin[1] + dock_frac * span_y
    count = 0

    # Build aisle band Y-keys from rack rows (rot=90 racks lie along X).
    rack_ys = sorted({round(ry * 2) / 2.0
                      for (rx, ry, rrot) in rack_positions if rrot == 90})

    def _rand_aisle_xy():
        if len(rack_ys) >= 2:
            i = random.randint(0, len(rack_ys) - 2)
            y = (rack_ys[i] + rack_ys[i + 1]) / 2.0 + random.uniform(-0.3, 0.3)
        else:
            y = random.uniform(bmin[1] + 1.0, bmax[1] - 1.0)
        x = random.uniform(bmin[0] + 1.5, bmax[0] - 1.5)
        return x, y

    # 1) Fallen single boxes — 1-layer stacks with strong tilt baked in.
    n_fallen = random.randint(4, 6)
    for _ in range(n_fallen):
        fx, fy = _rand_aisle_xy()
        idx, n = _stack_boxes(fx + random.uniform(-0.15, 0.15),
                              fy + random.uniform(-0.15, 0.15),
                              (1.0, 0.0, 0.0), (0.0, 0.0, 0.0),
                              asset_library, stage, idx)
        count += n

    # 2) Tilted / knocked-over cones along aisle edges. Use base "cone" prop
    # rotated about X to lie on its side.
    if "cone" in asset_library:
        for _ in range(random.randint(2, 3)):
            cnx, cny = _rand_aisle_xy()
            idx = _place("cone", cnx, cny, 0.10,
                         random.uniform(0, 360), asset_library, stage, idx)
            count += 1

    # 3) Dropped cardboard sheet stacks along the wall band (low height).
    for _ in range(3):
        side_x = random.choice((bmin[0] + 0.6, bmax[0] - 0.6))
        wy = random.uniform(bmin[1] + 1.0, bmax[1] - 1.0)
        idx = _place_cardboard_stack(stage, idx,
                                     side_x + random.uniform(-0.10, 0.10),
                                     wy + random.uniform(-0.10, 0.10),
                                     rot_z=random.uniform(0, 360),
                                     sheets=random.randint(3, 7))
        count += 1

    # 4) Hand trucks: 1 near rack-end, optionally 1 near charging band.
    if rack_positions:
        rx, ry, rrot = random.choice(rack_positions)
        ht_x = rx + random.uniform(-1.8, 1.8)
        ht_y = ry + random.uniform(-1.2, 1.2)
        idx = _place_hand_truck(stage, idx, ht_x, ht_y,
                                rot_z=random.uniform(0, 360))
        count += 1
    if random.random() < 0.6:
        idx = _place_hand_truck(stage, idx,
                                cx + random.uniform(-2.0, 2.0),
                                cy + random.uniform(-1.0, 1.0),
                                rot_z=random.uniform(0, 360),
                                color=(0.55, 0.10, 0.10))
        count += 1

    # 5) Leaning empty pallets against the back wall. Use the asset directly,
    # tilted on local Y so it leans against +Y wall.
    if "pallet" in asset_library:
        for i in range(2):
            lx = bmin[0] + (0.20 + 0.55 * (i + random.uniform(-0.05, 0.05))) * span_x
            ly = bmax[1] - 0.45
            # Lean ~75° away from vertical via tilt; _place takes z + rot_z so
            # we place flush to wall with a yaw rotation. True tilt would need
            # a custom xform; cheap proxy: stand pallet on its long edge.
            idx = _place("pallet", lx, ly, 0.50,
                         random.uniform(85, 95), asset_library, stage, idx)
            count += 1

    # 6) Wall safety posters — colored quads on long walls at eye height.
    poster_colors = [
        (0.85, 0.15, 0.15),  # red — fire/warning
        (0.95, 0.80, 0.10),  # yellow — caution
        (0.10, 0.55, 0.25),  # green — first aid / exit
        (0.15, 0.30, 0.70),  # blue — info
    ]
    poster_z = 1.85
    poster_w = 0.50
    poster_h = 0.70
    n_per_wall = random.randint(2, 3)
    for wall_x, normal_x in ((bmin[0] + 0.04, 1), (bmax[0] - 0.04, -1)):
        for i in range(n_per_wall):
            py = bmin[1] + (i + 0.5 + random.uniform(-0.1, 0.1)) * span_y / n_per_wall
            color = random.choice(poster_colors)
            poster_path = f"/World/Layout/wall_poster_{idx}"
            quad = UsdGeom.Cube.Define(stage, poster_path)
            quad.GetSizeAttr().Set(2.0)
            qxf = UsdGeom.XformCommonAPI(quad.GetPrim())
            qxf.SetScale(Gf.Vec3f(0.012, poster_w / 2.0, poster_h / 2.0))
            qxf.SetTranslate(Gf.Vec3d(wall_x, py, poster_z))
            bind_material(stage, quad, "M_PlasticMatte", color)
            # Thin white inner label band for variety.
            label_path = f"/World/Layout/wall_poster_band_{idx}_b"
            band = UsdGeom.Cube.Define(stage, label_path)
            band.GetSizeAttr().Set(2.0)
            bxf = UsdGeom.XformCommonAPI(band.GetPrim())
            bxf.SetScale(Gf.Vec3f(0.013, poster_w / 2.0 - 0.05, 0.05))
            bxf.SetTranslate(Gf.Vec3d(wall_x + normal_x * 0.001, py,
                                       poster_z - poster_h / 2.0 + 0.10))
            bind_material(stage, band, "M_PaintedWall", (0.95, 0.95, 0.95))
            idx += 1
            count += 1

    # 7) Stretch-wrap roll on floor (white cylinder lying down) near
    # marshalling band — only if not already in dock zone.
    if not has_dock:
        roll_path = f"/World/Layout/wrap_roll_{idx}"
        roll = UsdGeom.Cylinder.Define(stage, roll_path)
        roll.GetRadiusAttr().Set(0.10)
        roll.GetHeightAttr().Set(0.45)
        roll.GetAxisAttr().Set("Y")
        rxf = UsdGeom.XformCommonAPI(roll.GetPrim())
        rxf.SetTranslate(Gf.Vec3d(cx + random.uniform(-1.5, 1.5),
                                   cy + 0.20 * span_y + random.uniform(-0.5, 0.5),
                                   0.10))
        rxf.SetRotate(Gf.Vec3f(0, 0, random.uniform(0, 90)),
                      UsdGeom.XformCommonAPI.RotationOrderXYZ)
        bind_material(stage, roll, "M_StretchFilm", (0.92, 0.94, 0.96))
        idx += 1
        count += 1

    print(f"[INFO] Spawned atmosphere clutter: {count} items "
          f"(fallen boxes / cones / cardboard / hand trucks / leaning pallets / posters)")
    return idx, count