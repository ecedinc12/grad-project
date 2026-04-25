"""Probe omni.anim.graph.core Python binding surface. Boots SimulationApp,
dumps dir() of the module, the binding submodule, and the acquired interface,
then exits. Run with: /isaac-sim/python.sh probe_anim_api.py
"""

from isaacsim import SimulationApp

simulation_app = SimulationApp({
    "headless": True,
    "renderer": "RayTracedLighting",
    "extension_remote_config": True,
    "extensions": [
        "omni.anim.people",
        "omni.anim.graph.core",
        "omni.anim.graph.schema",
        "omni.anim.graph.ui",
    ],
})

print("=" * 60)
import omni.anim.graph.core as ag
print("--- omni.anim.graph.core (dir) ---")
print(sorted(n for n in dir(ag) if not n.startswith("_")))
print()

print("--- bindings._omni_anim_graph_core (dir) ---")
import omni.anim.graph.core.bindings._omni_anim_graph_core as ag_b
print(sorted(n for n in dir(ag_b) if not n.startswith("_")))
print()

print("--- acquire_interface() result ---")
try:
    plug = ag.acquire_interface()
    print("type:", type(plug).__name__)
    print("members:", sorted(n for n in dir(plug) if not n.startswith("_")))
except Exception as e:
    print("acquire_interface failed:", e)
print()

print("--- looking for IAnimGraph manual-update interface ---")
# IAnimGraph is a separate carb interface from ICharacter; there may be a second
# acquire_* binding for it.
for name in dir(ag_b):
    if "anim" in name.lower() or "graph" in name.lower() or "acquire" in name.lower():
        print("  candidate:", name)

simulation_app.close()
