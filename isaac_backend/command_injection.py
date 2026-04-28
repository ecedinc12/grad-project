"""
IRA Command Injection

Building command lists from behavior config and injecting them via AgentManager
after timeline play. Also handles periodic re-injection of randomized commands.
"""

import sys
import time
import random

import isaac_backend.ira_setup as _ira
from isaac_backend.navmesh_utils import get_navmesh, get_worker_pos, snap_target

WAREHOUSE_X_RANGE = (-5.5, 5.5)
WAREHOUSE_Y_RANGE = (-5.5, 5.5)


def _progress(msg):
    print(f"[PROGRESS] [{time.strftime('%H:%M:%S')}] {msg}")
    sys.stdout.flush()


def _build_command_list(worker_behaviors, worker_name, visible_bounds=None,
                        navmesh=None, origin_xy=None):
    """Build a command list for a single worker from behavior config.

    character_behavior.py requires the character name as the first word in each
    command string. Format:
        "worker_01 GoTo -4.0 -5.0 0.0 90.0"
        "worker_01 Idle 5.0"
        "worker_01 LookAround 3.0"

    Matches worker_id with or without "worker_" prefix. If visible_bounds is
    provided, GoTo (x, y) targets are clamped to (min_x, max_x, min_y, max_y).
    When navmesh is provided, each GoTo target is also snapped to the nearest
    reachable point so NavigationManager.generate_path won't fail with
    "no valid path between point position".
    """
    short_name = worker_name.removeprefix("worker_")
    for wb in worker_behaviors:
        wb_id = wb.get("worker_id", "")
        if wb_id == worker_name or wb_id == short_name:
            commands = wb.get("commands", [])
            if not commands:
                return [f"{worker_name} Idle 10"]
            result = []
            prev_xy = origin_xy
            for cmd in commands:
                cmd_type = cmd.get("command", "")
                if cmd_type == "GoTo":
                    x = cmd.get("x", 0.0)
                    y = cmd.get("y", 0.0)
                    z = cmd.get("z", 0.0)
                    rotation = cmd.get("rotation", 0)
                    if rotation == "_" or rotation is None:
                        rotation = 0
                    if visible_bounds is not None:
                        x = max(visible_bounds[0], min(visible_bounds[1], x))
                        y = max(visible_bounds[2], min(visible_bounds[3], y))
                    if navmesh is not None and prev_xy is not None:
                        snapped = snap_target(prev_xy, (x, y), navmesh=navmesh)
                        if snapped != (x, y):
                            print(f"[INFO] {worker_name} GoTo snapped "
                                  f"({x:.2f},{y:.2f}) -> ({snapped[0]:.2f},{snapped[1]:.2f})")
                        x, y = snapped
                    prev_xy = (x, y)
                    result.append(f"{worker_name} GoTo {x} {y} {z} {rotation}")
                elif cmd_type == "Idle":
                    result.append(f"{worker_name} Idle {cmd.get('duration', 5.0)}")
                elif cmd_type == "LookAround":
                    result.append(f"{worker_name} LookAround {cmd.get('duration', 3.0)}")
            return result if result else [f"{worker_name} Idle 10"]
    return [f"{worker_name} Idle 10"]


def inject_commands_after_play(spawned_worker_names, worker_behaviors, simulation_app=None,
                                visible_bounds=None, stage=None):
    """Inject commands to all registered agents via AgentManager.

    Must be called AFTER timeline.play() and after waiting for agent registration.
    Uses AgentManager.inject_command() which properly sets animation graph
    variables through the registered behavior script instances.

    visible_bounds: (min_x, max_x, min_y, max_y) constraining GoTo targets.
    stage: USD stage; when provided alongside an active navmesh, each GoTo
        target is snapped to the nearest reachable point so NavigationManager
        path queries can't fail.

    Returns (injected, failed) counts.
    """
    if not _ira._HAS_IRA_CORE or _ira.AgentManager is None:
        print("[WARN] AgentManager unavailable — cannot inject commands")
        return 0, len(spawned_worker_names)

    if simulation_app:
        for _ in range(10):
            simulation_app.update()

    if not _ira.AgentManager.has_instance():
        print("[WARN] AgentManager has no instance — no agents registered yet")
        return 0, len(spawned_worker_names)

    agent_manager = _ira.AgentManager.get_instance()

    if simulation_app:
        for _ in range(50):
            simulation_app.update()
            if spawned_worker_names.issubset(set(agent_manager.get_all_agent_names())):
                break

    print(f"[INFO] AgentManager registered agents: {list(agent_manager.get_all_agent_names())}")

    navmesh = get_navmesh() if stage is not None else None
    if stage is not None and navmesh is None:
        print("[INFO] inject_commands_after_play: no navmesh — skipping target snapping")

    injected = 0
    failed = 0

    for worker_name in sorted(spawned_worker_names):
        if not agent_manager.agent_registered(worker_name):
            print(f"[WARN] Agent '{worker_name}' not registered — skipping command injection")
            failed += 1
            continue

        origin_xy = get_worker_pos(stage, worker_name) if stage is not None else None
        command_list = _build_command_list(
            worker_behaviors, worker_name, visible_bounds=visible_bounds,
            navmesh=navmesh, origin_xy=origin_xy,
        )
        print(f"[INFO] Injecting commands for {worker_name}: {command_list}")

        try:
            agent_manager.inject_command(
                agent_name=worker_name,
                command_list=command_list,
                force_inject=True,
                instant=True,
            )
            injected += 1
        except Exception as e:
            print(f"[ERROR] Failed to inject commands for {worker_name}: {e}")
            failed += 1

    print(f"[INFO] Command injection: {injected} succeeded, {failed} failed")
    return injected, failed


