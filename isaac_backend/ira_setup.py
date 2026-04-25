"""
IRA (isaacsim.replicator.agent) Setup

Extension enabling, navmesh baking, Biped_Setup loading, character wrapper USD
creation, behavior script attachment, and AnimationGraph linking.
"""

import os
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

    for mod_name in ("NavigationSchema", "omni.anim.navigation.schema",
                     "omni.anim.navigation.core"):
        try:
            mod = __import__(mod_name, fromlist=["*"])
            attrs = [a for a in dir(mod) if not a.startswith("_")]
            print(f"[DIAG-NAVMESH] module {mod_name}: attrs={attrs}")
            for candidate in ("NavMeshVolume", "NavMeshVolumeAPI",
                              "NavMeshAPI", "Volume"):
                if hasattr(mod, candidate):
                    cls = getattr(mod, candidate)
                    members = [m for m in dir(cls) if not m.startswith("_")]
                    print(f"[DIAG-NAVMESH]   {mod_name}.{candidate}: {members}")
        except Exception as e:
            print(f"[DIAG-NAVMESH] module {mod_name}: import failed: {e}")

    try:
        import omni.anim.navigation.core as nav
        interface = nav.acquire_interface()
        print(f"[DIAG-NAVMESH] nav interface: {interface}")
        members = [m for m in dir(interface) if not m.startswith("_")]
        print(f"[DIAG-NAVMESH]   interface members: {members}")
        ns = getattr(nav, "NavSchema", None)
        if ns is not None:
            ns_attrs = [a for a in dir(ns) if not a.startswith("_")]
            print(f"[DIAG-NAVMESH]   NavSchema attrs: {ns_attrs}")
            for a in ns_attrs:
                obj = getattr(ns, a)
                if isinstance(obj, type):
                    print(f"[DIAG-NAVMESH]     NavSchema.{a} members: "
                          f"{[m for m in dir(obj) if not m.startswith('_')]}")
        cmd_cls = getattr(nav, "CreateNavMeshVolumeCommand", None)
        if cmd_cls is not None:
            print(f"[DIAG-NAVMESH]   CreateNavMeshVolumeCommand: {cmd_cls}")
            init = getattr(cmd_cls, "__init__", None)
            if init is not None:
                import inspect
                try:
                    print(f"[DIAG-NAVMESH]     __init__ sig: {inspect.signature(init)}")
                except Exception as e:
                    print(f"[DIAG-NAVMESH]     __init__ sig: <unreadable: {e}>")
        for const in ("NAVMESH_VOLUME_INCLUDE", "NAVMESH_VOLUME_EXCLUDE",
                      "NAVMESH_VOLUME_NAME", "HALF_EXTENT",
                      "INCLUDE_SCALE", "EXCLUDE_SCALE"):
            if hasattr(nav, const):
                print(f"[DIAG-NAVMESH]   const {const} = {getattr(nav, const)!r}")
    except Exception as e:
        print(f"[DIAG-NAVMESH] nav interface probe failed: {e}")

    print("[DIAG-NAVMESH] ---- end probe ----")


def _enable_navmesh_settings():
    settings = carb.settings.get_settings()
    settings.set("/persistent/omni/anim/people/navmeshBasedNavigation", True)
    settings.set("/exts/omni.anim.people/navigation_settings/navmesh_enabled", True)
    settings.set("/exts/omni.anim.people/navigation_settings/dynamic_avoidance_enabled", True)


def _find_any_navmesh_volume(stage):
    """Return the first NavMeshVolume-typed prim on the stage, or None."""
    for prim in stage.Traverse():
        if prim.GetTypeName() == "NavMeshVolume":
            return prim
    return None


