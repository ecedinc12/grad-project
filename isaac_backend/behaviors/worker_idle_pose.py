import random

try:
    from omni.behavior.scripting.core import BehaviorScript
    _HAS_BEHAVIOR_SCRIPT = True
except ImportError:
    _HAS_BEHAVIOR_SCRIPT = False

    class BehaviorScript:
        def __init__(self):
            self.prim = None
            self.prim_path = ""

        def _get_exposed_variable(self, name):
            if not self.prim or not self.prim.IsValid():
                return None
            from pxr import Sdf
            import omni.usd
            full_name = f"rep:behaviors:{self.BEHAVIOR_NS}:{name}"
            attr = self.prim.GetAttribute(full_name)
            if attr and attr.IsValid():
                return attr.Get()
            return None

try:
    import omni.anim.graph.core as ag
    _HAS_ANIM_GRAPH = True
except ImportError:
    _HAS_ANIM_GRAPH = False

try:
    import omni.usd
    from pxr import Gf, UsdGeom, Usd
except ImportError:
    pass


class WorkerIdlePoseBehavior(BehaviorScript):
    BEHAVIOR_NS = "workerIdlePose"

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

    def _find_skel_animation(self):
        if not self.prim or not self.prim.IsValid():
            return None
        for child in Usd.PrimRange(self.prim):
            if child.GetTypeName() == "SkelAnimation":
                return str(child.GetPath())
        return None

    def _try_play_idle_anim(self):
        if not _HAS_ANIM_GRAPH:
            return
        try:
            animator = ag.get_character_animator(self.prim_path)
            if animator is None:
                return
            anim_path = self._find_skel_animation()
            if anim_path:
                anim = ag.load_animation(anim_path, looping=True, blend_in=0.3)
                self.anim_id = animator.play_animation(anim)
        except Exception:
            pass

    def _stop_idle_anim(self):
        if not _HAS_ANIM_GRAPH or self.anim_id is None:
            return
        try:
            animator = ag.get_character_animator(self.prim_path)
            if animator:
                animator.stop_animation(self.anim_id)
        except Exception:
            pass
        self.anim_id = None