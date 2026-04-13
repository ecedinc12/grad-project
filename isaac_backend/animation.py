"""
Isaac Sim 5.1 IRA Behavior Script Manager

Enables isaacsim.replicator.behavior extension and attaches behavior scripts
(patrol/idle) to worker prims. Falls back to direct USD attribute manipulation
when the IRA extension is unavailable.
"""

import asyncio
import inspect
import time

import omni.kit.app
import omni.usd

from isaac_backend.behaviors.worker_patrol import WorkerPatrolBehavior
from isaac_backend.behaviors.worker_idle_pose import WorkerIdlePoseBehavior

try:
    from isaacsim.replicator.behavior.utils.behavior_utils import (
        add_behavior_script_with_parameters_async,
    )
    _HAS_IRA = True
except ImportError:
    _HAS_IRA = False

try:
    from isaacsim.replicator.behavior.global_variables import EXPOSED_ATTR_NS
except ImportError:
    EXPOSED_ATTR_NS = "exposedVar"

try:
    from pxr import Sdf
except ImportError:
    Sdf = None

try:
    import omni.kit.commands
    _HAS_KIT_COMMANDS = True
except ImportError:
    _HAS_KIT_COMMANDS = False


def enable_behavior_extensions(simulation_app=None):
    """Enable extensions required for IRA behavior scripts."""
    manager = omni.kit.app.get_app().get_extension_manager()
    extensions = [
        "omni.kit.scripting",
        "isaacsim.replicator.behavior",
        "omni.anim.graph.core",
    ]
    for ext in extensions:
        try:
            if not manager.is_extension_enabled(ext):
                print(f"[INFO] Enabling extension: {ext}")
                manager.set_extension_enabled_immediate(ext, True)
            else:
                print(f"[INFO] Extension already active: {ext}")
        except Exception as e:
            print(f"[WARN] Could not enable extension {ext}: {e}")
    if simulation_app:
        for _ in range(30):
            simulation_app.update()


def _extract_waypoints(worker_behavior):
    """Extract GoTo waypoints from a worker behavior config."""
    waypoints = []
    for cmd in worker_behavior.get("commands", []):
        if cmd.get("command") == "GoTo":
            wp = (cmd.get("x", 0.0), cmd.get("y", 0.0), cmd.get("z", 0.0), cmd.get("rotation", 0.0))
            waypoints.append(wp)
    return waypoints


async def _attach_patrol_async(prim, waypoints, speed=1.0, idle_duration=3.0, look_around_duration=2.0):
    """Attach WorkerPatrolBehavior via IRA add_behavior_script_with_parameters_async."""
    script_path = inspect.getfile(WorkerPatrolBehavior)
    waypoints_csv = ";".join(f"{x},{y},{z},{r}" for x, y, z, r in waypoints)

    _set_exposed_attr(prim, "workerPatrol", "waypoints:csv", waypoints_csv, Sdf.ValueTypeNames.String)
    _set_exposed_attr(prim, "workerPatrol", "speed", speed, Sdf.ValueTypeNames.Float)
    _set_exposed_attr(prim, "workerPatrol", "idleDuration", idle_duration, Sdf.ValueTypeNames.Float)
    _set_exposed_attr(prim, "workerPatrol", "lookAroundDuration", look_around_duration, Sdf.ValueTypeNames.Float)

    parameters = {
        f"{EXPOSED_ATTR_NS}:workerPatrol:waypoints:csv": waypoints_csv,
        f"{EXPOSED_ATTR_NS}:workerPatrol:speed": speed,
        f"{EXPOSED_ATTR_NS}:workerPatrol:idleDuration": idle_duration,
        f"{EXPOSED_ATTR_NS}:workerPatrol:lookAroundDuration": look_around_duration,
    }
    await add_behavior_script_with_parameters_async(prim, script_path, parameters)
    print(f"[INFO] WorkerPatrol attached to {prim.GetPath()} with {len(waypoints)} waypoints")


async def _attach_idle_pose_async(prim, interval=10, rotation_range=(-15.0, 15.0)):
    """Attach WorkerIdlePoseBehavior via IRA add_behavior_script_with_parameters_async."""
    script_path = inspect.getfile(WorkerIdlePoseBehavior)

    _set_exposed_attr(prim, "workerIdlePose", "interval", interval, Sdf.ValueTypeNames.UInt)
    _set_exposed_attr(prim, "workerIdlePose", "rotationRange:csv", f"{rotation_range[0]},{rotation_range[1]}", Sdf.ValueTypeNames.String)

    parameters = {
        f"{EXPOSED_ATTR_NS}:workerIdlePose:interval": interval,
        f"{EXPOSED_ATTR_NS}:workerIdlePose:rotationRange:csv": f"{rotation_range[0]},{rotation_range[1]}",
    }
    await add_behavior_script_with_parameters_async(prim, script_path, parameters)
    print(f"[INFO] WorkerIdlePose attached to {prim.GetPath()} (interval={interval}, range={rotation_range})")


def _set_exposed_attr(prim, namespace, attr_name, value, attr_type):
    """Set or create an exposed behavior attribute on a prim."""
    full_name = f"{EXPOSED_ATTR_NS}:{namespace}:{attr_name}"
    attr = prim.GetAttribute(full_name)
    if attr and attr.IsValid():
        attr.Set(value)
    else:
        prim.CreateAttribute(full_name, attr_type, True).Set(value)


