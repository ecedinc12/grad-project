"""
Worker Idle Pose Behavior Script — IRA BehaviorScript subclass

Periodic Y-rotation randomization with idle animation. Attached to workers
that have no patrol commands.

Exposed attributes (set by animation.py):
  exposedVar:workerIdlePose:interval          — frames between rotation changes
  exposedVar:workerIdlePose:rotationRange:csv — "min_deg,max_deg"
"""

import random

try:
    from pxr import Sdf
except ImportError:
    Sdf = None

try:
    from omni.behavior.scripting.core import BehaviorScript
    _HAS_BEHAVIOR_SCRIPT = True
except ImportError:
    _HAS_BEHAVIOR_SCRIPT = False

    class BehaviorScript:
        """Fallback stub when omni.behavior.scripting.core is unavailable."""
        def __init__(self):
            self.prim = None
            self.prim_path = ""

        def _get_exposed_variable(self, name):
            if not self.prim or not self.prim.IsValid():
                return None
            from pxr import Sdf
            full_name = f"exposedVar:{self.BEHAVIOR_NS}:{name}"
            attr = self.prim.GetAttribute(full_name)
            if attr and attr.IsValid():
                return attr.Get()
            return None

try:
    import omni.anim.graph.core as ag
    _HAS_ANIM_GRAPH = True
except ImportError:
    _HAS_ANIM_GRAPH = False

import omni.usd
from pxr import Gf, UsdGeom, Usd


class WorkerIdlePoseBehavior(BehaviorScript):
    """Periodically randomize Y rotation while playing idle animation."""

    BEHAVIOR_NS = "workerIdlePose"

    VARIABLES_TO_EXPOSE = [
        {"attr_name": "interval", "attr_type": Sdf.ValueTypeNames.UInt, "default_value": 10},
        {"attr_name": "rotationRange:csv", "attr_type": Sdf.ValueTypeNames.String, "default_value": "-15.0,15.0"},
    ]

    def on_init(self):
        self.interval = 10
        self.rotation_range = (-15.0, 15.0)
        self.frame_count = 0
        self.base_rotation_deg = 0.0
        self.anim_id = None

    def on_play(self):
        self._parse_params()
        self.frame_count = 0
        self.base_rotation_deg = 0.0
        self._try_play_idle_anim()

    def on_update(self, current_time, delta_time):
        if not self.prim or not self.prim.IsValid():
            return
        self.frame_count += 1
        if self.frame_count % self.interval == 0:
            angle = random.uniform(self.rotation_range[0], self.rotation_range[1])
            self._set_y_rotation(self.base_rotation_deg + angle)

    def on_stop(self):
        self._stop_idle_anim()

    def on_destroy(self):
        self._stop_idle_anim()

    def _parse_params(self):
        interval_val = self._get_exposed_variable("interval")
        if interval_val is not None:
            self.interval = max(1, int(interval_val))
        range_csv = self._get_exposed_variable("rotationRange:csv")
        if range_csv:
            parts = range_csv.split(",")
            if len(parts) == 2:
                self.rotation_range = (float(parts[0]), float(parts[1]))

    def _set_y_rotation(self, angle_deg):
        if not self.prim or not self.prim.IsValid():
            return
        xform = UsdGeom.Xformable(self.prim)
        translate_op = None
        rotateY_op = None
        for op in xform.GetOrderedXformOps():
            if op.GetOpType() == UsdGeom.XformOp.TypeTranslate:
                translate_op = op
            elif op.GetOpType() == UsdGeom.XformOp.TypeRotateY:
                rotateY_op = op
        if translate_op is None:
            translate_op = xform.AddTranslateOp()
        if rotateY_op is None:
            rotateY_op = xform.AddRotateYOp()
        mat = xform.ComputeLocalToWorldTransform(Usd.TimeCode.Default())
        t = mat.ExtractTranslation()
        translate_op.Set(Gf.Vec3d(t[0], t[1], t[2]))
        rotateY_op.Set(angle_deg)

    def _get_skel_root_path(self):
        """Find the SkelRoot prim path within the worker hierarchy for animation graph access."""
        if not self.prim or not self.prim.IsValid():
            return self.prim_path
        for child in Usd.PrimRange(self.prim):
            if child.GetTypeName() == "SkelRoot":
                path = str(child.GetPath())
                return path
        return self.prim_path

    def _get_skel_root_path(self):
        """Find the SkelRoot prim path within the worker hierarchy for animation graph access."""
        if not self.prim or not self.prim.IsValid():
            return self.prim_path
        for child in Usd.PrimRange(self.prim):
            if child.GetTypeName() == "SkelRoot":
                path = str(child.GetPath())
                return path
        return self.prim_path

    def _find_skel_animation(self):
        if not self.prim or not self.prim.IsValid():
            print(f"[DEBUG][FindSkelAnim] Prim invalid for {self.prim_path}")
            return None
        print(f"[DEBUG][FindSkelAnim] Searching for SkelAnimation in {self.prim_path}")
        found_anims = []
        for child in Usd.PrimRange(self.prim):
            type_name = child.GetTypeName()
            if type_name == "SkelAnimation":
                found_anims.append(str(child.GetPath()))
                print(f"[DEBUG][FindSkelAnim] Found SkelAnimation: {child.GetPath()}")
            elif type_name in ("SkelRoot", "Xform", "Scope", "Mesh"):
                print(f"[DEBUG][FindSkelAnim] Found {type_name}: {child.GetPath()}")
        if not found_anims:
            print(f"[DEBUG][FindSkelAnim] No SkelAnimation found in {self.prim_path}")
        return found_anims[0] if found_anims else None

    def _try_play_idle_anim(self):
        if not _HAS_ANIM_GRAPH:
            print(f"[DEBUG][IdleAnim] _HAS_ANIM_GRAPH=False for {self.prim_path}, skipping")
            return
        skel_path = self._get_skel_root_path()
        print(f"[DEBUG][IdleAnim] Attempting idle anim for {self.prim_path}, skel_path={skel_path}")
        try:
            animator = ag.get_character_animator(skel_path)
            if animator is None:
                print(f"[DEBUG][IdleAnim] ag.get_character_animator('{skel_path}') returned None")
                return
            print(f"[DEBUG][IdleAnim] Animator obtained: {animator}")
            anim_path = self._find_skel_animation()
            if anim_path is None:
                print(f"[DEBUG][IdleAnim] _find_skel_animation() returned None for {self.prim_path}")
                return
            print(f"[DEBUG][IdleAnim] Found SkelAnimation: {anim_path}")
            anim = ag.load_animation(anim_path, looping=True, blend_in=0.3)
            self.anim_id = animator.play_animation(anim)
            print(f"[DEBUG][IdleAnim] Animation played, anim_id={self.anim_id}")
        except Exception as e:
            print(f"[DEBUG][IdleAnim] Exception for {self.prim_path}: {e}")
            import traceback
            traceback.print_exc()

    def _stop_idle_anim(self):
        if not _HAS_ANIM_GRAPH or self.anim_id is None:
            return
        skel_path = self._get_skel_root_path()
        try:
            animator = ag.get_character_animator(skel_path)
            if animator:
                animator.stop_animation(self.anim_id)
        except Exception:
            pass
        self.anim_id = None
