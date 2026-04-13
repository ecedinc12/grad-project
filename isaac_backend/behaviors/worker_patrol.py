import math

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
            "waypoints": [],
            "current_wp_idx": 0,
            "speed": 1.0,
            "idle_duration": 3.0,
            "look_around_duration": 2.0,
            "state": "walking",
            "idle_timer": 0.0,
            "look_timer": 0.0,
            "anim_id": None,
            "walk_anim_id": None,
            "base_rotation_deg": 0.0,
        }
    return _STATE[prim_path]


def _parse_waypoints(prim):
    EXPOSED_ATTR_NS = "rep:behaviors"
    BEHAVIOR_NS = "workerPatrol"
    waypoints = []
    csv_attr = prim.GetAttribute(f"{EXPOSED_ATTR_NS}:{BEHAVIOR_NS}:waypoints:csv")
    if csv_attr and csv_attr.IsValid():
        csv = csv_attr.Get()
        if csv:
            for wp_str in csv.split(";"):
                parts = [float(v) for v in wp_str.split(",")]
                waypoints.append(tuple(parts))
    speed_attr = prim.GetAttribute(f"{EXPOSED_ATTR_NS}:{BEHAVIOR_NS}:speed")
    idle_attr = prim.GetAttribute(f"{EXPOSED_ATTR_NS}:{BEHAVIOR_NS}:idleDuration")
    look_attr = prim.GetAttribute(f"{EXPOSED_ATTR_NS}:{BEHAVIOR_NS}:lookAroundDuration")
    return waypoints, speed_attr, idle_attr, look_attr


def _find_skel_animation(prim):
    if not prim or not prim.IsValid():
        return None
    for child in Usd.PrimRange(prim):
        if child.GetTypeName() == "SkelAnimation":
            return str(child.GetPath())
    return None


def _find_walk_animation(prim):
    if not prim or not prim.IsValid():
        return None
    all_anims = []
    for child in Usd.PrimRange(prim):
        if child.GetTypeName() == "SkelAnimation":
            all_anims.append(str(child.GetPath()))
    for ap in all_anims:
        if "walk" in ap.lower() or "move" in ap.lower():
            return ap
    return all_anims[0] if all_anims else None


def _get_position(prim):
    xform = UsdGeom.Xformable(prim)
    if xform:
        mat = xform.ComputeLocalToWorldTransform(Usd.TimeCode.Default())
        t = mat.ExtractTranslation()
        return Gf.Vec3d(t[0], t[1], t[2])
    return Gf.Vec3d(0, 0, 0)


def _set_translate_and_rotateY(prim, tx, ty, tz, ry_deg):
    xform = UsdGeom.Xformable(prim)
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
    translate_op.Set(Gf.Vec3d(tx, ty, tz))
    rotateY_op.Set(ry_deg)


def on_play(prim_path):
    stage = omni.usd.get_context().get_stage()
    prim = stage.GetPrimAtPath(prim_path)
    if not prim or not prim.IsValid():
        return
    s = _get_state(prim_path)
    waypoints, speed_attr, idle_attr, look_attr = _parse_waypoints(prim)
    s["waypoints"] = waypoints
    s["current_wp_idx"] = 0
    s["state"] = "walking"
    s["idle_timer"] = 0.0
    s["look_timer"] = 0.0
    if speed_attr and speed_attr.IsValid():
        s["speed"] = float(speed_attr.Get() or 1.0)
    if idle_attr and idle_attr.IsValid():
        s["idle_duration"] = float(idle_attr.Get() or 3.0)
    if look_attr and look_attr.IsValid():
        s["look_around_duration"] = float(look_attr.Get() or 2.0)
    pos = _get_position(prim)
    s["base_rotation_deg"] = 0.0
    if _HAS_ANIM_GRAPH:
        _play_idle_anim(prim_path, prim)