def _define_navmesh_volume(stage, bounds_min, bounds_max, height=4.0,
                            simulation_app=None):
    """Create a NavMeshVolume sized to encompass the warehouse footprint.

    Uses CreateNavMeshVolumeCommand (the same entry point the nav extension's
    UI uses) so every attribute the extension expects is populated via the
    schema's own command. The command places the prim under the stage's
    default-prim path, which is Isaac-variant-specific — we then scan the
    stage to locate it and rescale it to cover the warehouse bounds.
    """
    from pxr import Gf, UsdGeom, Sdf
    import omni.anim.navigation.core as nav

    existing = _find_any_navmesh_volume(stage)
    if existing is not None:
        stage.RemovePrim(existing.GetPath())

    min_x, min_y = bounds_min
    max_x, max_y = bounds_max
    pad = 2.0
    min_x -= pad; min_y -= pad; max_x += pad; max_y += pad
    cx = (min_x + max_x) * 0.5
    cy = (min_y + max_y) * 0.5
    cz = height * 0.5
    sx = max(max_x - min_x, 1.0)
    sy = max(max_y - min_y, 1.0)
    sz = max(height, 1.0)

    cmd = nav.CreateNavMeshVolumeCommand(
        parent_prim_path=Sdf.Path("/World"),
        volume_type=nav.NAVMESH_VOLUME_INCLUDE,
        position=Gf.Vec3d(cx, cy, cz),
    )
    cmd_result = cmd.do()
    print(f"[INFO] CreateNavMeshVolumeCommand.do() returned: {cmd_result!r}")

    if simulation_app is not None:
        for _ in range(5):
            simulation_app.update()

    vol_prim = _find_any_navmesh_volume(stage)
    if vol_prim is None:
        # Dump /World children so we can see what the command actually created.
        try:
            world = stage.GetPrimAtPath("/World")
            children = [(c.GetName(), c.GetTypeName())
                        for c in (world.GetChildren() if world else [])]
            print(f"[DIAG-NAVMESH] /World children after command: {children}")
            roots = [(c.GetName(), c.GetTypeName())
                     for c in stage.GetPseudoRoot().GetChildren()]
            print(f"[DIAG-NAVMESH] stage roots after command: {roots}")
        except Exception as e:
            print(f"[DIAG-NAVMESH] failed to dump stage post-command: {e}")
        raise RuntimeError("CreateNavMeshVolumeCommand did not produce a NavMeshVolume prim")

    xf = UsdGeom.Xformable(vol_prim)
    scale_op = None
    for op in xf.GetOrderedXformOps():
        if op.GetOpType() == UsdGeom.XformOp.TypeScale:
            scale_op = op
            break
    if scale_op is None:
        scale_op = xf.AddScaleOp()
    scale_op.Set(Gf.Vec3f(sx, sy, sz))

    print(f"[INFO] NavMeshVolume created at {vol_prim.GetPath()} "
          f"center=({cx:.2f},{cy:.2f},{cz:.2f}) size=({sx:.2f},{sy:.2f},{sz:.2f})")
    return vol_prim


