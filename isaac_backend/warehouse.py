"""
Warehouse Layout Spawner

Delegates to the procedural layout generator in layouts.py.
"""

from pxr import UsdGeom
from isaac_backend.layouts import generate_layout


def spawn_warehouse_layout(scene_config, asset_library, stage):
    """Dispatch to procedural layout generator and return (bounds_min, bounds_max)."""
    layout_name = scene_config.get("layout", "standard_warehouse")
    layout_params = scene_config.get("layout_params", None)
    bounds_min, bounds_max = generate_layout(layout_name, layout_params, asset_library, stage)
    return bounds_min, bounds_max


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