def reinject_random_commands(spawned_worker_names, visible_bounds=None,
                              worker_zone_bounds=None, stage=None):
    """Re-inject randomized commands to all registered agents.

    Prevents IRA behavior loop from repeating the same command sequence.
    Generates varied GoTo targets within each worker's assigned zone bounds
    (from worker_zone_bounds), falling back to visible_bounds or warehouse
    bounds when no zone is assigned.

    worker_zone_bounds: dict mapping worker_name → (x_lo, x_hi, y_lo, y_hi).
    visible_bounds: (min_x, max_x, min_y, max_y) fallback when no zone bounds.
    stage: USD stage; when provided alongside an active navmesh, each random
        GoTo target is snapped to the nearest reachable point.

    Returns (injected, failed) counts.
    """
    if not _ira._HAS_IRA_CORE or _ira.AgentManager is None:
        return 0, 0
    if not _ira.AgentManager.has_instance():
        return 0, 0

    agent_manager = _ira.AgentManager.get_instance()
    injected = 0
    failed = 0

    default_x_lo, default_x_hi = (visible_bounds[0], visible_bounds[1]) if visible_bounds else WAREHOUSE_X_RANGE
    default_y_lo, default_y_hi = (visible_bounds[2], visible_bounds[3]) if visible_bounds else WAREHOUSE_Y_RANGE

    navmesh = get_navmesh() if stage is not None else None

    for worker_name in sorted(spawned_worker_names):
        if not agent_manager.agent_registered(worker_name):
            failed += 1
            continue

        if worker_zone_bounds and worker_name in worker_zone_bounds:
            x_lo, x_hi, y_lo, y_hi = worker_zone_bounds[worker_name]
        else:
            x_lo, x_hi, y_lo, y_hi = default_x_lo, default_x_hi, default_y_lo, default_y_hi

        prev_xy = get_worker_pos(stage, worker_name) if (stage is not None and navmesh is not None) else None

        num_waypoints = random.randint(2, 3)
        cmd_list = []
        for i in range(num_waypoints):
            wx = round(random.uniform(x_lo, x_hi), 1)
            wy = round(random.uniform(y_lo, y_hi), 1)
            if navmesh is not None and prev_xy is not None:
                snapped = snap_target(prev_xy, (wx, wy), navmesh=navmesh)
                wx, wy = round(snapped[0], 2), round(snapped[1], 2)
                prev_xy = (wx, wy)
            cmd_list.append(f"{worker_name} GoTo {wx} {wy} 0.0 0")
            if i < num_waypoints - 1:
                if random.random() < 0.5:
                    cmd_list.append(f"{worker_name} Idle {round(random.uniform(1, 4), 1)}")
                else:
                    cmd_list.append(f"{worker_name} LookAround {round(random.uniform(1, 3), 1)}")
        cmd_list.append(f"{worker_name} Idle {round(random.uniform(3, 8), 1)}")

        try:
            # instant=False so anim.people lets the agent finish its current
            # command before swapping the queue. instant=True aborts mid-
            # pathfind and segfaults inside NavigationManager when the new
            # waypoints can't be routed (libpython3.11/cfunction_call crash).
            agent_manager.inject_command(
                agent_name=worker_name,
                command_list=cmd_list,
                force_inject=True,
                instant=False,
            )
            injected += 1
        except Exception as e:
            print(f"[WARN] Re-injection failed for {worker_name}: {e}")
            failed += 1

    if injected > 0:
        _progress(f"Re-injected commands for {injected} workers (step midpoint)")
    return injected, failed
