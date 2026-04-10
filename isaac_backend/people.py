import os
import carb
import omni.kit.app
import omni.timeline
import omni.anim.people

def enable_extensions():
    """Enable all extensions required for omni.anim.people to animate characters."""
    manager = omni.kit.app.get_app().get_extension_manager()
    required = [
        "omni.anim.graph.core",
        "omni.anim.behavior.schema",
        "omni.anim.people",
    ]
    for ext in required:
        if not manager.is_extension_enabled(ext):
            print(f"[INFO] Enabling extension: {ext}")
            manager.set_extension_enabled_immediate(ext, True)
        else:
            print(f"[INFO] Extension already active: {ext}")

def setup_navmesh():
    """Disable navmesh-based navigation (omni.anim.navigation removed in Isaac Sim 5.1)."""
    carb.settings.get_settings().set(
        "/persistent/omni/anim/people/navmeshBasedNavigation", False
    )
    print("[INFO] Direct navigation active (navmesh not available).")

def setup_characters():
    """Apply Animation Graph and BehaviorScript to all prims under /World/Characters."""
    omni.anim.people.setup_characters()
    print("[INFO] setup_characters() called — Animation Graph applied to all characters.")

def setup_people_simulation(command_file):
    """Configure omni.anim.people with character root path and command file."""
    carb.settings.get_settings().set(
        "/persistent/exts/omni.anim.people/character_prim_path", "/World/Characters"
    )
    carb.settings.get_settings().set(
        "/exts/omni.anim.people/command_settings/command_file_path", command_file
    )
    print(f"[INFO] People simulation configured, command file: {command_file}")

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
