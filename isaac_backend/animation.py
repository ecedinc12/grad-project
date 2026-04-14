"""
Isaac Sim 5.1 IRA Behavior Script Manager — Built-in Behavior + Command Injection

Phase 1: Attach IRA's built-in character_behavior.py to worker SkelRoots (before timeline play).
Phase 2: Inject GoTo/Idle/LookAround commands via AgentManager (after timeline play + agent registration).

Falls back to direct USD scripting attribute manipulation when IRA extensions are unavailable.
"""

import asyncio
import time

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
    """Re-evaluate IRA imports after extensions are enabled at runtime."""
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
    """Enable extensions required for IRA behavior scripts."""
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


def _attach_ira_builtin_behavior(skelroot_prim):
    """Attach IRA's built-in character_behavior.py to a character SkelRoot.

    Uses CharacterUtil.setup_python_scripts_to_character() which applies
    ScriptingAPI and sets omni:scripting:scripts to the built-in script path.
    """
    global _HAS_IRA_CORE, BehaviorScriptPaths, CharacterUtil

    if not _HAS_IRA_CORE:
        print("[WARN] IRA core unavailable, cannot attach built-in behavior")
        return False

    script_path = BehaviorScriptPaths.behavior_script_path()
    print(f"[INFO] Attaching IRA built-in behavior to {skelroot_prim.GetPath()}")
    print(f"[INFO] Behavior script path: {script_path}")

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
        print(f"[WARN] Cannot attach behavior script — kit commands unavailable")
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


def _build_command_string(worker_id, commands):
    """Convert WorkerBehavior commands list to IRA command strings.

    Input: [{"command": "GoTo", "x": 10, "y": 10, "z": 0, "rotation": 90},
            {"command": "Idle", "duration": 5},
            {"command": "LookAround", "duration": 3}]

    Output: ["worker_01 GoTo 10 10 0 90", "worker_01 Idle 5", "worker_01 LookAround 3"]
    """
    result = []
    for cmd in commands:
        cmd_type = cmd.get("command", "")
        if cmd_type == "GoTo":
            x = cmd.get("x", 0.0)
            y = cmd.get("y", 0.0)
            z = cmd.get("z", 0.0)
            rot = cmd.get("rotation", 0.0)
            result.append(f"{worker_id} GoTo {x} {y} {z} {rot}")
        elif cmd_type == "Idle":
            duration = cmd.get("duration", 5.0)
            result.append(f"{worker_id} Idle {duration}")
        elif cmd_type == "LookAround":
            duration = cmd.get("duration", 3.0)
            result.append(f"{worker_id} LookAround {duration}")
    return result


