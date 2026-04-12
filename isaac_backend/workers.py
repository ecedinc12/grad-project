import os
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


def _wait_for_skelroot(prim_path, stage, simulation_app, max_ticks=240):
    """Poll until the SkelRoot descendent appears inside a referenced character USD.

    S3-hosted USD assets load asynchronously. After ``AddReference()``, the
    SkelRoot inside the reference is not immediately reachable via
    ``Usd.PrimRange``.  This function ticks the simulation app and re-checks
    until the SkelRoot resolves or the timeout expires.

    Parameters
    ----------
    prim_path : str
        Path of the parent Xform prim (e.g. ``/World/Characters/worker_01``).
    stage : Usd.Stage
        The USD stage.
    simulation_app : SimulationApp
        The Isaac Sim app handle used to tick updates.
    max_ticks : int
        Maximum number of ``simulation_app.update()`` calls before giving up.

    Returns
    -------
    Usd.Prim or None
        The resolved SkelRoot prim, or None if it never appeared.
    """
    for tick in range(max_ticks):
        prim = stage.GetPrimAtPath(prim_path)
        skelroot = _find_skelroot(prim) if prim and prim.IsValid() else None
        if skelroot is not None:
            print(f"[INFO] SkelRoot resolved for {prim_path} after {tick + 1} ticks")
            return skelroot
        simulation_app.update()
        if tick > 0 and tick % 60 == 0:
            print(f"[INFO] Still waiting for SkelRoot at {prim_path} ({tick}/{max_ticks} ticks)...")
    print(f"[ERROR] SkelRoot never appeared for {prim_path} after {max_ticks} ticks")
    return None

def attach_character_behavior(prim_path):
    """Attach CharacterBehavior script to the SkelRoot inside the referenced character USD.

    Locates the first SkelRoot descendant, applies the AnimationGraphAPI schema,
    resolves the character_behavior.py script path from the omni.anim.people
    extension, applies the ScriptingAPI, and wires up the script attribute.

    Returns the SkelRoot path on success, None on failure.
    """
    stage = omni.usd.get_context().get_stage()
    prim = stage.GetPrimAtPath(prim_path)
    if not prim or not prim.IsValid():
        print(f"[ERROR] Prim not valid: {prim_path}")
        return None

    skelroot = _find_skelroot(prim)
    if skelroot is None:
        print(f"[WARN] No SkelRoot found under {prim_path}, skipping behavior attachment.")
        return None

    try:
        AnimGraphSchema.AnimationGraphAPI.Apply(skelroot)
        print(f"[INFO] Applied AnimationGraphAPI to {skelroot.GetPath()}")
    except Exception as e:
        print(f"[WARN] AnimationGraphAPI.Apply failed for {skelroot.GetPath()}: {e}")

    script_path = None
    try:
        ext_manager = omni.kit.app.get_app().get_extension_manager()
        ext_path = ext_manager.get_extension_path_by_module("omni.anim.people")
        if ext_path:
            candidate = os.path.join(ext_path, "omni", "anim", "people", "scripts", "character_behavior.py")
            if os.path.isfile(candidate):
                script_path = candidate
            else:
                script_path = ext_path + "/omni/anim/people/scripts/character_behavior.py"
        else:
            print(f"[WARN] Could not resolve omni.anim.people extension path for {prim_path}")
    except Exception as e:
        print(f"[WARN] Failed to resolve script path for {prim_path}: {e}")

    if script_path is None:
        print(f"[ERROR] Cannot attach behavior script to {prim_path}: script path unresolved.")
        return None

    try:
        omni.kit.commands.execute("ApplyScriptingAPICommand", paths=[Sdf.Path(str(skelroot.GetPath()))])
    except Exception as e:
        print(f"[WARN] ApplyScriptingAPICommand failed for {skelroot.GetPath()}: {e}")

    skelroot.GetAttribute("omni:scripting:scripts").Set([script_path])
    print(f"[INFO] Attached CharacterBehavior to SkelRoot at {skelroot.GetPath()}")
    return str(skelroot.GetPath())

