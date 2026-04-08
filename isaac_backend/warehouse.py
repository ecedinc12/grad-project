import random
from pxr import UsdGeom, Gf
import omni.usd
import omni.kit.commands
from isaac_backend.semantics import apply_semantics

def spawn_warehouse_layout(asset_library):
    """Build an organised warehouse interior: rack rows, pallet staging, aisle clutter."""
    stage = omni.usd.get_context().get_stage()
    _idx = [0]
    spawned = 0

    def place(asset_id, x, y, z=0, rot_z=0):
        nonlocal spawned
        usd = asset_library.get(asset_id)
        if not usd:
            return
        path = f"/World/Layout/{asset_id}_{_idx[0]}"
        _idx[0] += 1
        omni.kit.commands.execute(
            "CreateReferenceCommand",
            usd_context=omni.usd.get_context(),
            path_to=path,
            asset_path=usd,
            instanceable=False,
        )
        prim = stage.GetPrimAtPath(path)
        if not prim.IsValid():
            return
        xf = UsdGeom.XformCommonAPI(prim)
        xf.SetTranslate(Gf.Vec3d(x, y, z))
        xf.SetRotate(Gf.Vec3f(0, 0, rot_z), UsdGeom.XformCommonAPI.RotationOrderXYZ)
        apply_semantics(path, asset_id)
        spawned += 1

    rack_xs = [-6, -3, 0, 3, 6]

    for x in rack_xs:
        place("rack",   x,    7.0, rot_z=90)
        place("pallet", x,    5.8, rot_z=random.uniform(-20, 20))

    for x in rack_xs:
        place("rack", x, 3.0, rot_z=90)

    for x in rack_xs:
        place("rack",   x,   -3.0, rot_z=270)
        place("pallet", x,   -1.8, rot_z=random.uniform(-20, 20))

    for dx, dy in [(-1.0, 0.0), (0.5, 0.2), (2.0, -0.3), (-2.5, 0.1)]:
        place("pallet", dx, dy, rot_z=random.uniform(0, 90))

    small = ["box"] * 6 + ["barrel"] * 4 + ["cone"] * 4
    random.shuffle(small)
    for prop in small[:8]:
        place(prop,
              random.uniform(-5.5, 5.5),
              random.uniform(-1.5, 1.5),
              rot_z=random.uniform(0, 360))
    for prop in small[8:]:
        place(prop,
              random.uniform(-5.0, 5.0),
              random.uniform(-6.0, -4.2),
              rot_z=random.uniform(0, 360))

    print(f"[INFO] Spawned {spawned} layout props.")

def hide_driver_prims():
    """Hide baked-in driver/operator meshes inside vehicle assets."""
    stage = omni.usd.get_context().get_stage()
    hidden = 0
    for prim in stage.Traverse():
        if "driver" in prim.GetName().lower():
            UsdGeom.Imageable(prim).MakeInvisible()
            print(f"[INFO] Hid driver prim: {prim.GetPath()}")
            hidden += 1
    if hidden == 0:
        print("[INFO] No driver prims found (forklift not in scene, or prim name differs).")
