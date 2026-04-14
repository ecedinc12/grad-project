from isaacsim import SimulationApp
app = SimulationApp({"headless": True})
import omni.anim.graph.core as ag
print(dir(ag))
app.close()
