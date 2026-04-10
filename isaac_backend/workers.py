import random
import AnimGraphSchema
from pxr import Gf, UsdGeom, Usd, Sdf
import omni.usd
import omni.kit.app
import omni.kit.commands
import omni.replicator.core as rep
from isaac_backend.semantics import apply_semantics

def _find_skelroot(prim):
    """Find the first SkelRoot descendant of a prim (inside referenced USD)."""
    for child in Usd.PrimRange(prim):
        if child.GetTypeName() == "SkelRoot":
            return child
    return None

def attach_character_behavior(prim_path):
    """Attach CharacterBehavior script to the SkelRoot inside the referenced character USD."""
    stage = omni.usd.get_context().get_stage()
    prim = stage.GetPrimAtPath(prim_path)

    skelroot = _find_skelroot(prim)
    if skelroot is None:
        print(f"[ERROR] No SkelRoot found under {prim_path}")
        return

    AnimGraphSchema.AnimationGraphAPI.Apply(skelroot)
    print(f"[INFO] Applied AnimationGraphAPI to {skelroot.GetPath()}")

    script_path = (
        omni.kit.app.get_app().get_extension_manager()
        .get_extension_path_by_module("omni.anim.people")
        + "/omni/anim/people/scripts/character_behavior.py"
    )

    omni.kit.commands.execute("ApplyScriptingAPICommand", paths=[Sdf.Path(skelroot.GetPath())])
    skelroot.GetAttribute("omni:scripting:scripts").Set([script_path])
    print(f"[INFO] Attached CharacterBehavior to SkelRoot at {skelroot.GetPath()}")

def select_worker_usd(ppe_state, asset_library):
    """Return the worker USD path based on whether PPE is worn."""
    if ppe_state.get("hardhat", False) or ppe_state.get("vest", False):
        return asset_library["worker_with_ppe"]
    return asset_library["worker_no_ppe"]

def spawn_workers(workers, worker_behaviors, asset_library, stage):
    """Spawn workers directly on the USD stage (required by omni.anim.people)."""
    def _initial_pos(worker_id):
        for wb in worker_behaviors:
            if wb.get("worker_id") == worker_id:
                for cmd in wb.get("commands", []):
                    if cmd.get("command") == "GoTo":
                        return cmd.get("x", 0.0), cmd.get("y", 0.0)
        return random.uniform(-5.0, 5.0), random.uniform(-1.5, 1.5)

    if workers:
        stage.DefinePrim("/World/Characters", "Xform")

    worker_idx = 0
    for entity in workers:
        worker_idx += 1
        name = f"worker_{worker_idx:02d}"
        prim_path = f"/World/Characters/{name}"

        ppe_state = entity.get("ppe_state") or {}
        usd_path = select_worker_usd(ppe_state, asset_library)

        prim = stage.DefinePrim(prim_path, "Xform")
        prim.GetReferences().AddReference(usd_path)

        attach_character_behavior(prim_path)

        spawn_x, spawn_y = _initial_pos(name)
        xf = UsdGeom.Xformable(prim)
        xf.ClearXformOpOrder()
        xf.AddTranslateOp().Set(Gf.Vec3d(spawn_x, spawn_y, 0.0))

        apply_semantics(prim_path, "person")

        print(f"[INFO] Spawned {name} @ ({spawn_x:.2f}, {spawn_y:.2f}, 0.0) ppe={ppe_state}")
        print(f"[DEBUG] Worker {name} prim valid: {prim.IsValid()}")
        print(f"[DEBUG] Worker {name} visibility: {UsdGeom.Imageable(prim).ComputeVisibility()}")
        mat = xf.ComputeLocalToWorldTransform(Usd.TimeCode.Default())
        pos = mat.ExtractTranslation()
        print(f"[DEBUG] Worker {name} world position: ({pos[0]:.2f}, {pos[1]:.2f}, {pos[2]:.2f})")