_PPE_KEYS = ["worker_with_ppe", "worker_with_ppe_alt"]
_NO_PPE_KEYS = ["worker_no_ppe"]


def select_worker_usd(ppe_state, asset_library):
    """Return a randomly-selected worker USD path based on whether PPE is worn.

    Picks from a pool of appearance variants for visual diversity while
    keeping all characters appropriate for a warehouse environment.
    """
    if ppe_state.get("hardhat", False) or ppe_state.get("vest", False):
        key = random.choice(_PPE_KEYS)
    else:
        key = random.choice(_NO_PPE_KEYS)
    return asset_library[key]

def spawn_workers(workers, worker_behaviors, asset_library, stage, simulation_app=None):
    """Spawn workers directly on the USD stage (required by omni.anim.people).

    Returns a set of successfully spawned character names (e.g. {"worker_01", "worker_02"}).

    Parameters
    ----------
    simulation_app : SimulationApp, optional
        Required to poll for async S3 asset resolution.  If provided, the
        function will tick the simulation until each worker's SkelRoot appears
        before attaching the behavior script.  If None, behavior attachment
        is attempted immediately (may fail for remote USD assets).
    """
    def _initial_pos(worker_id):
        for wb in worker_behaviors:
            if wb.get("worker_id") == worker_id:
                for cmd in wb.get("commands", []):
                    if cmd.get("command") == "GoTo":
                        return cmd.get("x", 0.0), cmd.get("y", 0.0)
        return random.uniform(-5.0, 5.0), random.uniform(-1.5, 1.5)

    if workers:
        stage.DefinePrim("/World/Characters", "Xform")

    spawned_names = set()
    spawned_prims = []
    worker_idx = 0
    for entity in workers:
        worker_idx += 1
        name = f"worker_{worker_idx:02d}"
        prim_path = f"/World/Characters/{name}"

        ppe_state = entity.get("ppe_state") or {}
        usd_path = select_worker_usd(ppe_state, asset_library)

        prim = stage.DefinePrim(prim_path, "Xform")
        prim.GetReferences().AddReference(usd_path)

        spawn_x, spawn_y = _initial_pos(name)
        xf = UsdGeom.Xformable(prim)
        xf.ClearXformOpOrder()
        xf.AddTranslateOp().Set(Gf.Vec3d(spawn_x, spawn_y, 0.0))

        apply_semantics(prim_path, "person")
        spawned_names.add(name)
        spawned_prims.append(prim_path)

        print(f"[INFO] Spawned {name} @ ({spawn_x:.2f}, {spawn_y:.2f}, 0.0) ppe={ppe_state}")
        print(f"[DEBUG] Worker {name} prim valid: {prim.IsValid()}")
        print(f"[DEBUG] Worker {name} visibility: {UsdGeom.Imageable(prim).ComputeVisibility()}")
        mat = xf.ComputeLocalToWorldTransform(Usd.TimeCode.Default())
        pos = mat.ExtractTranslation()
        print(f"[DEBUG] Worker {name} world position: ({pos[0]:.2f}, {pos[1]:.2f}, {pos[2]:.2f})")

    if simulation_app is not None:
        for prim_path in spawned_prims:
            name = prim_path.rsplit("/", 1)[-1]
            skelroot = _wait_for_skelroot(prim_path, stage, simulation_app)
            if skelroot is not None:
                skel_path = attach_character_behavior(prim_path)
                if skel_path is None:
                    print(f"[WARN] Behavior script not attached to {name}; character may not animate.")
            else:
                print(f"[ERROR] SkelRoot not found for {name} after timeout; skipping behavior attachment.")
    else:
        for prim_path in spawned_prims:
            name = prim_path.rsplit("/", 1)[-1]
            skel_path = attach_character_behavior(prim_path)
            if skel_path is None:
                print(f"[WARN] Behavior script not attached to {name}; character may not animate.")

    return spawned_names
