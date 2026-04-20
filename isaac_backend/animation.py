"""
Isaac Sim 5.1 IRA Animation Setup

Phase 1 (before timeline play):
  - Load Biped_Setup.usd (provides shared AnimationGraph + walk animations)
  - Attach ScriptingAPI + behavior script to all worker SkelRoots
  - Link each SkelRoot to the AnimationGraph via AnimationGraphAPI

Phase 2 (after timeline play + agent registration):
  - Inject commands via AgentManager.inject_command()

Reference: isaacsim.replicator.agent.core.stage_util.CharacterUtil
  - setup_python_scripts_to_character() — applies ScriptingAPI
  - setup_animation_graph_to_character() — applies AnimationGraphAPI + links graph
  - load_default_biped_to_stage() — loads Biped_Setup.usd invisibly
"""

import os
import random
import sys
import time
import math

import carb
import omni.kit.app
import omni.usd

AgentManager = None
BehaviorScriptPaths = None
PrimPaths = None
CharacterUtil = None
add_behavior_script = None
_HAS_IRA_CORE = False
_HAS_IRA_BEHAVIOR = False
_HAS_KIT_COMMANDS = False
Sdf = None


def _refresh_ira_state():
    global AgentManager, BehaviorScriptPaths, PrimPaths, CharacterUtil
    global add_behavior_script, _HAS_IRA_CORE, _HAS_IRA_BEHAVIOR, _HAS_KIT_COMMANDS, Sdf

    try:
        from isaacsim.replicator.agent.core.agent_manager import AgentManager as _AM
        from isaacsim.replicator.agent.core.settings import BehaviorScriptPaths as _BSP, PrimPaths as _PP
        from isaacsim.replicator.agent.core.stage_util import CharacterUtil as _CU
        AgentManager = _AM
        BehaviorScriptPaths = _BSP
        PrimPaths = _PP
        CharacterUtil = _CU
        _HAS_IRA_CORE = True
        print("[INFO] IRA core imports loaded successfully")
    except ImportError as e:
        print(f"[WARN] IRA core imports failed: {e}")
        _HAS_IRA_CORE = False

    try:
        from isaacsim.replicator.behavior.utils.behavior_utils import add_behavior_script as _abs
        add_behavior_script = _abs
        _HAS_IRA_BEHAVIOR = True
    except ImportError:
        _HAS_IRA_BEHAVIOR = False

    try:
        import omni.kit.commands
        _HAS_KIT_COMMANDS = True
    except ImportError:
        _HAS_KIT_COMMANDS = False

    try:
        from pxr import Sdf as _Sdf
        Sdf = _Sdf
    except ImportError:
        Sdf = None


