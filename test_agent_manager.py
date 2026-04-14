from isaacsim import SimulationApp
simulation_app = SimulationApp({"headless": True})

import omni.kit.app
manager = omni.kit.app.get_app().get_extension_manager()
manager.set_extension_enabled_immediate("omni.isaac.core", True)
manager.set_extension_enabled_immediate("omni.anim.people", True)
manager.set_extension_enabled_immediate("isaacsim.replicator.agent.core", True)
manager.set_extension_enabled_immediate("isaacsim.replicator.behavior", True)

import omni.timeline
import omni.usd
from isaacsim.core.api import World
from isaacsim.replicator.agent.core.agent_manager import AgentManager
from isaacsim.replicator.agent.core.settings import BehaviorScriptPaths
from isaacsim.replicator.agent.core.stage_util import CharacterUtil
from pxr import UsdGeom, Gf, Sdf

world = World()
stage = omni.usd.get_context().get_stage()

# Spawn character
prim_path = "/World/Characters/worker_01"
stage.DefinePrim("/World/Characters", "Xform")
prim = stage.DefinePrim(prim_path, "Xform")
usd_path = "http://omniverse-content-production.s3-us-west-2.amazonaws.com/Assets/Isaac/5.1/Isaac/People/Characters/male_adult_construction_05/male_adult_construction_05.usd"
prim.GetReferences().AddReference(usd_path)
xf = UsdGeom.Xformable(prim)
xf.ClearXformOpOrder()
xf.AddTranslateOp().Set(Gf.Vec3d(0, 0, 0))

for _ in range(100):
    simulation_app.update()

# Attach behavior
skelroots = CharacterUtil.get_characters_in_stage()
script_path = BehaviorScriptPaths.behavior_script_path()
print(f"Skelroots found: {[s.GetPath() for s in skelroots]}")
print(f"Script path: {script_path}")

CharacterUtil.setup_python_scripts_to_character(skelroots, script_path)

omni.timeline.get_timeline_interface().play()
for _ in range(100):
    simulation_app.update()

agent_manager = AgentManager.get_instance()
print("Registered agents:", agent_manager.get_all_agent_names())

simulation_app.close()