def bake_navmesh(simulation_app=None, bounds_min=None, bounds_max=None,
                 height=4.0, max_ticks=600):
    """Define a NavMeshVolume covering the warehouse and bake the navmesh.

    Non-blocking: calls start_navmesh_baking() then polls is_navmesh_baking()
    each tick with a bounded budget so a failed bake can't hang the process.
    Returns True if get_navmesh() is non-None after the bake settles.
    """
    _probe_navmesh_environment()

    if bounds_min is None or bounds_max is None:
        print("[WARN] bake_navmesh: no bounds provided — skipping bake, using direct nav.")
        _disable_navmesh_settings()
        return False

    try:
        import omni.anim.navigation.core as nav
    except ImportError as e:
        print(f"[WARN] omni.anim.navigation.core unavailable: {e} — using direct nav.")
        _disable_navmesh_settings()
        return False

    # Enable nav settings BEFORE creating the volume so the extension's stage
    # observer is already running when CreateNavMeshVolumeCommand fires. Prior
    # attempts (see commits 94bfc2b, b28a1f6, 85dcc2f) enabled settings after
    # volume creation; the extension never saw the volume and the bake became
    # a no-op.
    _enable_navmesh_settings()

    stage = omni.usd.get_context().get_stage()

    if simulation_app is not None:
        for _ in range(10):
            simulation_app.update()

    try:
        vol = _define_navmesh_volume(stage, bounds_min, bounds_max, height=height,
                                      simulation_app=simulation_app)
    except Exception as e:
        print(f"[ERROR] Failed to define NavMeshVolume: {e}")
        _disable_navmesh_settings()
        return False

    # Let the extension observe the new volume prim before requesting a bake.
    if simulation_app is not None:
        for _ in range(60):
            simulation_app.update()

    interface = nav.acquire_interface()

    # Blocking bake. Prior attempts used async start_navmesh_baking() + poll
    # loops on is_navmesh_baking(); the flag never flipped reliably, causing
    # the grace-window heuristic to misdiagnose a slow bake as "extension did
    # not see the volume." The probe confirms start_navmesh_baking_and_wait
    # exists on this build.
    try:
        print("[INFO] Calling start_navmesh_baking_and_wait()...")
        sys.stdout.flush()
        interface.start_navmesh_baking_and_wait()
        print("[INFO] start_navmesh_baking_and_wait() returned")
        sys.stdout.flush()
    except Exception as e:
        print(f"[ERROR] start_navmesh_baking_and_wait() raised: {e}")
        sys.stdout.flush()
        _disable_navmesh_settings()
        return False

    # Event-stream drain was removed: in this kit build event_stream.pop()
    # blocks natively (hangs with no exception, no Ctrl-C), even when called
    # after start_navmesh_baking_and_wait() has returned.

    print("[INFO] Polling get_navmesh() for up to 30 ticks...")
    sys.stdout.flush()
    if simulation_app is not None:
        for tick in range(30):
            try:
                nm = interface.get_navmesh()
            except Exception as e:
                print(f"[WARN] get_navmesh() raised at tick {tick}: {e}")
                sys.stdout.flush()
                nm = None
            if nm is not None:
                print(f"[INFO] get_navmesh() returned non-None at tick {tick}")
                sys.stdout.flush()
                break
            simulation_app.update()
        else:
            print("[INFO] get_navmesh() still None after 30 ticks")
            sys.stdout.flush()

    navmesh = interface.get_navmesh()
    if navmesh is None:
        print("[WARN] Navmesh bake completed but get_navmesh() returned None — using direct nav")
        _disable_navmesh_settings()
        return False

    print(f"[INFO] Navmesh baked successfully: {navmesh}")
    return True


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