def enable_behavior_extensions(simulation_app=None):
    """Enable extensions required for IRA behavior scripts and configure navmesh settings."""
    settings = carb.settings.get_settings()
    settings.set("/persistent/omni/anim/people/navmeshBasedNavigation", True)
    settings.set("/exts/omni.anim.people/navigation_settings/navmesh_enabled", True)
    settings.set("/exts/omni.anim.people/navigation_settings/dynamic_avoidance_enabled", True)
    settings.set("/persistent/exts/omni.anim.people/character_prim_path", "/World/Characters")
    print("[INFO] Navmesh enabled — GoTo uses navmesh pathfinding with dynamic avoidance")
    print("[INFO] CHARACTER_PRIM_PATH set to /World/Characters")

    manager = omni.kit.app.get_app().get_extension_manager()
    extensions = [
        "omni.kit.scripting",
        "isaacsim.replicator.behavior",
        "isaacsim.replicator.agent.core",
        "omni.anim.graph.core",
        "omni.anim.graph.schema",
        "omni.anim.people",
        "omni.anim.navigation.schema",
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

    _refresh_ira_state()


def bake_navmesh(simulation_app=None):
    """Bake navmesh after the warehouse layout is loaded so workers path around obstacles.

    Uses event-stream polling to wait for the bake to complete, rather than a
    fixed tick count. Falls back to extended tick polling if the event API
    is unavailable.
    """
    try:
        import omni.anim.navigation.core as nav_core
        interface = nav_core.acquire_interface()
        interface.start_navmesh_baking()
        print("[INFO] Navmesh baking started — waiting for completion...")

        baked = False
        try:
            event_stream = interface.get_navmesh_event_stream()
            nav_updated_event = nav_core.EVENT_TYPE_NAVMESH_UPDATED

            if simulation_app:
                for _ in range(300):
                    simulation_app.update()
                    pending = event_stream.pop()
                    while pending:
                        if pending.type == nav_updated_event:
                            baked = True
                            break
                        pending = event_stream.pop()
                    if baked:
                        break
        except Exception:
            pass

        if not baked and simulation_app:
            print("[INFO] Event stream unavailable — polling with extended ticks (200)")
            for _ in range(200):
                simulation_app.update()

        navmesh_obj = interface.get_navmesh()
        if navmesh_obj is not None:
            print("[INFO] Navmesh bake succeeded — navmesh object available")
        else:
            print("[WARN] Navmesh bake returned None — workers may use direct navigation")

        return True
    except Exception as e:
        print(f"[WARN] Navmesh baking failed (workers will use direct navigation): {e}")
        return False


def ensure_biped_setup(simulation_app=None):
    """Load Biped_Setup.usd invisibly to provide shared AnimationGraph + animations.

    Uses CharacterUtil.load_default_biped_to_stage() which creates
    /World/Characters/Biped_Setup with walk/sit/idle animations and an
    AnimationGraph prim. This is required before linking workers to the graph.

    Returns the Biped_Setup Xform prim, or None on failure.
    """
    if not _HAS_IRA_CORE:
        print("[WARN] IRA core unavailable — cannot load Biped_Setup")
        return None

    try:
        biped_prim = CharacterUtil.load_default_biped_to_stage()
        print(f"[INFO] Biped_Setup loaded at {biped_prim.GetPath()}")
    except Exception as e:
        print(f"[WARN] CharacterUtil.load_default_biped_to_stage() failed: {e}")
        try:
            from isaacsim.replicator.agent.core.settings import AssetPaths
            biped_path = AssetPaths.default_biped_asset_path()
            from pxr import Usd
            stage = omni.usd.get_context().get_stage()
            stage.DefinePrim("/World/Characters/Biped_Setup", "Xform")
            prim = stage.GetPrimAtPath("/World/Characters/Biped_Setup")
            prim.GetReferences().AddReference(biped_path)
            prim.GetAttribute("visibility").Set("invisible")
            print(f"[INFO] Biped_Setup loaded manually at /World/Characters/Biped_Setup")
            biped_prim = prim
        except Exception as e2:
            print(f"[ERROR] Failed to load Biped_Setup: {e2}")
            return None

    if simulation_app:
        for _ in range(30):
            simulation_app.update()

    return biped_prim


def _find_skelroot_for_worker(worker_name, stage):
    """Find the SkelRoot prim for a worker spawned under /World/Characters/{name}."""
    xform_path = f"/World/Characters/{worker_name}"
    xform_prim = stage.GetPrimAtPath(xform_path)
    if not xform_prim or not xform_prim.IsValid():
        return None
    from pxr import Usd
    for child in Usd.PrimRange(xform_prim):
        if child.GetTypeName() == "SkelRoot":
            return child
    return None


def _find_animation_graph(biped_prim, stage):
    """Find the AnimationGraph prim under the Biped_Setup hierarchy."""
    from pxr import Usd
    for prim in Usd.PrimRange(biped_prim):
        if prim.GetTypeName() == "AnimationGraph":
            return prim
    for prim in stage.Traverse():
        if prim.GetTypeName() == "AnimationGraph":
            return prim
    return None


def _attach_ira_builtin_behavior(skelroot_prim):
    """Attach IRA's built-in character_behavior.py to a character SkelRoot."""
    global _HAS_IRA_CORE, BehaviorScriptPaths, CharacterUtil

    if not _HAS_IRA_CORE:
        print("[WARN] IRA core unavailable, cannot attach built-in behavior")
        return False

    script_path = BehaviorScriptPaths.behavior_script_path()
    print(f"[INFO] Attaching IRA built-in behavior to {skelroot_prim.GetPath()}")

    try:
        CharacterUtil.setup_python_scripts_to_character([skelroot_prim], script_path)
        print(f"[INFO] IRA built-in behavior attached to {skelroot_prim.GetPath()}")
        return True
    except Exception as e:
        print(f"[ERROR] Failed to attach built-in behavior to {skelroot_prim.GetPath()}: {e}")
        return False


def _attach_builtin_fallback(skelroot_prim):
    """Fallback: directly set omni:scripting:scripts when IRA utils unavailable."""
    if not _HAS_KIT_COMMANDS or Sdf is None:
        print("[WARN] Cannot attach behavior script — kit commands unavailable")
        return False

    try:
        manager = omni.kit.app.get_app().get_extension_manager()
        people_path = manager.get_extension_path_by_module("omni.anim.people")
        script_path = f"{people_path}/omni/anim/people/scripts/character_behavior.py"
    except Exception:
        script_path = "/dev/null"

    prim_path = str(skelroot_prim.GetPath())
    try:
        omni.kit.commands.execute("ApplyScriptingAPICommand", paths=[Sdf.Path(prim_path)])
        attr = skelroot_prim.GetAttribute("omni:scripting:scripts")
        if attr:
            attr.Set([script_path])
        print(f"[INFO] Fallback behavior script attached to {prim_path}: {script_path}")
        return True
    except Exception as e:
        print(f"[ERROR] Fallback attachment failed for {prim_path}: {e}")
        return False


def link_workers_to_animation_graph(spawned_worker_names, stage, simulation_app=None):
    """Apply AnimationGraphAPI to each worker SkelRoot and link to AnimationGraph.

    Uses CharacterUtil.setup_animation_graph_to_character() which:
    1. Removes any existing AnimationGraphAPI
    2. Applies fresh AnimationGraphAPI to each SkelRoot
    3. Sets the animationGraph relationship to point at the shared AnimationGraph

    Returns (linked, failed) counts.
    """
    linked = 0
    failed = 0

    skelroots = []
    for name in sorted(spawned_worker_names):
        skelroot = _find_skelroot_for_worker(name, stage)
        if skelroot is None:
            print(f"[WARN] SkelRoot not found for {name}, skipping animation graph link")
            failed += 1
            continue
        skelroots.append(skelroot)

    if not skelroots:
        print("[WARN] No SkelRoots found to link to AnimationGraph")
        return 0, failed

    anim_graph_prim = None
    biped_prim = stage.GetPrimAtPath("/World/Characters/Biped_Setup")
    if biped_prim and biped_prim.IsValid():
        anim_graph_prim = _find_animation_graph(biped_prim, stage)

    if anim_graph_prim is None:
        for prim in stage.Traverse():
            if prim.GetTypeName() == "AnimationGraph":
                anim_graph_prim = prim
                break

    if anim_graph_prim is None:
        print("[ERROR] No AnimationGraph prim found on stage — cannot link workers")
        return 0, len(skelroots)

    print(f"[INFO] Found AnimationGraph at {anim_graph_prim.GetPath()}")

    if _HAS_IRA_CORE and CharacterUtil is not None:
        try:
            CharacterUtil.setup_animation_graph_to_character(skelroots, anim_graph_prim)
            linked = len(skelroots)
            print(f"[INFO] AnimationGraphAPI applied to {linked} SkelRoots via CharacterUtil")
        except Exception as e:
            print(f"[WARN] CharacterUtil.setup_animation_graph_to_character() failed: {e}")
            linked, failed = _link_animation_graph_fallback(skelroots, anim_graph_prim, stage)
    else:
        linked, failed = _link_animation_graph_fallback(skelroots, anim_graph_prim, stage)

    if simulation_app:
        for _ in range(10):
            simulation_app.update()

    return linked, failed


def _link_animation_graph_fallback(skelroots, anim_graph_prim, stage):
    """Fallback: apply AnimationGraphAPI manually using omni.kit.commands."""
    if not _HAS_KIT_COMMANDS or Sdf is None:
        print("[WARN] Cannot link animation graph — kit commands unavailable")
        return 0, len(skelroots)

    linked = 0
    failed = 0
    paths = [Sdf.Path(str(sr.GetPath())) for sr in skelroots]
    anim_graph_path = Sdf.Path(str(anim_graph_prim.GetPath()))

    try:
        omni.kit.commands.execute("RemoveAnimationGraphAPICommand", paths=paths)
        omni.kit.commands.execute(
            "ApplyAnimationGraphAPICommand", paths=paths, animation_graph_path=anim_graph_path
        )
        linked = len(skelroots)
        print(f"[INFO] AnimationGraphAPI applied to {linked} SkelRoots via kit commands")
    except Exception as e:
        print(f"[ERROR] kit command animation graph linking failed: {e}")
        failed = len(skelroots)

    return linked, failed


def setup_all_behaviors_async(spawned_worker_names, worker_behaviors, stage):
    """Attach IRA's built-in behavior script to all worker SkelRoots.

    Must be called BEFORE timeline.play(). The behavior script will
    automatically register the agent with AgentManager when play starts.

    Returns (attached, failed) counts.
    """
    attached = 0
    failed = 0

    print(f"[DEBUG][SetupBehaviors] _HAS_IRA_CORE={_HAS_IRA_CORE}")
    print(f"[DEBUG][SetupBehaviors] spawned_worker_names={spawned_worker_names}")

    all_workers = set(spawned_worker_names)
    # Warn about behaviors whose worker_id doesn't match any spawned name,
    # accepting both "worker_01" and bare "01" style IDs.
    for wb in worker_behaviors:
        worker_id = wb.get("worker_id", "")
        short_id = worker_id.removeprefix("worker_")
        canonical = f"worker_{short_id}" if short_id != worker_id else worker_id
        if worker_id not in all_workers and canonical not in all_workers:
            print(f"[INFO] No spawned worker matches behavior worker_id='{worker_id}' (tried '{canonical}')")

    for worker_name in sorted(all_workers):
        skelroot = _find_skelroot_for_worker(worker_name, stage)
        if skelroot is None:
            print(f"[WARN] SkelRoot not found for {worker_name}")
            failed += 1
            continue

        try:
            if _HAS_IRA_CORE:
                ok = _attach_ira_builtin_behavior(skelroot)
            else:
                ok = _attach_builtin_fallback(skelroot)
            if ok:
                attached += 1
            else:
                failed += 1
        except Exception as e:
            print(f"[ERROR] Failed to attach behavior to {worker_name}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print(f"[INFO] IRA behaviors: {attached} attached, {failed} failed")
    return attached, failed


def _build_command_list(worker_behaviors, worker_name, visible_bounds=None):
    """Build a command list for a single worker from behavior config.

    character_behavior.py requires the character name as the first word in each
    command string (see convert_str_to_command). Format:
        "worker_01 GoTo -4.0 -5.0 0.0 90.0"
        "worker_01 Idle 5.0"
        "worker_01 LookAround 3.0"

    If visible_bounds is provided, GoTo (x, y) targets are clamped to
    the camera-visible area (min_x, max_x, min_y, max_y).

    Matches worker_id with or without "worker_" prefix so configs work
    whether they use "worker_01" or bare "01" style IDs.
    """
    short_name = worker_name.removeprefix("worker_")
    for wb in worker_behaviors:
        wb_id = wb.get("worker_id", "")
        if wb_id == worker_name or wb_id == short_name:
            commands = wb.get("commands", [])
            if not commands:
                return [f"{worker_name} Idle 10"]
            result = []
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
                    result.append(f"{worker_name} GoTo {x} {y} {z} {rotation}")
                elif cmd_type == "Idle":
                    duration = cmd.get("duration", 5.0)
                    result.append(f"{worker_name} Idle {duration}")
                elif cmd_type == "LookAround":
                    duration = cmd.get("duration", 3.0)
                    result.append(f"{worker_name} LookAround {duration}")
            return result if result else [f"{worker_name} Idle 10"]
    return [f"{worker_name} Idle 10"]


def inject_commands_after_play(spawned_worker_names, worker_behaviors, simulation_app=None, visible_bounds=None):
    """Inject commands to all registered agents via AgentManager.

    Must be called AFTER timeline.play() and after waiting for agent registration.
    Uses AgentManager.inject_command() which properly sets animation graph
    variables through the registered behavior script instances.

    visible_bounds: (min_x, max_x, min_y, max_y) constraining GoTo targets
                    to the camera-visible area.

    Returns (injected, failed) counts.
    """
    global AgentManager

    if not _HAS_IRA_CORE or AgentManager is None:
        print("[WARN] AgentManager unavailable — cannot inject commands")
        return 0, len(spawned_worker_names)

    if simulation_app:
        for _ in range(10):
            simulation_app.update()

    if not AgentManager.has_instance():
        print("[WARN] AgentManager has no instance — no agents registered yet")
        return 0, len(spawned_worker_names)

    agent_manager = AgentManager.get_instance()

    if simulation_app:
        for _ in range(50):
            simulation_app.update()
            registered = agent_manager.get_all_agent_names()
            if spawned_worker_names.issubset(set(registered)):
                break
    registered = agent_manager.get_all_agent_names()
    print(f"[INFO] AgentManager registered agents: {list(registered)}")

    injected = 0
    failed = 0

    for worker_name in sorted(spawned_worker_names):
        if not agent_manager.agent_registered(worker_name):
            print(f"[WARN] Agent '{worker_name}' not registered — skipping command injection")
            failed += 1
            continue

        command_list = _build_command_list(worker_behaviors, worker_name, visible_bounds=visible_bounds)
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


WAREHOUSE_X_RANGE = (-5.5, 5.5)
WAREHOUSE_Y_RANGE = (-5.5, 5.5)


def reinject_random_commands(spawned_worker_names, visible_bounds=None):
    """Re-inject randomized commands to all registered agents.

    Prevents IRA behavior loop from repeating the same command sequence.
    Generates varied GoTo targets within visible_bounds (or warehouse bounds
    as fallback), plus Idle and LookAround with random durations.

    visible_bounds: (min_x, max_x, min_y, max_y) constraining GoTo targets.
                    If None, falls back to WAREHOUSE_X/Y_RANGE.

    Returns (injected, failed) counts.
    """
    global AgentManager

    if not _HAS_IRA_CORE or AgentManager is None:
        return 0, 0

    if not AgentManager.has_instance():
        return 0, 0

    agent_manager = AgentManager.get_instance()
    injected = 0
    failed = 0

    if visible_bounds is not None:
        x_lo, x_hi = visible_bounds[0], visible_bounds[1]
        y_lo, y_hi = visible_bounds[2], visible_bounds[3]
    else:
        x_lo, x_hi = WAREHOUSE_X_RANGE
        y_lo, y_hi = WAREHOUSE_Y_RANGE

    for worker_name in sorted(spawned_worker_names):
        if not agent_manager.agent_registered(worker_name):
            failed += 1
            continue

        num_waypoints = random.randint(2, 3)
        cmd_list = []
        for i in range(num_waypoints):
            wx = round(random.uniform(x_lo, x_hi), 1)
            wy = round(random.uniform(y_lo, y_hi), 1)
            cmd_list.append(f"GoTo {wx} {wy} 0.0 0")
            if i < num_waypoints - 1:
                if random.random() < 0.5:
                    cmd_list.append(f"Idle {round(random.uniform(1, 4), 1)}")
                else:
                    cmd_list.append(f"LookAround {round(random.uniform(1, 3), 1)}")
        cmd_list.append(f"Idle {round(random.uniform(3, 8), 1)}")

        try:
            agent_manager.inject_command(
                agent_name=worker_name,
                command_list=cmd_list,
                force_inject=True,
                instant=True,
            )
            injected += 1
        except Exception as e:
            print(f"[WARN] Re-injection failed for {worker_name}: {e}")
            failed += 1

    if injected > 0:
        _progress(f"Re-injected commands for {injected} workers (step midpoint)")
    return injected, failed


def _progress(msg):
    print(f"[PROGRESS] [{time.strftime('%H:%M:%S')}] {msg}")
    sys.stdout.flush()
class VehicleAnimator:
    """Animates non-biped vehicles like forklifts over the simulation frames."""
    def __init__(self, vehicle_behaviors, stage, fps=30):
        self.stage = stage
        self.fps = fps
        self.vehicles = []

        for vb in vehicle_behaviors:
            v_id = vb.get("vehicle_id")
            commands = vb.get("commands", [])
            prim_path = f"/World/Entities/{v_id}"
            prim = self.stage.GetPrimAtPath(prim_path)
            if not prim or not prim.IsValid():
                print(f"[WARN] VehicleAnimator: Prim not found for {v_id} at {prim_path}")
                continue

            # Extract waypoints
            waypoints = []
            for cmd in commands:
                if cmd.get("command") == "GoTo":
                    waypoints.append({
                        "x": cmd.get("x", 0.0),
                        "y": cmd.get("y", 0.0),
                        "z": cmd.get("z", 0.0),
                        "rot": cmd.get("rotation")
                    })
                elif cmd.get("command") == "Idle":
                    # Just add a delay by duplicating last waypoint
                    if waypoints:
                        waypoints.append(waypoints[-1].copy())

            if len(waypoints) < 2:
                print(f"[WARN] VehicleAnimator: Not enough waypoints for {v_id}")
                continue

            waypoints = self._expand_via_navmesh(waypoints, v_id)

            # Cache XformOp references once at init — looking them up every frame
            # via GetOrderedXformOps() can return stale or reordered results when
            # Replicator flushes its USD layer at the camera trigger interval.
            from pxr import UsdGeom, Gf
            xformable = UsdGeom.Xformable(prim)
            translate_op = None
            rotate_op = None
            for op in xformable.GetOrderedXformOps():
                if op.GetOpType() == UsdGeom.XformOp.TypeTranslate:
                    translate_op = op
                elif op.GetOpType() in (UsdGeom.XformOp.TypeRotateXYZ, UsdGeom.XformOp.TypeOrient):
                    rotate_op = op
            if translate_op is None:
                translate_op = xformable.AddTranslateOp()
            if rotate_op is None:
                rotate_op = xformable.AddRotateXYZOp()

            self.vehicles.append({
                "id": v_id,
                "prim": prim,
                "waypoints": waypoints,
                "current_wp": 0,
                "translate_op": translate_op,
                "rotate_op": rotate_op,
            })
            print(f"[INFO] VehicleAnimator tracking {v_id} with {len(waypoints)} waypoints")

    def _expand_via_navmesh(self, waypoints, v_id):
        """Replace straight-line segments with navmesh-queried paths."""
        try:
            import omni.anim.navigation.core as nav_core
            import carb
            interface = nav_core.acquire_interface()
            navmesh = interface.get_navmesh()
            if navmesh is None:
                print(f"[WARN] VehicleAnimator: navmesh not available for {v_id}, using straight-line paths")
                return waypoints
        except Exception as e:
            print(f"[WARN] VehicleAnimator: could not acquire navmesh for {v_id}: {e}")
            return waypoints

        expanded = [waypoints[0]]
        for i in range(len(waypoints) - 1):
            p1, p2 = waypoints[i], waypoints[i + 1]
            dx, dy = p2["x"] - p1["x"], p2["y"] - p1["y"]
            if dx*dx + dy*dy < 0.01:
                expanded.append(p2)
                continue
            try:
                start = carb.Float3(p1["x"], p1["y"], 0.0)
                end = carb.Float3(p2["x"], p2["y"], 0.0)
                path = navmesh.query_path(start, end)
                if path and len(path) > 2:
                    for pt in path[1:-1]:
                        expanded.append({"x": pt.x, "y": pt.y, "z": p2["z"], "rot": None})
                    print(f"[INFO] VehicleAnimator: navmesh added {len(path)-2} intermediate points for {v_id}")
            except Exception as e:
                print(f"[WARN] VehicleAnimator: navmesh query failed for {v_id}: {e}")
            expanded.append(p2)
        return expanded

    def update(self, current_frame, total_frames):
        if not self.vehicles:
            return

        from pxr import Gf

        for v in self.vehicles:
            wps = v["waypoints"]
            if not wps:
                continue

            # Simple interpolation across total frames
            progress = current_frame / max(1, total_frames - 1)
            total_segments = len(wps) - 1
            segment_float = progress * total_segments
            segment_idx = min(int(segment_float), total_segments - 1)
            t = segment_float - segment_idx

            p1 = wps[segment_idx]
            p2 = wps[segment_idx + 1]

            cur_x = p1["x"] + (p2["x"] - p1["x"]) * t
            cur_y = p1["y"] + (p2["y"] - p1["y"]) * t
            cur_z = p1["z"] + (p2["z"] - p1["z"]) * t

            # Use cached op references — never re-query GetOrderedXformOps() here,
            # because Replicator's layer flush at camera-trigger intervals can
            # transiently reorder or hide ops, causing AddTranslateOp() to create
            # a second op that composes with the first and breaks the trajectory.
            translate_op = v["translate_op"]
            rotate_op = v["rotate_op"]

            dx = p2["x"] - p1["x"]
            dy = p2["y"] - p1["y"]
            dist_sq = dx*dx + dy*dy

            if dist_sq > 0.001:
                # Asset faces +Y at 0°; subtract 90° to align with travel direction.
                travel_rot = math.degrees(math.atan2(dy, dx)) - 90.0
                dest_rot = p2.get("rot")
                if dest_rot is not None and t >= 0.7:
                    # Blend into docking orientation in the final 30% of the segment.
                    blend_t = (t - 0.7) / 0.3
                    diff = ((dest_rot - travel_rot + 180) % 360) - 180
                    rot_deg = travel_rot + diff * blend_t
                else:
                    rot_deg = travel_rot
            else:
                # Stationary (Idle): hold the waypoint's explicit rotation.
                rot_deg = p2.get("rot") if p2.get("rot") is not None else (p1.get("rot") if p1.get("rot") is not None else 0.0)

            translate_op.Set(Gf.Vec3d(cur_x, cur_y, cur_z))

            from pxr import UsdGeom
            if rotate_op.GetOpType() == UsdGeom.XformOp.TypeRotateXYZ:
                rotate_op.Set(Gf.Vec3d(0, 0, rot_deg))

