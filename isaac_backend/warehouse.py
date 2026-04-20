"""
Warehouse Layout Spawner

Delegates to the procedural layout generator in layouts.py.
"""

from pxr import UsdGeom
from isaac_backend.layouts import generate_layout

_RACK_KEYWORDS = {"rackframe", "rack_frame", "sm_rack", "shelving", "shelf_unit"}


def spawn_warehouse_layout(scene_config, asset_library, stage):
    """Dispatch to procedural layout generator and return (bounds_min, bounds_max)."""
    layout_name = scene_config.get("layout", "standard_warehouse")
    layout_params = scene_config.get("layout_params", None)
    bounds_min, bounds_max = generate_layout(layout_name, layout_params, asset_library, stage)
    return bounds_min, bounds_max


def hide_warehouse_rack_frames(stage):
    """Hide rack frame meshes baked into the warehouse.usd environment asset.

    The Simple_Warehouse USD ships with freestanding SM_RackFrame props as
    part of the scene. Since we control prop placement through the layout
    generator, these baked-in frames create visual clutter. Hide them by
    name rather than deleting so semantic labels and physics are unaffected.
    """
    hidden = 0
    for prim in stage.Traverse():
        name_lower = prim.GetName().lower()
        if any(kw in name_lower for kw in _RACK_KEYWORDS):
            UsdGeom.Imageable(prim).MakeInvisible()
            print(f"[INFO] Hid warehouse rack prim: {prim.GetPath()}")
            hidden += 1
    print(f"[INFO] Hid {hidden} baked-in rack frame prim(s) from warehouse.usd.")


def hide_driver_prims(stage):
    """Hide baked-in driver/operator meshes inside vehicle assets."""
    hidden = 0
    for prim in stage.Traverse():
        if "driver" in prim.GetName().lower():
            UsdGeom.Imageable(prim).MakeInvisible()
            print(f"[INFO] Hid driver prim: {prim.GetPath()}")
            hidden += 1
    if hidden == 0:
        print("[INFO] No driver prims found (forklift not in scene, or prim name differs).")
