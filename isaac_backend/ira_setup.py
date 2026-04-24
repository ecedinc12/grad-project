"""
IRA (isaacsim.replicator.agent) Setup

Extension enabling, navmesh baking, Biped_Setup loading, character wrapper USD
creation, behavior script attachment, and AnimationGraph linking.
"""

import sys
import time
import carb
import omni.kit.app
import omni.usd

# --- Lazy IRA imports (populated by _refresh_ira_state after extensions are enabled) ---
AgentManager = None
BehaviorScriptPaths = None
PrimPaths = None
CharacterUtil = None
add_behavior_script = None
_HAS_IRA_CORE = False
_HAS_IRA_BEHAVIOR = False
_HAS_KIT_COMMANDS = False
Sdf = None


def _progress(msg):
    print(f"[PROGRESS] [{time.strftime('%H:%M:%S')}] {msg}")
    sys.stdout.flush()


def _refresh_ira_state():
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
    """Enable extensions required for IRA behavior scripts and configure navmesh settings.

    Navmesh baking has been unreliable in this build across multiple attempts
    (see git log: 2a976cb, e67a435, 1077877, current HEAD). start_navmesh_baking()
    hangs the process natively and auto-bake never produces a navmesh. We run
    without navmesh — GoTo uses straight-line paths with dynamic avoidance
    handling inter-agent collisions. Vehicle path curving falls back gracefully
    in VehicleAnimator._expand_via_navmesh.
    """
    settings = carb.settings.get_settings()
    settings.set("/persistent/omni/anim/people/navmeshBasedNavigation", False)
    settings.set("/exts/omni.anim.people/navigation_settings/navmesh_enabled", False)
    settings.set("/exts/omni.anim.people/navigation_settings/dynamic_avoidance_enabled", True)
    settings.set("/persistent/exts/omni.anim.people/character_prim_path", "/World/Characters")
    print("[INFO] Navmesh disabled — GoTo uses direct navigation with dynamic avoidance")
    print("[INFO] CHARACTER_PRIM_PATH set to /World/Characters")

    manager = omni.kit.app.get_app().get_extension_manager()
    extensions = [
        "omni.kit.scripting",
        "isaacsim.replicator.behavior",
        "isaacsim.replicator.agent.core",
        "omni.anim.graph.core",
        "omni.anim.graph.schema",
        "omni.anim.people",
        "omni.anim.navigation.schema",
        "omni.anim.navigation.core",
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
        for _ in range(60):
            simulation_app.update()

    _refresh_ira_state()


def _disable_navmesh_settings():
    settings = carb.settings.get_settings()
    settings.set("/persistent/omni/anim/people/navmeshBasedNavigation", False)
    settings.set("/exts/omni.anim.people/navigation_settings/navmesh_enabled", False)
    settings.set("/exts/omni.anim.people/navigation_settings/dynamic_avoidance_enabled", False)


def _probe_navmesh_environment():
    """Probe extension registry, kit command registry, and navmesh settings.

    Prints a [DIAG-NAVMESH] block so we can decide between a real bake and
    direct-navigation fallback without trial-and-error runs.
    """
    print("[DIAG-NAVMESH] ---- begin probe ----")
    try:
        import omni.kit.app
        manager = omni.kit.app.get_app().get_extension_manager()
        for ext_name in ("omni.nav.mesh", "omni.anim.navigation.core", "omni.anim.navigation.schema"):
            try:
                ext_id = manager.get_extension_id(ext_name)
            except Exception as e:
                ext_id = f"<error: {e}>"
            try:
                enabled = manager.is_extension_enabled(ext_name)
            except Exception as e:
                enabled = f"<error: {e}>"
            print(f"[DIAG-NAVMESH] ext {ext_name}: id={ext_id!r} enabled={enabled}")
    except Exception as e:
        print(f"[DIAG-NAVMESH] extension manager probe failed: {e}")

    try:
        import omni.kit.commands
        commands = omni.kit.commands.get_commands()
        command_names = set()
        if isinstance(commands, dict):
            for v in commands.values():
                if isinstance(v, dict):
                    command_names.update(v.keys())
                else:
                    command_names.add(str(v))
        for cmd in ("RebuildNavMesh", "CreateNavMesh", "AddNavMeshVolume"):
            present = cmd in command_names
            print(f"[DIAG-NAVMESH] command {cmd}: registered={present}")
    except Exception as e:
        print(f"[DIAG-NAVMESH] kit command probe failed: {e}")

    try:
        settings = carb.settings.get_settings()
        for key in (
            "/persistent/omni/anim/people/navmeshBasedNavigation",
            "/exts/omni.anim.people/navigation_settings/navmesh_enabled",
            "/exts/omni.anim.people/navigation_settings/dynamic_avoidance_enabled",
        ):
            print(f"[DIAG-NAVMESH] setting {key} = {settings.get(key)!r}")
    except Exception as e:
        print(f"[DIAG-NAVMESH] settings probe failed: {e}")
    print("[DIAG-NAVMESH] ---- end probe ----")


def bake_navmesh(simulation_app=None):
    """No-op. Kept as a call-site stub; see enable_behavior_extensions for rationale."""
    _probe_navmesh_environment()
    print("[INFO] Navmesh bake skipped (navmesh disabled; using direct navigation).")
    _disable_navmesh_settings()
    return False


def ensure_biped_setup(simulation_app=None):
    """Load Biped_Setup.usd invisibly to provide shared AnimationGraph + animations.

    Uses CharacterUtil.load_default_biped_to_stage() which creates
    /World/Characters/Biped_Setup with walk/sit/idle animations and an
    AnimationGraph prim. Required before linking workers to the graph.

    Returns the Biped_Setup Xform prim, or None on failure.
    """
    if not _HAS_IRA_CORE:
        print("[WARN] IRA core unavailable — cannot load Biped_Setup")
        return None

    try:
        biped_prim = CharacterUtil.load_default_biped_to_stage()
        print(f"[INFO] Biped_Setup loaded at {biped_prim.GetPath()}")
    except Exception as e:
        print(f"[WARN] CharacterUtil.load_default_biped_to_stage() failed: {e}")
        try:
            from isaacsim.replicator.agent.core.settings import AssetPaths
            biped_path = AssetPaths.default_biped_asset_path()
            stage = omni.usd.get_context().get_stage()
            stage.DefinePrim("/World/Characters/Biped_Setup", "Xform")
            prim = stage.GetPrimAtPath("/World/Characters/Biped_Setup")
            prim.GetReferences().AddReference(biped_path)
            prim.GetAttribute("visibility").Set("invisible")
            print("[INFO] Biped_Setup loaded manually at /World/Characters/Biped_Setup")
            biped_prim = prim
        except Exception as e2:
            print(f"[ERROR] Failed to load Biped_Setup: {e2}")
            return None

    if simulation_app:
        for _ in range(30):
            simulation_app.update()

    return biped_prim


# --- AnimationGraph discovery helpers ---

def _find_animation_graph(biped_prim, stage):
    """Find the AnimationGraph prim under the Biped_Setup hierarchy."""
    from pxr import Usd
    for prim in Usd.PrimRange(biped_prim):
        if prim.GetTypeName() == "AnimationGraph":
            return prim
    for prim in stage.Traverse():
        if prim.GetTypeName() == "AnimationGraph":
            return prim
    return None


def _find_stage_animation_graph(stage):
    """Find the AnimationGraph prim on stage, checking Biped_Setup first."""
    biped_prim = stage.GetPrimAtPath("/World/Characters/Biped_Setup")
    if biped_prim and biped_prim.IsValid():
        result = _find_animation_graph(biped_prim, stage)
        if result:
            return result
    for prim in stage.Traverse():
        if prim.GetTypeName() == "AnimationGraph":
            return prim
    return None


def wait_for_animation_graph(stage, simulation_app, max_ticks=120):
    """Poll until the AnimationGraph prim from Biped_Setup is fully resolved.

    Biped_Setup contains nested USD references that load asynchronously.
    The AnimationGraph prim may not be traversable immediately after
    ensure_biped_setup() returns.  Returns the prim, or None on timeout.
    """
    for tick in range(max_ticks):
        prim = _find_stage_animation_graph(stage)
        if prim is not None:
            print(f"[INFO] AnimationGraph resolved at {prim.GetPath()} after {tick} ticks")
            return prim
        simulation_app.update()
        if tick > 0 and tick % 30 == 0:
            print(f"[INFO] Waiting for AnimationGraph prim... ({tick}/{max_ticks} ticks)")
    print("[ERROR] AnimationGraph prim never appeared on stage after "
          f"{max_ticks} ticks — workers will not animate")
    return None


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


# --- Wrapper USD creation ---

def create_character_wrapper_usd(original_usd_path, stage):
    """Create a temporary wrapper USD with AnimationGraphAPI baked into the SkelRoot.

    Fabric populates its prim attribute cache at first load from the static layer stack.
    Runtime USD overrides (OverridePrim / ApplyAPI calls) arrive after that cache is
    sealed and are silently ignored by Fabric. A wrapper USD file is processed as part
    of the static stack, so Fabric sees AnimationGraphAPI from the very first sync.

    Returns the path to the temp wrapper file, or original_usd_path if creation fails.
    """
    import tempfile
    from pxr import Usd, Sdf as _Sdf

    # Find SkelRoot relative path — strip defaultPrim prefix since references compose
    # the asset's defaultPrim out of the path (e.g. "Root/Char" → "Char").
    skelroot_rel = None
    try:
        tmp_stage = Usd.Stage.Open(original_usd_path)
        if tmp_stage:
            dp = tmp_stage.GetDefaultPrim()
            prefix = (dp.GetName() + "/") if dp and dp.IsValid() else ""
            for prim in tmp_stage.Traverse():
                if prim.GetTypeName() == "SkelRoot":
                    rel = str(prim.GetPath()).lstrip("/")
                    if prefix and rel.startswith(prefix):
                        rel = rel[len(prefix):]
                    skelroot_rel = rel
                    break
    except Exception as e:
        print(f"[WARN] create_character_wrapper_usd: could not inspect asset: {e}")

    if not skelroot_rel:
        print("[WARN] create_character_wrapper_usd: no SkelRoot in asset — using original USD")
        return original_usd_path

    anim_graph_prim = _find_stage_animation_graph(stage)
    if anim_graph_prim is None:
        print("[WARN] create_character_wrapper_usd: no AnimationGraph on stage — using original USD")
        return original_usd_path

    try:
        tmp_path = tempfile.mktemp(suffix=".usda")
        wrapper = Usd.Stage.CreateNew(tmp_path)

        root = wrapper.DefinePrim("/CharacterWrapper", "Xform")
        wrapper.SetDefaultPrim(root)
        root.GetReferences().AddReference(original_usd_path)

        skelroot_abs = f"/CharacterWrapper/{skelroot_rel}"
        sr_over = wrapper.OverridePrim(skelroot_abs)

        anim_graph_path = anim_graph_prim.GetPath()
        applied = False

        # --- Strategy 1: AnimGraphSchema Python bindings (best) ---
        try:
            import AnimGraphSchema
            AnimGraphSchema.AnimationGraphAPI.Apply(sr_over)
            api = AnimGraphSchema.AnimationGraphAPI(sr_over)
            rel = api.GetAnimationGraphRel()
            if rel:
                rel.SetTargets([anim_graph_path])
                # Capture the actual relationship name for diagnostics
                print(f"[INFO] create_character_wrapper_usd: AnimationGraphAPI applied via "
                      f"AnimGraphSchema at {skelroot_abs} (rel={rel.GetName()})")
            applied = True
        except (ImportError, AttributeError) as e:
            print(f"[INFO] create_character_wrapper_usd: AnimGraphSchema unavailable ({e}), "
                  "using Sdf layer fallback")

        # --- Strategy 2: Raw Sdf layer API on the wrapper stage ---
        # CRITICAL: Do NOT use omni.kit.commands here — kit commands always
        # operate on the main simulation stage, not this wrapper stage.
        if not applied:
            layer = wrapper.GetRootLayer()
            prim_spec = layer.GetPrimAtPath(skelroot_abs)
            if prim_spec is None:
                print(f"[WARN] create_character_wrapper_usd: prim spec not found at {skelroot_abs}")
                return original_usd_path

            # Add AnimationGraphAPI to apiSchemas
            schemas = _Sdf.TokenListOp()
            schemas.prependedItems = ["AnimationGraphAPI"]
            prim_spec.SetInfo("apiSchemas", schemas)

            # Create the animationGraph relationship.
            # Try the two known property names used across Omniverse versions.
            anim_graph_sdf_path = _Sdf.Path(str(anim_graph_path))
            for rel_name in ("animationGraph:animationGraph", "animationGraphs:animationGraph"):
                try:
                    rel_spec = _Sdf.RelationshipSpec(prim_spec, rel_name, custom=False)
                    rel_spec.targetPathList.explicitItems = [anim_graph_sdf_path]
                    applied = True
                    print(f"[INFO] create_character_wrapper_usd: AnimationGraphAPI applied via "
                          f"Sdf layer at {skelroot_abs} (rel={rel_name})")
                    break
                except Exception as rel_err:
                    print(f"[INFO] create_character_wrapper_usd: rel name '{rel_name}' failed: {rel_err}")

            if not applied:
                print("[WARN] create_character_wrapper_usd: could not create animationGraph "
                      "relationship — using original USD")
                return original_usd_path

        wrapper.Save()

        # --- Verify the saved wrapper actually contains AnimationGraphAPI ---
        verify = Usd.Stage.Open(tmp_path)
        if verify:
            vp = verify.GetPrimAtPath(skelroot_abs)
            api_schemas = vp.GetMetadata("apiSchemas") if vp else None
            rels = [r.GetName() for r in vp.GetRelationships()] if vp else []
            print(f"[INFO] create_character_wrapper_usd: verification — "
                  f"apiSchemas={api_schemas}, relationships={rels}")
            if api_schemas is None:
                print("[WARN] create_character_wrapper_usd: wrapper verification FAILED — "
                      "AnimationGraphAPI not present in saved file")

        print(f"[INFO] create_character_wrapper_usd: wrapper saved to {tmp_path} "
              f"(SkelRoot rel: {skelroot_rel})")
        return tmp_path

    except Exception as e:
        print(f"[WARN] create_character_wrapper_usd: failed: {e}")
        return original_usd_path


# --- Behavior script attachment ---

def _attach_ira_builtin_behavior(skelroot_prim):
    """Attach IRA's built-in character_behavior.py to a character SkelRoot."""
    if not _HAS_IRA_CORE:
        print("[WARN] IRA core unavailable, cannot attach built-in behavior")
        return False

    script_path = BehaviorScriptPaths.behavior_script_path()
    print(f"[INFO] Attaching IRA built-in behavior to {skelroot_prim.GetPath()}")

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
        print("[WARN] Cannot attach behavior script — kit commands unavailable")
        return False

    try:
        manager = omni.kit.app.get_app().get_extension_manager()
        people_path = manager.get_extension_path_by_module("omni.anim.people")
        script_path = f"{people_path}/omni/anim/people/scripts/character_behavior.py"
    except Exception:
        script_path = "/dev/null"

    prim_path = str(skelroot_prim.GetPath())
    try:
        import omni.kit.commands
        omni.kit.commands.execute("ApplyScriptingAPICommand", paths=[Sdf.Path(prim_path)])
        attr = skelroot_prim.GetAttribute("omni:scripting:scripts")
        if attr:
            attr.Set([script_path])
        print(f"[INFO] Fallback behavior script attached to {prim_path}: {script_path}")
        return True
    except Exception as e:
        print(f"[ERROR] Fallback attachment failed for {prim_path}: {e}")
        return False


def setup_all_behaviors_async(spawned_worker_names, worker_behaviors, stage):
    """Attach IRA's built-in behavior script to all worker SkelRoots.

    Must be called BEFORE timeline.play(). The behavior script will
    automatically register the agent with AgentManager when play starts.

    Returns (attached, failed) counts.
    """
    attached = 0
    failed = 0

    print(f"[DEBUG][SetupBehaviors] _HAS_IRA_CORE={_HAS_IRA_CORE}")
    print(f"[DEBUG][SetupBehaviors] spawned_worker_names={spawned_worker_names}")

    all_workers = set(spawned_worker_names)
    for wb in worker_behaviors:
        worker_id = wb.get("worker_id", "")
        short_id = worker_id.removeprefix("worker_")
        canonical = f"worker_{short_id}" if short_id != worker_id else worker_id
        if worker_id not in all_workers and canonical not in all_workers:
            print(f"[INFO] No spawned worker matches behavior worker_id='{worker_id}' (tried '{canonical}')")

    for worker_name in sorted(all_workers):
        skelroot = _find_skelroot_for_worker(worker_name, stage)
        if skelroot is None:
            print(f"[WARN] SkelRoot not found for {worker_name}")
            failed += 1
            continue

        try:
            ok = _attach_ira_builtin_behavior(skelroot) if _HAS_IRA_CORE else _attach_builtin_fallback(skelroot)
            if ok:
                attached += 1
            else:
                failed += 1
        except Exception as e:
            print(f"[ERROR] Failed to attach behavior to {worker_name}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print(f"[INFO] IRA behaviors: {attached} attached, {failed} failed")
    return attached, failed


# --- AnimationGraph linking ---

def _link_animation_graph_fallback(skelroots, anim_graph_prim, stage):
    """Fallback: apply AnimationGraphAPI manually using omni.kit.commands."""
    if not _HAS_KIT_COMMANDS or Sdf is None:
        print("[WARN] Cannot link animation graph — kit commands unavailable")
        return 0, len(skelroots)

    import omni.kit.commands
    paths = [Sdf.Path(str(sr.GetPath())) for sr in skelroots]
    anim_graph_path = Sdf.Path(str(anim_graph_prim.GetPath()))

    try:
        omni.kit.commands.execute("RemoveAnimationGraphAPICommand", paths=paths)
        omni.kit.commands.execute(
            "ApplyAnimationGraphAPICommand", paths=paths, animation_graph_path=anim_graph_path
        )
        print(f"[INFO] AnimationGraphAPI applied to {len(skelroots)} SkelRoots via kit commands")
        return len(skelroots), 0
    except Exception as e:
        print(f"[ERROR] kit command animation graph linking failed: {e}")
        return 0, len(skelroots)


def link_workers_to_animation_graph(spawned_worker_names, stage, simulation_app=None):
    """Apply AnimationGraphAPI to each worker SkelRoot and link to AnimationGraph.

    Uses CharacterUtil.setup_animation_graph_to_character() first, then always
    re-applies via kit commands so Fabric picks up the animationGraph attribute.

    Returns (linked, failed) counts.
    """
    skelroots = []
    missing = 0
    for name in sorted(spawned_worker_names):
        skelroot = _find_skelroot_for_worker(name, stage)
        if skelroot is None:
            print(f"[WARN] SkelRoot not found for {name}, skipping animation graph link")
            missing += 1
            continue
        skelroots.append(skelroot)

    if not skelroots:
        print("[WARN] No SkelRoots found to link to AnimationGraph")
        return 0, missing

    anim_graph_prim = _find_stage_animation_graph(stage)
    if anim_graph_prim is None:
        print("[ERROR] No AnimationGraph prim found on stage — cannot link workers")
        return 0, len(skelroots) + missing

    print(f"[INFO] Found AnimationGraph at {anim_graph_prim.GetPath()}")

    if _HAS_IRA_CORE and CharacterUtil is not None:
        try:
            CharacterUtil.setup_animation_graph_to_character(skelroots, anim_graph_prim)
            print(f"[INFO] AnimationGraphAPI applied to {len(skelroots)} SkelRoots via CharacterUtil")
        except Exception as e:
            print(f"[WARN] CharacterUtil.setup_animation_graph_to_character() failed: {e}")

    # Always re-apply via kit commands so Fabric picks up the animationGraph attribute.
    # CharacterUtil writes to the USD layer but omni.fabric.plugin reads its own
    # attribute cache — the kit command path triggers the Fabric change notification.
    linked, kit_failed = _link_animation_graph_fallback(skelroots, anim_graph_prim, stage)

    if simulation_app:
        for _ in range(10):
            simulation_app.update()

    try:
        import AnimGraphSchema
        for sr in skelroots:
            is_skelroot = sr.GetTypeName() == "SkelRoot"
            has_ag = sr.HasAPI(AnimGraphSchema.AnimationGraphAPI)
            schemas = sr.GetAppliedSchemas()
            print(f"[DIAG] {sr.GetPath()} typeName={sr.GetTypeName()} "
                  f"IsA(SkelRoot)={is_skelroot} HasAPI(AnimationGraphAPI)={has_ag} "
                  f"appliedSchemas={list(schemas)}")
    except Exception as e:
        print(f"[DIAG] apiSchema inspection failed: {e}")

    return linked, kit_failed + missing
