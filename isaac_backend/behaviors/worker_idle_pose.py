import math
import random

try:
    import omni.usd
    from pxr import Gf, UsdGeom, Usd
except ImportError:
    pass

try:
    import omni.anim.graph.core as ag
    _HAS_ANIM_GRAPH = True
except ImportError:
    _HAS_ANIM_GRAPH = False

_STATE = {}


def _get_state(prim_path):
    if prim_path not in _STATE:
        _STATE[prim_path] = {
            "interval": 10,
            "rotation_range": (-15.0, 15.0),
            "frame_count": 0,
            "base_rotation_deg": 0.0,
            "anim_id": None,
        }
    return _STATE[prim_path]


def _parse_params(prim):
    EXPOSED_ATTR_NS = "rep:behaviors"
    BEHAVIOR_NS = "workerIdlePose"
    interval = 10
    rotation_range = (-15.0, 15.0)
    interval_attr = prim.GetAttribute(f"{EXPOSED_ATTR_NS}:{BEHAVIOR_NS}:interval")
    if interval_attr and interval_attr.IsValid():
        interval = max(1, int(interval_attr.Get() or 10))
    range_attr = prim.GetAttribute(f"{EXPOSED_ATTR_NS}:{BEHAVIOR_NS}:rotationRange:csv")
    if range_attr and range_attr.IsValid():
        csv = range_attr.Get()
        if csv:
            parts = csv.split(",")
            if len(parts) == 2:
                rotation_range = (float(parts[0]), float(parts[1]))
    return interval, rotation_range


def _find_skel_animation(prim):
    if not prim or not prim.IsValid():
        return None
    for child in Usd.PrimRange(prim):
        if child.GetTypeName() == "SkelAnimation":
            return str(child.GetPath())
    return None


def _set_y_rotation(prim, angle_deg):
    if not prim or not prim.IsValid():
        return
    xform = UsdGeom.Xformable(prim)
    mat = xform.ComputeLocalToWorldTransform(Usd.TimeCode.Default())
    t = mat.ExtractTranslation()
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
    translate_op.Set(Gf.Vec3d(t[0], t[1], t[2]))
    rotateY_op.Set(angle_deg)


def on_play(prim_path):
    stage = omni.usd.get_context().get_stage()
    prim = stage.GetPrimAtPath(prim_path)
    if not prim or not prim.IsValid():
        return
    s = _get_state(prim_path)
    s["interval"], s["rotation_range"] = _parse_params(prim)
    s["frame_count"] = 0
    s["base_rotation_deg"] = 0.0
    if _HAS_ANIM_GRAPH:
        try:
            animator = ag.get_character_animator(prim_path)
            if animator is not None:
                anim_path = _find_skel_animation(prim)
                if anim_path:
                    anim = ag.load_animation(anim_path, looping=True, blend_in=0.3)
                    s["anim_id"] = animator.play_animation(anim)
        except Exception:
            pass


def on_update(prim_path, dt):
    stage = omni.usd.get_context().get_stage()
    prim = stage.GetPrimAtPath(prim_path)
    if not prim or not prim.IsValid():
        return
    s = _get_state(prim_path)
    s["frame_count"] += 1
    if s["frame_count"] % s["interval"] == 0:
        angle = random.uniform(s["rotation_range"][0], s["rotation_range"][1])
        _set_y_rotation(prim, s["base_rotation_deg"] + angle)


def on_stop(prim_path):
    s = _get_state(prim_path)
    if _HAS_ANIM_GRAPH and s["anim_id"] is not None:
        try:
            animator = ag.get_character_animator(prim_path)
            if animator:
                animator.stop_animation(s["anim_id"])
        except Exception:
            pass
    s["anim_id"] = None


def on_destroy(prim_path):
    _STATE.pop(prim_path, None)