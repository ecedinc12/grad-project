import os
import carb
import omni.kit.app
import omni.timeline
import omni.usd
import omni.kit.commands
from pxr import UsdGeom, Gf

def enable_extensions():
    """Enable all extensions required for omni.anim.people to animate characters."""
    manager = omni.kit.app.get_app().get_extension_manager()
    required = [
        "omni.anim.graph.core",
        "omni.anim.behavior.schema",
        "omni.anim.people",
        "omni.anim.navigation.core",
    ]
    for ext in required:
        if not manager.is_extension_enabled(ext):
            print(f"[INFO] Enabling extension: {ext}")
            manager.set_extension_enabled_immediate(ext, True)
        else:
            print(f"[INFO] Extension already active: {ext}")

def setup_navmesh(bounds_min=(-10, -10), bounds_max=(10, 10), height=4.0):
    """Bake a navmesh covering the scene for omni.anim.people GoTo commands.

    Creates a NavMeshVolume prim that encompasses the scene, then triggers a
    navmesh bake via ``RebuildNavMesh`` command.  If the bake fails (e.g. the
    navigation extension is unavailable), falls back to direct-navigation mode
    where characters walk in straight lines without pathfinding.

    Returns True if navmesh was baked successfully, False if using direct nav.
    """
    stage = omni.usd.get_context().get_stage()
    settings = carb.settings.get_settings()

    vol_path = "/World/NavMeshVolume"
    vol_prim = stage.DefinePrim(vol_path, "Cube")
    vol_prim.GetAttribute("size").Set(1.0)

    center_x = (bounds_min[0] + bounds_max[0]) / 2.0
    center_y = (bounds_min[1] + bounds_max[1]) / 2.0
    scale_x = abs(bounds_max[0] - bounds_min[0])
    scale_y = abs(bounds_max[1] - bounds_min[1])

    xform = UsdGeom.Xformable(vol_prim)
    xform.ClearXformOpOrder()
    xform.AddTranslateOp().Set(Gf.Vec3d(center_x, center_y, height / 2.0))
    xform.AddScaleOp().Set(Gf.Vec3f(scale_x, scale_y, height))

    vol_prim.SetCustomDataByKey("omni:navmesh:volume", True)
    vol_prim.SetCustomDataByKey("omni:navmesh:auto_rebuild", False)

    try:
        omni.kit.commands.execute("RebuildNavMesh")
        settings.set("/exts/omni.anim.people/navigation_settings/navmesh_enabled", True)
        settings.set("/persistent/omni/anim/people/navmeshBasedNavigation", True)
        print(f"[INFO] NavMesh baked successfully (volume {scale_x:.1f}x{scale_y:.1f}x{height:.1f}m).")
        return True
    except Exception as e:
        print(f"[WARN] NavMesh bake failed ({e}), falling back to direct navigation.")
        try:
            stage.RemovePrim(vol_prim.GetPath())
        except Exception:
            pass
        settings.set("/exts/omni.anim.people/navigation_settings/navmesh_enabled", False)
        settings.set("/persistent/omni/anim/people/navmeshBasedNavigation", False)
        print("[INFO] Direct navigation active (navmesh not available).")
        return False

def setup_people_simulation(command_file, navmesh_enabled=False):
    """Configure omni.anim.people with character root path and command file.

    Parameters
    ----------
    command_file : str
        Absolute path to the people_commands.txt file.
    navmesh_enabled : bool
        Whether a navmesh was successfully baked.  When True the character
        GoTo commands will use pathfinding; when False they walk in
        straight lines.
    """
    settings = carb.settings.get_settings()
    settings.set("/persistent/exts/omni.anim.people/character_prim_path", "/World/Characters")
    settings.set("/exts/omni.anim.people/command_settings/command_file_path", command_file)
    settings.set("/exts/omni.anim.people/command_settings/number_of_loop", "inf")
    settings.set("/exts/omni.anim.people/navigation_settings/navmesh_enabled", navmesh_enabled)
    settings.set("/exts/omni.anim.people/navigation_settings/dynamic_avoidance_enabled", navmesh_enabled)
    nav_str = "navmesh" if navmesh_enabled else "direct"
    print(f"[INFO] People simulation configured ({nav_str} nav), command file: {command_file}")

def write_command_file(worker_behaviors, path, worker_names=None):
    """Serialise worker_behaviors to the IRA command-file format.

    Each line follows the format recognised by ``character_behavior.py``::

        <character_name> <Command> [args...]

    For example::

        worker_01 GoTo 3.0 -1.5 0.0 45.0
        worker_01 Idle 5.0
        worker_02 LookAround 3.0

    Parameters
    ----------
    worker_behaviors : list[dict]
        List of WorkerBehavior dicts with ``worker_id`` and ``commands``.
    path : str
        Output file path for the command file.
    worker_names : set[str] | None
        If provided, only commands for character names that exist in this set
        are written.  This prevents orphan commands for characters that failed
        to spawn.
    """
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    lines = []
    skipped = 0
    for wb in worker_behaviors:
        worker_id = wb.get("worker_id", "worker_01")
        if worker_names is not None and worker_id not in worker_names:
            skipped += 1
            continue
        cmds = wb.get("commands", [])
        if not cmds:
            lines.append(f"{worker_id} Idle 5.0")
            continue
        for cmd in cmds:
            command = cmd.get("command")
            if command == "GoTo":
                x = cmd.get("x", 0.0)
                y = cmd.get("y", 0.0)
                z = cmd.get("z", 0.0)
                rot = cmd.get("rotation", 0.0)
                lines.append(f"{worker_id} GoTo {x} {y} {z} {rot}")
            elif command in ("Idle", "LookAround"):
                dur = cmd.get("duration", 2.0)
                lines.append(f"{worker_id} {command} {dur}")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    msg = f"[INFO] Wrote {len(lines)} command lines to {path}"
    if skipped:
        msg += f" (skipped {skipped} behaviours for non-existent characters)"
    print(msg)