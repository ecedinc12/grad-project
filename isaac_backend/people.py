import os
import importlib
import carb

def enable_extensions():
    """Enable omni.anim.people extension."""
    manager = omni.kit.app.get_app().get_extension_manager()
    if not manager.is_extension_enabled("omni.anim.people"):
        print("[INFO] Enabling extension: omni.anim.people")
        manager.set_extension_enabled_immediate("omni.anim.people", True)
    else:
        print("[INFO] Extension already active: omni.anim.people")

def setup_navmesh():
    """Disable navmesh-based navigation (omni.anim.navigation removed in Isaac Sim 5.1)."""
    carb.settings.get_settings().set(
        "/persistent/omni/anim/people/navmeshBasedNavigation", False
    )
    print("[INFO] Direct navigation active (navmesh not available).")

def setup_people_simulation(command_file):
    """Point omni.anim.people at the command file and call setup_characters()."""
    carb.settings.get_settings().set(
        "/persistent/omni/anim/people/commandFilePath", command_file
    )
    print(f"[INFO] People command file: {command_file}")

    success = False
    for module_name, fn_name in [
        ("omni.anim.people", "setup_characters"),
        ("omni.anim.people.scripts.global_agent_manager", "GlobalAgentManager"),
    ]:
        try:
            mod = importlib.import_module(module_name)
            fn = getattr(mod, fn_name)
            if fn_name == "GlobalAgentManager":
                fn().setup_characters()
            else:
                fn()
            print(f"[INFO] setup_characters OK ({module_name})")
            success = True
            break
        except Exception as e:
            print(f"[INFO] {module_name}.{fn_name} failed: {e}")

    if not success:
        raise RuntimeError(
            "CRITICAL: setup_characters() failed to attach AnimGraph. "
            "Characters will remain in T-pose. Check that worker USDs are fully loaded "
            "and world.initialize_simulation_context_async() was called before spawning workers."
        )

def write_command_file(worker_behaviors, path):
    """Serialise worker_behaviors (list of WorkerBehavior dicts) to people_commands.txt format."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lines = []
    for wb in worker_behaviors:
        worker_id = wb.get("worker_id", "worker_01")
        for cmd in wb.get("commands", []):
            command = cmd.get("command")
            if command == "GoTo":
                x = cmd.get("x", 0.0)
                y = cmd.get("y", 0.0)
                rot = cmd.get("rotation", 0.0)
                lines.append(f"{worker_id} GoTo {x} {y} 0.0 {rot}")
            elif command in ("Idle", "LookAround"):
                dur = cmd.get("duration", 2.0)
                lines.append(f"{worker_id} {command} {dur}")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"[INFO] Wrote {len(lines)} command lines to {path}")