def on_update(prim_path, dt):
    stage = omni.usd.get_context().get_stage()
    prim = stage.GetPrimAtPath(prim_path)
    if not prim or not prim.IsValid():
        return
    s = _get_state(prim_path)
    if not s["waypoints"]:
        return
    if dt <= 0:
        dt = 1.0 / 30.0
    current_pos = _get_position(prim)

    if s["state"] == "walking":
        wp = s["waypoints"][s["current_wp_idx"]]
        target = Gf.Vec3d(wp[0], wp[1], wp[2] if len(wp) > 2 else 0.0)
        direction = target - current_pos
        dist = direction.GetLength()
        if dist < 0.05:
            s["state"] = "idle"
            s["idle_timer"] = 0.0
            _stop_walk_anim(prim_path, s)
            _set_translate_and_rotateY(prim, current_pos[0], current_pos[1], current_pos[2], s["base_rotation_deg"])
            return
        step = min(s["speed"] * dt, dist)
        direction.Normalize()
        new_pos = current_pos + direction * step
        angle_rad = math.atan2(direction[1], direction[0])
        face_deg = -math.degrees(angle_rad)
        s["base_rotation_deg"] = face_deg
        _set_translate_and_rotateY(prim, new_pos[0], new_pos[1], new_pos[2], face_deg)
        _play_walk_anim(prim_path, prim, s)

    elif s["state"] == "idle":
        s["idle_timer"] += dt
        if s["idle_timer"] >= s["idle_duration"]:
            s["state"] = "look_around"
            s["look_timer"] = 0.0

    elif s["state"] == "look_around":
        s["look_timer"] += dt
        roll = math.sin(s["look_timer"] * 2.0) * 30.0
        pos = _get_position(prim)
        _set_translate_and_rotateY(prim, pos[0], pos[1], pos[2], s["base_rotation_deg"] + roll)
        if s["look_timer"] >= s["look_around_duration"]:
            wp = s["waypoints"][s["current_wp_idx"]]
            final_rot = wp[3] if len(wp) > 3 else s["base_rotation_deg"]
            s["base_rotation_deg"] = final_rot
            pos = _get_position(prim)
            _set_translate_and_rotateY(prim, pos[0], pos[1], pos[2], final_rot)
            s["current_wp_idx"] = (s["current_wp_idx"] + 1) % len(s["waypoints"])
            s["state"] = "walking"


def on_stop(prim_path):
    s = _get_state(prim_path)
    _stop_walk_anim(prim_path, s)
    _stop_idle_anim(prim_path, s)
    s["state"] = "walking"
    s["current_wp_idx"] = 0


def on_destroy(prim_path):
    s = _get_state(prim_path)
    _stop_walk_anim(prim_path, s)
    _stop_idle_anim(prim_path, s)
    _STATE.pop(prim_path, None)


def _play_idle_anim(prim_path, prim):
    if not _HAS_ANIM_GRAPH:
        return
    try:
        animator = ag.get_character_animator(prim_path)
        if animator is None:
            return
        anim_path = _find_skel_animation(prim)
        if anim_path:
            anim = ag.load_animation(anim_path, looping=True, blend_in=0.3)
            _get_state(prim_path)["anim_id"] = animator.play_animation(anim)
    except Exception:
        pass


def _play_walk_anim(prim_path, prim, s):
    if not _HAS_ANIM_GRAPH:
        return
    if s["walk_anim_id"] is not None:
        return
    try:
        animator = ag.get_character_animator(prim_path)
        if animator is None:
            return
        walk_anim_path = _find_walk_animation(prim)
        if walk_anim_path is None:
            return
        if s["anim_id"] is not None:
            animator.stop_animation(s["anim_id"])
            s["anim_id"] = None
        anim = ag.load_animation(walk_anim_path, looping=True, blend_in=0.3)
        s["walk_anim_id"] = animator.play_animation(anim)
    except Exception:
        pass


def _stop_walk_anim(prim_path, s):
    if not _HAS_ANIM_GRAPH or s["walk_anim_id"] is None:
        return
    try:
        animator = ag.get_character_animator(prim_path)
        if animator:
            animator.stop_animation(s["walk_anim_id"])
    except Exception:
        pass
    s["walk_anim_id"] = None


def _stop_idle_anim(prim_path, s):
    if not _HAS_ANIM_GRAPH or s["anim_id"] is None:
        return
    try:
        animator = ag.get_character_animator(prim_path)
        if animator:
            animator.stop_animation(s["anim_id"])
    except Exception:
        pass
    s["anim_id"] = None