def _apply_scripting_api_fallback(prim_path):
    """Apply ScriptingAPI to a prim via kit commands (fallback when IRA unavailable)."""
    if not _HAS_KIT_COMMANDS or Sdf is None:
        print(f"[WARN] Cannot apply ScriptingAPI to {prim_path} — kit commands unavailable")
        return False
    try:
        omni.kit.commands.execute(
            "ApplyScriptingAPICommand",
            paths=[Sdf.Path(prim_path)],
        )
        return True
    except Exception as e:
        print(f"[WARN] ApplyScriptingAPICommand failed for {prim_path}: {e}")
        return False


def _attach_behavior_script_fallback(prim, script_path):
    """Attach a behavior script via direct USD omni:scripting:scripts attribute."""
    if not prim or not prim.IsValid():
        return False
    attr = prim.GetAttribute("omni:scripting:scripts")
    if not attr or not attr.IsValid():
        attr = prim.CreateAttribute("omni:scripting:scripts", Sdf.ValueTypeNames.StringArray, True)
    attr.Set([script_path])
    print(f"[INFO] Attached behavior script (fallback) to {prim.GetPath()}: {script_path}")
    return True


async def _attach_patrol_fallback_async(prim, waypoints, speed=1.0, idle_duration=3.0, look_around_duration=2.0):
    """Attach WorkerPatrolBehavior via fallback (direct USD attributes)."""
    prim_path = str(prim.GetPath())
    _apply_scripting_api_fallback(prim_path)
    script_path = inspect.getfile(WorkerPatrolBehavior)
    _attach_behavior_script_fallback(prim, script_path)
    waypoints_csv = ";".join(f"{x},{y},{z},{r}" for x, y, z, r in waypoints)
    _set_exposed_attr(prim, "workerPatrol", "waypoints:csv", waypoints_csv, Sdf.ValueTypeNames.String)
    _set_exposed_attr(prim, "workerPatrol", "speed", speed, Sdf.ValueTypeNames.Float)
    _set_exposed_attr(prim, "workerPatrol", "idleDuration", idle_duration, Sdf.ValueTypeNames.Float)
    _set_exposed_attr(prim, "workerPatrol", "lookAroundDuration", look_around_duration, Sdf.ValueTypeNames.Float)
    print(f"[INFO] WorkerPatrol attached (fallback) to {prim_path} with {len(waypoints)} waypoints")


async def _attach_idle_pose_fallback_async(prim, interval=10, rotation_range=(-15.0, 15.0)):
    """Attach WorkerIdlePoseBehavior via fallback (direct USD attributes)."""
    prim_path = str(prim.GetPath())
    _apply_scripting_api_fallback(prim_path)
    script_path = inspect.getfile(WorkerIdlePoseBehavior)
    _attach_behavior_script_fallback(prim, script_path)
    _set_exposed_attr(prim, "workerIdlePose", "interval", interval, Sdf.ValueTypeNames.UInt)
    range_csv = f"{rotation_range[0]},{rotation_range[1]}"
    _set_exposed_attr(prim, "workerIdlePose", "rotationRange:csv", range_csv, Sdf.ValueTypeNames.String)
    print(f"[INFO] WorkerIdlePose attached (fallback) to {prim_path} (interval={interval}, range={rotation_range})")


def _wait_for_async(coro, simulation_app):
    """Schedule coroutine on the existing Omniverse asyncio loop and poll while pumping.

    IRA's add_behavior_script_with_parameters_async sends commands to
    omni.kit.scripting which processes them on the Omniverse main event loop.
    Using run_until_complete() creates a nested task context that blocks all
    other Omniverse tasks (ScriptManager, PrimCaching, etc.), causing re-entry
    errors. Instead, we schedule the coroutine cooperatively on the existing
    loop and pump the app until it completes.
    """
    loop = asyncio.get_event_loop()
    task = asyncio.ensure_future(coro, loop=loop)

    while not task.done():
        simulation_app.update()
        time.sleep(0.01)

    return task.result()


async def setup_all_behaviors_async(spawned_worker_names, worker_behaviors, stage):
    """Orchestrate behavior attachment for all spawned workers.

    Workers with GoTo commands get WorkerPatrolBehavior.
    Workers without commands get WorkerIdlePoseBehavior.
    Uses IRA when available, falls back to direct USD attributes otherwise.
    """
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

        try:
            if _HAS_IRA:
                if waypoints:
                    await _attach_patrol_async(prim, waypoints)
                else:
                    await _attach_idle_pose_async(prim)
            else:
                if waypoints:
                    await _attach_patrol_fallback_async(prim, waypoints)
                else:
                    await _attach_idle_pose_fallback_async(prim)
            attached += 1
        except Exception as e:
            print(f"[ERROR] Failed to attach behavior to {worker_id}: {e}")
            failed += 1

    for worker_name in spawned_worker_names:
        has_behavior = any(wb.get("worker_id") == worker_name for wb in worker_behaviors)
        if not has_behavior:
            prim_path = f"/World/Characters/{worker_name}"
            prim = stage.GetPrimAtPath(prim_path)
            if prim and prim.IsValid():
                try:
                    if _HAS_IRA:
                        await _attach_idle_pose_async(prim)
                    else:
                        await _attach_idle_pose_fallback_async(prim)
                    attached += 1
                except Exception as e:
                    print(f"[ERROR] Failed to attach idle behavior to {worker_name}: {e}")
                    failed += 1

    print(f"[INFO] IRA behaviors: {attached} attached, {failed} failed")
    return attached, failed
