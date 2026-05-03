"""Atmospheric clutter, polish-pass overhead detail."""

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
