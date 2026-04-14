"""
Isaac Sim 5.1 IRA Behavior Script Manager — Built-in Behavior + Command Injection

Phase 1: Attach IRA's built-in character_behavior.py to worker SkelRoots (before timeline play).
Phase 2: Write command file for character_behavior.py to consume natively.

Falls back to direct USD scripting attribute manipulation when IRA extensions are unavailable.
"""

import asyncio
import os
import time

import carb
import omni.kit.app
import omni.usd

COMMAND_FILE_PATH = "/tmp/worker_commands.txt"

COMMAND_FILE_PATH = "/tmp/worker_commands.txt"

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


def _build_command_file_lines(worker_behaviors, spawned_worker_names):
    """Build command file lines for character_behavior.py.

    Format: "agent_name Command arg1 arg2 ..."
    Example:
        worker_01 GoTo -4.0 -5.0 0.0 90.0
        worker_01 Idle 3.0
        worker_02 GoTo -3.0 5.0 0.0 0.0
    """
    lines = []
    for wb in worker_behaviors:
        worker_id = wb.get("worker_id", "worker_01")
        if worker_id not in spawned_worker_names:
            continue
        commands = wb.get("commands", [])
        if not commands:
            commands = [{"command": "Idle", "duration": 10}]
        for cmd in commands:
            cmd_type = cmd.get("command", "")
            if cmd_type == "GoTo":
                x = cmd.get("x", 0.0)
                y = cmd.get("y", 0.0)
                z = cmd.get("z", 0.0)
                rot = cmd.get("rotation", 0.0)
                lines.append(f"{worker_id} GoTo {x} {y} {z} {rot}")
            elif cmd_type == "Idle":
                duration = cmd.get("duration", 5.0)
                lines.append(f"{worker_id} Idle {duration}")
            elif cmd_type == "LookAround":
                duration = cmd.get("duration", 3.0)
                lines.append(f"{worker_id} LookAround {duration}")

    for worker_name in spawned_worker_names:
        has_behavior = any(wb.get("worker_id") == worker_name for wb in worker_behaviors)
        if not has_behavior:
            lines.append(f"{worker_name} Idle 10")

    return lines


def write_command_file(worker_behaviors, spawned_worker_names, path=COMMAND_FILE_PATH):
    """Write worker commands to a file for character_behavior.py to consume.

    Returns the number of command lines written.
    """
    lines = _build_command_file_lines(worker_behaviors, spawned_worker_names)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"[INFO] Wrote {len(lines)} command lines to {path}")
    for line in lines:
        print(f"[INFO]   {line}")
    return len(lines)


def setup_command_file_path(path=COMMAND_FILE_PATH):
    """Configure omni.anim.people to read commands from the written file."""
    settings = carb.settings.get_settings()
    settings.set("/exts/omni.anim.people/command_settings/command_file_path", path)
    settings.set("/exts/omni.anim.people/command_settings/number_of_loop", "1")
    print(f"[INFO] Command file path set to: {path}")