def setup_all_behaviors_async(spawned_worker_names, worker_behaviors, stage):
    """Phase 1: Attach IRA's built-in behavior script to all worker SkelRoots.

    This must be called BEFORE timeline.play(). The behavior script will
    automatically register the agent with AgentManager when play starts.

    Returns (attached, failed) counts.
    """
    attached = 0
    failed = 0

    print(f"[DEBUG][SetupBehaviors] _HAS_IRA_CORE={_HAS_IRA_CORE}")
    print(f"[DEBUG][SetupBehaviors] spawned_worker_names={spawned_worker_names}")
    print(f"[DEBUG][SetupBehaviors] worker_behaviors={worker_behaviors}")

    for wb in worker_behaviors:
        worker_id = wb.get("worker_id", "worker_01")
        if worker_id not in spawned_worker_names:
            print(f"[INFO] Skipping behavior for non-spawned worker: {worker_id}")
            continue

        skelroot = _find_skelroot_for_worker(worker_id, stage)
        if skelroot is None:
            print(f"[WARN] SkelRoot not found for {worker_id}")
            failed += 1
            continue

        try:
            if _HAS_IRA_CORE:
                ok = _attach_ira_builtin_behavior(skelroot)
            else:
                print(f"[INFO] IRA core unavailable, using fallback for {worker_id}")
                ok = _attach_builtin_fallback(skelroot)
            if ok:
                attached += 1
            else:
                failed += 1
        except Exception as e:
            print(f"[ERROR] Failed to attach behavior to {worker_id}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    for worker_name in spawned_worker_names:
        has_behavior = any(wb.get("worker_id") == worker_name for wb in worker_behaviors)
        if not has_behavior:
            skelroot = _find_skelroot_for_worker(worker_name, stage)
            if skelroot:
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


def _build_skelroot_name_map(stage, spawned_worker_names):
    """Build a mapping from worker Xform name (worker_01) to SkelRoot name.

    CharacterUtil.get_characters_in_stage() returns SkelRoot prims whose
    names come from the referenced USD (e.g. male_adult_construction_01),
    not the Xform wrapper name (worker_01). IRA registers agents using
    the SkelRoot name, so we need this mapping for command injection.
    """
    name_map = {}
    try:
        chars = CharacterUtil.get_characters_in_stage()
        for char_prim in chars:
            skel_name = char_prim.GetName()
            skel_path = str(char_prim.GetPath())
            for worker_name in spawned_worker_names:
                if worker_name in skel_path:
                    name_map[worker_name] = skel_name
                    print(f"[INFO] Name mapping: {worker_name} -> {skel_name}")
                    break
    except Exception as e:
        print(f"[WARN] Failed to build Skelroot name map: {e}")
    return name_map


def _wait_for_agent_registration(simulation_app, max_updates=60):
    """Wait for all spawned agents to register with AgentManager.

    Agents register after timeline.play() fires the behavior script's on_play().
    Minimum 2 update cycles required. Returns list of registered agent names.
    """
    if not _HAS_IRA_CORE or not AgentManager.has_instance():
        print("[WARN] AgentManager not available, skipping registration wait")
        return []

    agent_manager = AgentManager.get_instance()
    registered = []

    for i in range(max_updates):
        simulation_app.update()
        registered = list(agent_manager.get_all_agent_names())
        if len(registered) > 0:
            print(f"[INFO] Agents registered after {i + 1} updates: {registered}")
            break

    return registered


def inject_worker_commands(worker_behaviors, simulation_app, spawned_worker_names, stage):
    """Phase 2: Inject GoTo/Idle/LookAround commands via AgentManager.

    Must be called AFTER timeline.play() and agent registration.
    Workers without commands get a default Idle command.

    Uses CharacterUtil.get_characters_in_stage() to map worker Xform names
    to actual SkelRoot names for agent injection.
    """
    if not _HAS_IRA_CORE:
        print("[WARN] IRA core unavailable, cannot inject commands")
        return 0, 0

    name_map = _build_skelroot_name_map(stage, spawned_worker_names)

    if not AgentManager.has_instance():
        print("[WARN] AgentManager not initialized, waiting for registration...")
        _wait_for_agent_registration(simulation_app)

    if not AgentManager.has_instance():
        print("[ERROR] AgentManager still not available after wait")
        return 0, 0

    agent_manager = AgentManager.get_instance()
    injected = 0
    failed = 0

    registered_names = set(agent_manager.get_all_agent_names())
    print(f"[DEBUG][InjectCommands] Registered agents: {registered_names}")
    print(f"[DEBUG][InjectCommands] Name map: {name_map}")

    for wb in worker_behaviors:
        worker_id = wb.get("worker_id", "worker_01")
        if worker_id not in spawned_worker_names:
            continue

        agent_name = name_map.get(worker_id, worker_id)

        if agent_name not in registered_names:
            print(f"[WARN] {agent_name} (mapped from {worker_id}) not registered with AgentManager, skipping")
            failed += 1
            continue

        commands = wb.get("commands", [])
        if not commands:
            commands = [{"command": "Idle", "duration": 10}]

        cmd_strings = _build_command_string(agent_name, commands)
        print(f"[INFO] Injecting commands for {agent_name}: {cmd_strings}")

        try:
            agent_manager.inject_command(
                agent_name=agent_name,
                command_list=cmd_strings,
                force_inject=True,
                instant=True,
            )
            injected += 1
        except Exception as e:
            print(f"[ERROR] Failed to inject commands for {agent_name}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    for worker_name in spawned_worker_names:
        has_behavior = any(wb.get("worker_id") == worker_name for wb in worker_behaviors)
        if not has_behavior:
            agent_name = name_map.get(worker_name, worker_name)
            if agent_name in registered_names:
                default_cmds = [f"{agent_name} Idle 10"]
                print(f"[INFO] Injecting default idle for {agent_name}: {default_cmds}")
                try:
                    agent_manager.inject_command(
                        agent_name=agent_name,
                        command_list=default_cmds,
                        force_inject=True,
                        instant=True,
                    )
                    injected += 1
                except Exception as e:
                    print(f"[ERROR] Failed to inject default commands for {agent_name}: {e}")
                    failed += 1

    print(f"[INFO] Command injection: {injected} injected, {failed} failed")
    return injected, failed
