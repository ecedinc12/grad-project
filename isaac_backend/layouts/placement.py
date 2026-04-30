"""
Foundational placement helpers shared by props and spawners.

`_place` is the canonical asset-library reference placer; it tags semantics
and applies a static collider so the navmesh routes around layout items.
The other helpers (`_paint_floor_stripe`, `_stack_boxes`, `_place_rows_in_band`,
`_draw_floor_glyph`) compose `_place` and direct USD prim authoring.
"""

import math
import random

from pxr import UsdGeom, Gf, UsdPhysics
import omni.usd
import omni.kit.commands

from isaac_backend.semantics import apply_usd_semantics

from .geometry import (
    SEMANTIC_MAP,
    RACK_X_EXTENT,
    RACK_DEPTH,
    WALL_CLEARANCE,
    RACK_CEILING_FILL,
)
from .materials import bind_material


_GLYPH_3x5 = {
    "A": "010101111101101", "B": "110101110101110", "C": "011100100100011",
    "D": "110101101101110", "E": "111100110100111", "F": "111100110100100",
    "G": "011100101101011", "H": "101101111101101", "I": "111010010010111",
    "J": "001001001101010", "K": "101110100110101", "L": "100100100100111",
    "M": "101111111101101", "N": "101111111111101", "O": "010101101101010",
    "P": "110101110100100", "Q": "010101101111011", "R": "110101110110101",
    "S": "011100010001110", "T": "111010010010010", "U": "101101101101010",
    "V": "101101101010010", "W": "101101111111101", "X": "101101010101101",
    "Y": "101101101010010", "Z": "111001010100111",
    "0": "111101101101111", "1": "010110010010111", "2": "110001010100111",
    "3": "111001010001111", "4": "101101111001001", "5": "111100111001111",
    "6": "011100111101111", "7": "111001010100100", "8": "111101111101111",
    "9": "111101111001110", "-": "000000111000000", " ": "000000000000000",
}


def _paint_floor_stripe(stage, idx, x, y, length_x, length_y, color, z=0.012):
    """Thin colored cuboid laid on the floor — used for aisle paint, hatched zones."""
    path = f"/World/Layout/floor_stripe_{idx}"
    cube = UsdGeom.Cube.Define(stage, path)
    cube.GetSizeAttr().Set(2.0)  # default unit cube of size 2 (extents ±1)
    prim = cube.GetPrim()
    xf = UsdGeom.XformCommonAPI(prim)
    # Cube default is 2x2x2 → scale halves give the desired full extents.
    xf.SetScale(Gf.Vec3f(length_x / 2.0, length_y / 2.0, 0.012))
    xf.SetTranslate(Gf.Vec3d(x, y, z))
    bind_material(stage, cube, "M_PaintedConcrete", color)
    return idx + 1


def _place(asset_id, x, y, z, rot_z, asset_library, stage, idx, scale=None):
    usd = asset_library.get(asset_id)
    if not usd:
        return idx
    path = f"/World/Layout/{asset_id}_{idx}"
    omni.kit.commands.execute(
        "CreateReferenceCommand",
        usd_context=omni.usd.get_context(),
        path_to=path,
        asset_path=usd,
        instanceable=False,
    )
    prim = stage.GetPrimAtPath(path)
    if not prim.IsValid():
        return idx + 1
    xf = UsdGeom.XformCommonAPI(prim)
    xf.SetTranslate(Gf.Vec3d(x, y, z))
    xf.SetRotate(Gf.Vec3f(0, 0, rot_z), UsdGeom.XformCommonAPI.RotationOrderXYZ)
    if scale is not None:
        if isinstance(scale, (tuple, list)):
            xf.SetScale(Gf.Vec3f(float(scale[0]), float(scale[1]), float(scale[2])))
        else:
            xf.SetScale(Gf.Vec3f(scale, scale, scale))
    semantic_class = SEMANTIC_MAP.get(asset_id, asset_id)
    apply_usd_semantics(prim, semantic_class)
    # Static collision so navmesh routes workers and vehicles around layout items.
    # CollisionAPI only (no RigidBodyAPI) keeps items stationary.
    if not prim.HasAPI(UsdPhysics.CollisionAPI):
        UsdPhysics.CollisionAPI.Apply(prim)
    return idx + 1


