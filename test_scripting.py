import sys
from isaacsim import SimulationApp

has_scripting_arg = len(sys.argv) > 1 and sys.argv[1] == "with_scripting"
exts = ["omni.isaac.core"]
if has_scripting_arg:
    exts.append("omni.kit.scripting")

simulation_app = SimulationApp({
    "headless": True,
    "extensions": exts
})

import omni.kit.app
manager = omni.kit.app.get_app().get_extension_manager()

if not has_scripting_arg:
    manager.set_extension_enabled_immediate("omni.kit.scripting", True)

print("Scripting extension enabled:", manager.is_extension_enabled("omni.kit.scripting"))

simulation_app.close()