def force_register_agents(stage, simulation_app=None, max_wait_ticks=10):
    """Manually register every attached BehaviorScript with AgentManager.

    Bypasses character_behavior.py's on_update -> init_character -> dispatch
    chain. In this kit build omni.anim.graph.core.plugin reads AnimationGraphAPI
    via Fabric, which ignores runtime ApplyAnimationGraphAPICommand edits — so
    ag.get_character() returns None inside init_character(), the self-register
    event never fires, and AgentManager stays empty.

    Mirrors IRA's own test_command_injection workaround
    (references/ira_test_command_injection.py:82-96): walks
    ScriptManager._prim_to_scripts, calls init_character(), then
    AgentManager.register_agent() unconditionally. After this, command
    injection works even if init_character() returned False — the agent_name
    -> instance mapping exists and inject_command() appends to inst.commands,
    which on_update eventually drains once Fabric settles.

    Must be called AFTER timeline.play(). Returns (registered, total).
    """
    try:
        from omni.kit.scripting.scripts.script_manager import ScriptManager
    except ImportError as e:
        print(f"[ERROR] force_register_agents: ScriptManager unavailable: {e}")
        return 0, 0

    if not _HAS_IRA_CORE or AgentManager is None:
        print("[ERROR] force_register_agents: AgentManager unavailable")
        return 0, 0

    script_manager = ScriptManager.get_instance()
    agent_manager = AgentManager.get_instance()

    if simulation_app is not None:
        for _ in range(max_wait_ticks):
            if script_manager._prim_to_scripts:
                break
            simulation_app.update()

    debug_tick = bool(os.environ.get("DEBUG_BEHAVIOR_TICK"))
    try:
        import omni.anim.graph.core as _ag_core
    except Exception as _ag_err:
        _ag_core = None
        print(f"[DIAG] omni.anim.graph.core import failed: {_ag_err}")

    registered = 0
    total = 0
    for scripts in script_manager._prim_to_scripts.values():
        for _, inst in scripts.items():
            if not inst:
                continue
            total += 1
            try:
                if hasattr(inst, "init_character"):
                    inst.init_character()
                agent_name = inst.get_agent_name()
                agent_path = inst.prim_path
                agent_manager.register_agent(agent_name, agent_path)
                registered += 1
                print(f"[INFO] force_register_agents: registered {agent_name} @ {agent_path}")

                # --- Phase A diagnostics ---
                char = getattr(inst, "character", None)
                ncmds = len(getattr(inst, "commands", []) or [])
                nav = getattr(inst, "navigation_manager", None)
                print(f"[DIAG] post-init {agent_name}: character={char!r} "
                      f"commands={ncmds} nav_mgr_set={nav is not None}")
                if _ag_core is not None:
                    try:
                        ext_char = _ag_core.get_character(str(agent_path))
                        print(f"[DIAG] ag.get_character({agent_path}) = {ext_char!r}")
                    except Exception as _probe_err:
                        print(f"[DIAG] ag.get_character probe failed: {_probe_err}")

                if debug_tick and not getattr(inst, "_diag_tick_wrapped", False):
                    _orig_on_update = inst.on_update
                    _state = {"n": 0, "last_log": -1.0}

                    def _wrapped_on_update(current_time, delta_time,
                                           _orig=_orig_on_update, _s=_state, _name=agent_name, _inst=inst):
                        _s["n"] += 1
                        if _s["last_log"] < 0 or current_time - _s["last_log"] > 1.0:
                            print(f"[DIAG] on_update {_name}: ticks={_s['n']} t={current_time:.2f} "
                                  f"character={_inst.character is not None} cmds={len(_inst.commands or [])}")
                            _s["last_log"] = current_time
                        return _orig(current_time, delta_time)

                    inst.on_update = _wrapped_on_update
                    inst._diag_tick_wrapped = True
            except Exception as e:
                print(f"[WARN] force_register_agents: failed on {inst}: {e}")

    print(f"[INFO] force_register_agents: {registered}/{total} agents registered")
    return registered, total


def diagnose_behavior_state(label):
    """Phase A checkpoint: print per-script BehaviorScript state.

    Walks ScriptManager._prim_to_scripts and reports whether each instance has
    its anim graph character set, command queue length, current command, and
    navigation manager — so we can tell from the log whether init_character()
    has succeeded by a given point in the pipeline.
    """
    try:
        from omni.kit.scripting.scripts.script_manager import ScriptManager
    except ImportError as e:
        print(f"[DIAG] diagnose_behavior_state({label}): ScriptManager unavailable: {e}")
        return
    sm = ScriptManager.get_instance()
    if not sm or not sm._prim_to_scripts:
        print(f"[DIAG] diagnose_behavior_state({label}): no scripts registered")
        return
    for scripts in sm._prim_to_scripts.values():
        for _, inst in scripts.items():
            if not inst:
                continue
            try:
                name = inst.get_agent_name() if hasattr(inst, "get_agent_name") else "?"
                char = getattr(inst, "character", None)
                ncmds = len(getattr(inst, "commands", []) or [])
                cur = getattr(inst, "current_command", None)
                nav = getattr(inst, "navigation_manager", None)
                print(f"[DIAG] {label} {name}: character_set={char is not None} "
                      f"commands={ncmds} current_command={cur!r} nav_mgr_set={nav is not None}")
            except Exception as e:
                print(f"[DIAG] {label}: inst probe failed: {e}")