def _place_rows_in_band(zone, x_lo, x_hi, y_lo, y_hi, ceiling_z,
                         asset_library, stage, idx):
    """Place a block of rack rows inside one (x_lo..x_hi, y_lo..y_hi) sub-band.

    Each sub-zone overrides global rack params: pattern (EW or NS rows),
    aisle_width, target_rack_height, rack count. Returns the resolved height
    so adjacent sub-zones can read tall vs short, and so the per-rack shelf
    populator can scale shelves to the *zone's* height instead of a single
    warehouse-wide value.
    """
    pattern = zone.get("pattern", "rows")
    aw = float(zone.get("aisle_width", 2.5))
    rows = zone.get("rows", "auto")
    cols = zone.get("cols", "auto")
    target_h = zone.get("target_rack_height", "auto")
    if target_h in (None, "auto"):
        target_h = ceiling_z * RACK_CEILING_FILL
    target_h = float(target_h)
    rack_z_scale = target_h / 2.4

    perpendicular = pattern in ("rows_perp", "rows_NS", "rows_perpendicular")

    if perpendicular:
        # Rack long-axis runs along Y (rrot=0). Rows iterate along X, each
        # row's racks sit along Y at RACK_X_EXTENT pitch.
        rrot = 0
        primary_lo = x_lo + WALL_CLEARANCE
        primary_hi = x_hi - WALL_CLEARANCE
        secondary_lo = y_lo + WALL_CLEARANCE
        secondary_hi = y_hi - WALL_CLEARANCE
    else:
        rrot = 90
        primary_lo = y_lo + WALL_CLEARANCE
        primary_hi = y_hi - WALL_CLEARANCE
        secondary_lo = x_lo + WALL_CLEARANCE
        secondary_hi = x_hi - WALL_CLEARANCE

    primary_avail = primary_hi - primary_lo
    secondary_avail = secondary_hi - secondary_lo
    if primary_avail < RACK_DEPTH or secondary_avail < RACK_X_EXTENT * 0.5:
        return idx, [], target_h, 0

    row_pitch = RACK_DEPTH + aw
    if rows in (None, "auto"):
        rows = max(1, int((primary_avail + aw) / row_pitch))
    rows = int(rows)
    while rows > 1 and (rows * RACK_DEPTH + (rows - 1) * aw) > primary_avail:
        rows -= 1

    if cols in (None, "auto"):
        cols = max(1, int(secondary_avail / RACK_X_EXTENT))
    cols = int(cols)
    if cols < 1 or rows < 1:
        return idx, [], target_h, 0

    block_primary = rows * RACK_DEPTH + max(0, rows - 1) * aw
    primary_center = (primary_lo + primary_hi) / 2.0
    primary_start = primary_center - block_primary / 2.0 + RACK_DEPTH / 2.0

    block_secondary = max(0, cols - 1) * RACK_X_EXTENT
    secondary_center = (secondary_lo + secondary_hi) / 2.0
    secondary_start = secondary_center - block_secondary / 2.0

    positions = []
    count = 0
    for r in range(rows):
        primary = primary_start + r * row_pitch
        for c in range(cols):
            secondary = secondary_start + c * RACK_X_EXTENT
            if perpendicular:
                rx, ry = primary, secondary
            else:
                rx, ry = secondary, primary
            if rx < x_lo + WALL_CLEARANCE or rx > x_hi - WALL_CLEARANCE:
                continue
            if ry < y_lo + WALL_CLEARANCE or ry > y_hi - WALL_CLEARANCE:
                continue
            idx = _place("rack", rx, ry, 0, rrot, asset_library, stage, idx,
                         scale=(1.0, 1.0, rack_z_scale))
            positions.append((rx, ry, rrot))
            count += 1
    return idx, positions, target_h, count


def _stack_boxes(x, y, probs, jitters, asset_library, stage, idx):
    """Stack up to 3 boxes on a pallet at (x, y).

    probs:   (p_first, p_second, p_third) — probability of placing each layer.
    jitters: (j0, j1, j2) — ±XY jitter (metres) per layer.

    Returns updated idx and count of items placed.
    """
    layers = [
        (random.choice(["box", "box_small", "box_large", "crate"]), 0.15, 15),
        (random.choice(["box", "box_small", "crate"]),               0.45, 15),
        (random.choice(["box_small", "crate"]),                      0.72, 10),
    ]
    count = 0
    for (prop, z, rot_max), prob, jitter in zip(layers, probs, jitters):
        if random.random() >= prob:
            break
        idx = _place(prop,
                     x + random.uniform(-jitter, jitter),
                     y + random.uniform(-jitter, jitter),
                     z, random.uniform(-rot_max, rot_max),
                     asset_library, stage, idx)
        count += 1
    return idx, count


def _count_clutter_for_density(density):
    return {"low": 8, "medium": 18, "high": 30}.get(density, 18)


def aw_dump(zone):
    return zone.get("aisle_width", "?")


def _draw_floor_glyph(stage, idx, text, x_center, y_center, cell_size=0.18,
                       color=(0.06, 0.06, 0.06), z=0.018, rot_z=0):
    """Render `text` (3x5 bitmap font) as thin floor cubes centered at
    (x_center, y_center). Used for painted aisle codes."""
    chars = list(text.upper())
    n = len(chars)
    char_w_cells, gap_cells = 3, 1
    total_cells_x = n * char_w_cells + max(0, n - 1) * gap_cells
    total_w = total_cells_x * cell_size
    total_h = 5 * cell_size
    ang = math.radians(rot_z)
    cos_a, sin_a = math.cos(ang), math.sin(ang)
    sx = -total_w / 2.0 + cell_size / 2.0
    sy = -total_h / 2.0 + cell_size / 2.0
    placed = 0
    for ci, ch in enumerate(chars):
        bits = _GLYPH_3x5.get(ch, _GLYPH_3x5[" "])
        for r in range(5):
            for c in range(3):
                if bits[r * 3 + c] != "1":
                    continue
                lx = sx + (ci * (char_w_cells + gap_cells) + c) * cell_size
                ly = sy + (4 - r) * cell_size
                wx = x_center + lx * cos_a - ly * sin_a
                wy = y_center + lx * sin_a + ly * cos_a
                path = f"/World/Layout/glyph_{idx}_{placed}"
                cube = UsdGeom.Cube.Define(stage, path)
                cube.GetSizeAttr().Set(2.0)
                xf = UsdGeom.XformCommonAPI(cube.GetPrim())
                xf.SetScale(Gf.Vec3f(cell_size / 2.0 * 0.9,
                                     cell_size / 2.0 * 0.9, 0.012))
                xf.SetTranslate(Gf.Vec3d(wx, wy, z))
                xf.SetRotate(Gf.Vec3f(0, 0, rot_z),
                             UsdGeom.XformCommonAPI.RotationOrderXYZ)
                bind_material(stage, cube, "M_PaintedConcrete", color)
                placed += 1
    return idx + placed
