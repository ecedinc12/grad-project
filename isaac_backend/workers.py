"""
Worker Spawner — Spawn worker characters as Xform prims with USD references,
PPE visibility toggling, and semantic labeling.

omni.anim.people handles animation internally — no AnimationGraph setup needed.
PPE items (hardhat, ear protection, safety vest) are separate Mesh prims inside
the character USD and can be individually hidden via UsdGeom.Imageable.MakeInvisible().
"""

import random
from pxr import Gf, Usd, UsdGeom
import omni.usd
from isaac_backend.semantics import apply_usd_semantics, _set_semantic

HARDHAT_MESH_KEYWORDS = {"hardhat", "earprotection"}
VEST_MESH_KEYWORDS = {"safetyvest"}
ALL_PPE_MESH_KEYWORDS = HARDHAT_MESH_KEYWORDS | VEST_MESH_KEYWORDS


def _find_skelroot(prim):
    """Find the first SkelRoot descendant of a prim (inside referenced USD)."""
    for child in Usd.PrimRange(prim):
        if child.GetTypeName() == "SkelRoot":
            return child
    return None


def _wait_for_skelroot(prim_path, stage, simulation_app, max_ticks=240):
    """Poll until the SkelRoot descendant appears inside a referenced character USD.

    S3-hosted USD assets load asynchronously. After AddReference(), the
    SkelRoot inside the reference is not immediately reachable via
    Usd.PrimRange. This function ticks the simulation app and re-checks
    until the SkelRoot resolves or the timeout expires.
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


def _classify_mesh(prim_name):
    """Classify a Mesh prim by its name into PPE category or None.

    Returns "hardhat" for hardhat/earprotection meshes,
    "vest" for safety vest meshes, or None for non-PPE meshes.
    """
    name_lower = prim_name.lower()
    if any(kw in name_lower for kw in HARDHAT_MESH_KEYWORDS):
        return "hardhat"
    if any(kw in name_lower for kw in VEST_MESH_KEYWORDS):
        return "vest"
    return None


def apply_ppe(worker_prim, ppe_state):
    """Toggle PPE mesh visibility and apply semantic labels.

    For each Mesh prim under the worker:
    - If hardhat keyword and ppe_state.hardhat is False: hide (MakeInvisible)
    - If vest keyword and ppe_state.vest is False: hide (MakeInvisible)
    - If PPE mesh is visible: apply its category semantic ("hardhat" or "vest")
    - Non-PPE meshes are left unlabeled (blanket "person" is applied later)

    Must be called AFTER SkelRoot resolution (full hierarchy loaded).
    """
    has_hardhat = ppe_state.get("hardhat", False)
    has_vest = ppe_state.get("vest", False)

    hidden = []
    labeled = []

    for child in Usd.PrimRange(worker_prim):
        if child.GetTypeName() != "Mesh":
            continue

        child_name = str(child.GetPath()).split("/")[-1]
        ppe_category = _classify_mesh(child_name)

        if ppe_category == "hardhat":
            if has_hardhat:
                UsdGeom.Imageable(child).MakeVisible()
                _set_semantic(child, "hardhat")
                labeled.append((str(child.GetPath()), "hardhat"))
            else:
                UsdGeom.Imageable(child).MakeInvisible()
                hidden.append((str(child.GetPath()), "hardhat"))

        elif ppe_category == "vest":
            if has_vest:
                UsdGeom.Imageable(child).MakeVisible()
                _set_semantic(child, "vest")
                labeled.append((str(child.GetPath()), "vest"))
            else:
                UsdGeom.Imageable(child).MakeInvisible()
                hidden.append((str(child.GetPath()), "vest"))

    print(f"[INFO] PPE for {worker_prim.GetPath()}: hardhat={has_hardhat}, vest={has_vest}")
    if labeled:
        print(f"[INFO]   Visible PPE meshes: {labeled}")
    if hidden:
        print(f"[INFO]   Hidden PPE meshes: {hidden}")

    return hidden, labeled


def collect_worker_ppe_mesh_names(worker_prim):
    """Collect the prim path names of PPE meshes under a worker prim.

    Used by apply_scene_semantics to know which meshes to skip when
    applying blanket "person" labels.
    """
    ppe_paths = set()
    for child in Usd.PrimRange(worker_prim):
        if child.GetTypeName() != "Mesh":
            continue
        child_name = str(child.GetPath()).split("/")[-1]
        if _classify_mesh(child_name) is not None:
            ppe_paths.add(str(child.GetPath()))
    return ppe_paths


def spawn_workers(workers, worker_behaviors, asset_library, stage, simulation_app=None, visible_bounds=None):
    """Spawn workers as Xform prims with USD references, PPE visibility, and semantics.

    visible_bounds: (min_x, max_x, min_y, max_y) constraining spawn positions
                    to the camera-visible area. GoTo targets are clamped; random
                    fallback positions are drawn from within these bounds.
    Returns a set of spawned worker names (e.g. {"worker_01", "worker_02"}).
    """
    def _initial_pos(worker_id):
        for wb in worker_behaviors:
            if wb.get("worker_id") == worker_id:
                for cmd in wb.get("commands", []):
                    if cmd.get("command") == "GoTo":
                        x, y = cmd.get("x", 0.0), cmd.get("y", 0.0)
                        if visible_bounds is not None:
                            x = max(visible_bounds[0], min(visible_bounds[1], x))
                            y = max(visible_bounds[2], min(visible_bounds[3], y))
                        return x, y
        if visible_bounds is not None:
            return random.uniform(visible_bounds[0], visible_bounds[1]), random.uniform(visible_bounds[2], visible_bounds[3])
        return random.uniform(-5.0, 5.0), random.uniform(-1.5, 1.5)

    if workers:
        stage.DefinePrim("/World/Characters", "Xform")

    spawned_names = set()
    worker_idx = 0
    usd_path = asset_library["worker"]

    for entity in workers:
        worker_idx += 1
        name = f"worker_{worker_idx:02d}"
        prim_path = f"/World/Characters/{name}"

        ppe_state = entity.get("ppe_state") or {}

        prim = stage.DefinePrim(prim_path, "Xform")
        prim.GetReferences().AddReference(usd_path)

        spawn_x, spawn_y = _initial_pos(name)
        xf = UsdGeom.Xformable(prim)
        xf.ClearXformOpOrder()
        xf.AddTranslateOp().Set(Gf.Vec3d(spawn_x, spawn_y, 0.0))

        apply_usd_semantics(prim_path, "person")
        for child in Usd.PrimRange(prim):
            _set_semantic(child, "person")
        spawned_names.add(name)

        print(f"[INFO] Spawned {name} @ ({spawn_x:.2f}, {spawn_y:.2f}, 0.0) ppe={ppe_state}")

    # Wait for SkelRoots to resolve, then apply PPE visibility
    if simulation_app is not None and workers:
        for worker_idx, entity in enumerate(workers, 1):
            name = f"worker_{worker_idx:02d}"
            prim_path = f"/World/Characters/{name}"
            skelroot = _wait_for_skelroot(prim_path, stage, simulation_app)
            if skelroot is None:
                print(f"[ERROR] SkelRoot not found for {name} after timeout.")
                continue

            # Re-fetch the worker Xform prim for PPE application
            worker_prim = stage.GetPrimAtPath(prim_path)
            ppe_state = entity.get("ppe_state") or {}
            apply_ppe(worker_prim, ppe_state)
    else:
        for worker_idx, entity in enumerate(workers, 1):
            name = f"worker_{worker_idx:02d}"
            prim_path = f"/World/Characters/{name}"
            prim = stage.GetPrimAtPath(prim_path)
            skelroot = _find_skelroot(prim) if prim and prim.IsValid() else None
            if skelroot is None:
                print(f"[WARN] SkelRoot not found for {name} (no simulation_app for async wait).")
                continue

            worker_prim = stage.GetPrimAtPath(prim_path)
            ppe_state = entity.get("ppe_state") or {}
            apply_ppe(worker_prim, ppe_state)

    print(f"[INFO] Spawned {len(spawned_names)} workers: {sorted(spawned_names)}")
    return spawned_names