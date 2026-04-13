import os
from pxr import Sdf
import omni.usd
import omni.kit.app
import omni.kit.commands

EXPOSED_ATTR_NS = "rep:behaviors"

_PATROL_SCRIPT = os.path.join(os.path.dirname(__file__), "behaviors", "worker_patrol.py")
_IDLE_POSE_SCRIPT = os.path.join(os.path.dirname(__file__), "behaviors", "worker_idle_pose.py")


def _enable_behavior_extension(simulation_app=None):
    status = True
    manager = omni.kit.app.get_app().get_extension_manager()
    for ext in [
        "isaacsim.replicator.behavior",
        "omni.anim.graph.core",
    ]:
        try:
            if not manager.is_extension_enabled(ext):
                print(f"[INFO] Enabling extension: {ext}")
                manager.set_extension_enabled_immediate(ext, True)
            else:
                print(f"[INFO] Extension already active: {ext}")
        except Exception as e:
            print(f"[WARN] Failed to enable extension {ext}: {e}")
            status = False
    if simulation_app:
        for _ in range(30):
            simulation_app.update()
    return status


def _resolve_script_path(script_file):
    return os.path.abspath(script_file)


def _set_exposed_attr(prim, namespace, attr_name, value, attr_type):
    full_name = f"{EXPOSED_ATTR_NS}:{namespace}:{attr_name}"
    attr = prim.GetAttribute(full_name)
    if attr and attr.IsValid():
        attr.Set(value)
    else:
        prim.CreateAttribute(full_name, attr_type, True).Set(value)


def _apply_scripting_api(prim_path):
    try:
        omni.kit.commands.execute(
            "ApplyScriptingAPICommand",
            paths=[Sdf.Path(prim_path)],
        )
        return True
    except Exception as e:
        print(f"[WARN] ApplyScriptingAPICommand failed for {prim_path}: {e}")
        return False


def _attach_behavior_script(prim, script_path):
    if not prim or not prim.IsValid():
        print(f"[ERROR] Prim invalid, cannot attach behavior script.")
        return False
    script_path = _resolve_script_path(script_path)
    if not os.path.isfile(script_path):
        print(f"[WARN] Behavior script not found at {script_path}")
    attr = prim.GetAttribute("omni:scripting:scripts")
    if not attr or not attr.IsValid():
        attr = prim.CreateAttribute("omni:scripting:scripts", Sdf.ValueTypeNames.StringArray, True)
    attr.Set([script_path])
    print(f"[INFO] Attached behavior script to {prim.GetPath()}: {os.path.basename(script_path)}")
    return True


def attach_worker_patrol(prim_path, waypoints, speed=1.0, idle_duration=3.0,
                         look_around_duration=2.0, simulation_app=None):
    stage = omni.usd.get_context().get_stage()
    prim = stage.GetPrimAtPath(prim_path)
    if not prim or not prim.IsValid():
        print(f"[ERROR] Prim not valid: {prim_path}")
        return False

    _apply_scripting_api(prim_path)
    _attach_behavior_script(prim, _PATROL_SCRIPT)

    waypoints_csv = ";".join(
        f"{wp[0]},{wp[1]},{wp[2]},{wp[3]}"
        for wp in waypoints
    )
    _set_exposed_attr(prim, "workerPatrol", "waypoints:csv", waypoints_csv, Sdf.ValueTypeNames.String)
    _set_exposed_attr(prim, "workerPatrol", "speed", speed, Sdf.ValueTypeNames.Float)
    _set_exposed_attr(prim, "workerPatrol", "idleDuration", idle_duration, Sdf.ValueTypeNames.Float)
    _set_exposed_attr(prim, "workerPatrol", "lookAroundDuration", look_around_duration, Sdf.ValueTypeNames.Float)

    print(f"[INFO] WorkerPatrol attached to {prim_path} with {len(waypoints)} waypoints")
    return True


def attach_worker_idle_pose(prim_path, interval=10, rotation_range=(-15.0, 15.0)):
    stage = omni.usd.get_context().get_stage()
    prim = stage.GetPrimAtPath(prim_path)
    if not prim or not prim.IsValid():
        print(f"[ERROR] Prim not valid: {prim_path}")
        return False

    _apply_scripting_api(prim_path)
    _attach_behavior_script(prim, _IDLE_POSE_SCRIPT)

    _set_exposed_attr(prim, "workerIdlePose", "interval", interval, Sdf.ValueTypeNames.UInt)
    range_csv = f"{rotation_range[0]},{rotation_range[1]}"
    _set_exposed_attr(prim, "workerIdlePose", "rotationRange:csv", range_csv, Sdf.ValueTypeNames.String)

    print(f"[INFO] WorkerIdlePose attached to {prim_path} (interval={interval}, range={rotation_range})")
    return True


def _extract_waypoints(worker_behavior):
    waypoints = []
    for cmd in worker_behavior.get("commands", []):
        if cmd.get("command") == "GoTo":
            wp = (cmd.get("x", 0.0), cmd.get("y", 0.0), cmd.get("z", 0.0), cmd.get("rotation", 0.0))
            waypoints.append(wp)
    return waypoints


def setup_all_behaviors(spawned_worker_names, worker_behaviors, stage, simulation_app=None):
    _enable_behavior_extension(simulation_app)

    attached = 0
    failed = 0

    for wb in worker_behaviors:
        worker_id = wb.get("worker_id", "worker_01")
        if worker_id not in spawned_worker_names:
            print(f"[INFO] Skipping behavior for non-spawned worker: {worker_id}")
            continue

        prim_path = f"/World/Characters/{worker_id}"
        prim = stage.GetPrimAtPath(prim_path)
        if not prim or not prim.IsValid():
            print(f"[WARN] Prim not found for {worker_id}: {prim_path}")
            failed += 1
            continue

        waypoints = _extract_waypoints(wb)

        if waypoints:
            success = attach_worker_patrol(
                prim_path, waypoints,
                speed=1.0,
                idle_duration=3.0,
                look_around_duration=2.0,
                simulation_app=simulation_app,
            )
        else:
            success = attach_worker_idle_pose(prim_path, interval=10, rotation_range=(-15.0, 15.0))

        if success:
            attached += 1
        else:
            failed += 1

    for worker_name in spawned_worker_names:
        has_behavior = any(wb.get("worker_id") == worker_name for wb in worker_behaviors)
        if not has_behavior:
            prim_path = f"/World/Characters/{worker_name}"
            prim = stage.GetPrimAtPath(prim_path)
            if prim and prim.IsValid():
                attach_worker_idle_pose(prim_path, interval=10, rotation_range=(-15.0, 15.0))
                attached += 1

    print(f"[INFO] Behavior attachment complete: {attached} attached, {failed} failed")
    return attached, failed