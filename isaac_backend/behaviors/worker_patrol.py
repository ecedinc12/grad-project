"""
Worker Patrol Behavior Script — IRA BehaviorScript subclass

Waypoint lerping with walk/idle/look_around state machine and skeletal
animation blending. Attached to worker prims via isaacsim.replicator.behavior.

Exposed attributes (set by animation.py):
  exposedVar:workerPatrol:waypoints:csv  — "x,y,z,rot;x,y,z,rot;..."
  exposedVar:workerPatrol:speed          — movement speed (m/s)
  exposedVar:workerPatrol:idleDuration   — seconds to idle at waypoint
  exposedVar:workerPatrol:lookAroundDuration — seconds to look around
"""

import math

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


class WorkerPatrolBehavior(BehaviorScript):
    """Patrol between waypoints with walk/idle/look_around state machine."""

    BEHAVIOR_NS = "workerPatrol"

    VARIABLES_TO_EXPOSE = [
        {"attr_name": "waypoints:csv", "attr_type": Sdf.ValueTypeNames.String, "default_value": ""},
        {"attr_name": "speed", "attr_type": Sdf.ValueTypeNames.Float, "default_value": 1.0},
        {"attr_name": "idleDuration", "attr_type": Sdf.ValueTypeNames.Float, "default_value": 3.0},
        {"attr_name": "lookAroundDuration", "attr_type": Sdf.ValueTypeNames.Float, "default_value": 2.0},
    ]

    def on_init(self):
        self.waypoints = []
        self.current_wp_idx = 0
        self.speed = 1.0
        self.idle_duration = 3.0
        self.look_around_duration = 2.0
        self.state = "walking"
        self.idle_timer = 0.0
        self.look_timer = 0.0
        self.base_rotation_deg = 0.0
        self.anim_id = None
        self.walk_anim_id = None
        self._parsed = False

    def _parse_params(self):
        csv = self._get_exposed_variable("waypoints:csv")
        self.waypoints = []
        if csv:
            for wp_str in csv.split(";"):
                parts = [float(v) for v in wp_str.split(",")]
                if len(parts) >= 2:
                    while len(parts) < 4:
                        parts.append(0.0)
                    self.waypoints.append(tuple(parts))
        speed_val = self._get_exposed_variable("speed")
        if speed_val is not None:
            self.speed = float(speed_val)
        idle_val = self._get_exposed_variable("idleDuration")
        if idle_val is not None:
            self.idle_duration = float(idle_val)
        look_val = self._get_exposed_variable("lookAroundDuration")
        if look_val is not None:
            self.look_around_duration = float(look_val)
        self._parsed = True

    def on_play(self):
        if not self._parsed:
            self._parse_params()
        self.current_wp_idx = 0
        self.state = "walking"
        self.idle_timer = 0.0
        self.look_timer = 0.0
        self.base_rotation_deg = 0.0
        self._try_play_idle_anim()

    def on_update(self, current_time, delta_time):
        if not self.waypoints:
            if not self._parsed:
                self._parse_params()
            if not self.waypoints:
                return
        dt = delta_time if delta_time > 0 else 1.0 / 30.0
        current_pos = self._get_position()

        if self.state == "walking":
            wp = self.waypoints[self.current_wp_idx]
            target = Gf.Vec3d(wp[0], wp[1], wp[2])
            direction = target - current_pos
            dist = direction.GetLength()

            if dist < 0.05:
                self.state = "idle"
                self.idle_timer = 0.0
                self._stop_walk_anim()
                return

            step = min(self.speed * dt, dist)
            direction.Normalize()
            new_pos = current_pos + direction * step
            self._set_translate_and_rotateY(
                new_pos[0], new_pos[1], new_pos[2],
                -math.degrees(math.atan2(direction[1], direction[0]))
            )
            self._try_play_walk_anim()

        elif self.state == "idle":
            self.idle_timer += dt
            if self.idle_timer >= self.idle_duration:
                self.state = "look_around"
                self.look_timer = 0.0

        elif self.state == "look_around":
            self.look_timer += dt
            roll = math.sin(self.look_timer * 2.0) * 30.0
            pos = self._get_position()
            self._set_translate_and_rotateY(
                pos[0], pos[1], pos[2],
                self.base_rotation_deg + roll
            )
            if self.look_timer >= self.look_around_duration:
                wp = self.waypoints[self.current_wp_idx]
                final_rot = wp[3] if len(wp) > 3 else 0.0
                self.base_rotation_deg = final_rot
                pos = self._get_position()
                self._set_translate_and_rotateY(pos[0], pos[1], pos[2], final_rot)
                self.current_wp_idx = (self.current_wp_idx + 1) % len(self.waypoints)
                self.state = "walking"

    def on_stop(self):
        self._stop_walk_anim()
        self._stop_idle_anim()
        self.state = "walking"
        self.current_wp_idx = 0

    def on_destroy(self):
        self._stop_walk_anim()
        self._stop_idle_anim()

    def _get_position(self):
        xform = UsdGeom.Xformable(self.prim)
        if xform:
            mat = xform.ComputeLocalToWorldTransform(Usd.TimeCode.Default())
            t = mat.ExtractTranslation()
            return Gf.Vec3d(t[0], t[1], t[2])
        return Gf.Vec3d(0, 0, 0)

    def _set_translate_and_rotateY(self, tx, ty, tz, ry_deg):
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
        translate_op.Set(Gf.Vec3d(tx, ty, tz))
        rotateY_op.Set(ry_deg)

    def _find_skel_animation(self):
        for child in Usd.PrimRange(self.prim):
            if child.GetTypeName() == "SkelAnimation":
                return str(child.GetPath())
        return None

    def _find_walk_animation(self):
        all_anims = []
        for child in Usd.PrimRange(self.prim):
            if child.GetTypeName() == "SkelAnimation":
                all_anims.append(str(child.GetPath()))
        for ap in all_anims:
            if "walk" in ap.lower() or "move" in ap.lower():
                return ap
        return all_anims[0] if all_anims else None

    def _try_play_idle_anim(self):
        if not _HAS_ANIM_GRAPH:
            print(f"[DEBUG][PatrolIdleAnim] _HAS_ANIM_GRAPH=False for {self.prim_path}, skipping")
            return
        print(f"[DEBUG][PatrolIdleAnim] Attempting idle anim for {self.prim_path}")
        try:
            animator = ag.get_character_animator(self.prim_path)
            if animator is None:
                print(f"[DEBUG][PatrolIdleAnim] ag.get_character_animator('{self.prim_path}') returned None")
                return
            print(f"[DEBUG][PatrolIdleAnim] Animator obtained: {animator}")
            anim_path = self._find_skel_animation()
            if anim_path is None:
                print(f"[DEBUG][PatrolIdleAnim] _find_skel_animation() returned None for {self.prim_path}")
                return
            print(f"[DEBUG][PatrolIdleAnim] Found SkelAnimation: {anim_path}")
            anim = ag.load_animation(anim_path, looping=True, blend_in=0.3)
            self.anim_id = animator.play_animation(anim)
            print(f"[DEBUG][PatrolIdleAnim] Animation played, anim_id={self.anim_id}")
        except Exception as e:
            print(f"[DEBUG][PatrolIdleAnim] Exception for {self.prim_path}: {e}")
            import traceback
            traceback.print_exc()

    def _try_play_walk_anim(self):
        if not _HAS_ANIM_GRAPH:
            print(f"[DEBUG][PatrolWalkAnim] _HAS_ANIM_GRAPH=False for {self.prim_path}, skipping")
            return
        if self.walk_anim_id is not None:
            return
        print(f"[DEBUG][PatrolWalkAnim] Attempting walk anim for {self.prim_path}")
        try:
            animator = ag.get_character_animator(self.prim_path)
            if animator is None:
                print(f"[DEBUG][PatrolWalkAnim] ag.get_character_animator('{self.prim_path}') returned None")
                return
            print(f"[DEBUG][PatrolWalkAnim] Animator obtained: {animator}")
            walk_anim_path = self._find_walk_animation()
            if walk_anim_path is None:
                print(f"[DEBUG][PatrolWalkAnim] _find_walk_animation() returned None for {self.prim_path}")
                return
            print(f"[DEBUG][PatrolWalkAnim] Found walk animation: {walk_anim_path}")
            if self.anim_id is not None:
                animator.stop_animation(self.anim_id)
                self.anim_id = None
            anim = ag.load_animation(walk_anim_path, looping=True, blend_in=0.3)
            self.walk_anim_id = animator.play_animation(anim)
            print(f"[DEBUG][PatrolWalkAnim] Walk animation played, anim_id={self.walk_anim_id}")
        except Exception as e:
            print(f"[DEBUG][PatrolWalkAnim] Exception for {self.prim_path}: {e}")
            import traceback
            traceback.print_exc()

    def _try_play_walk_anim(self):
        if not _HAS_ANIM_GRAPH:
            print(f"[DEBUG][PatrolWalkAnim] _HAS_ANIM_GRAPH=False for {self.prim_path}, skipping")
            return
        if self.walk_anim_id is not None:
            return
        print(f"[DEBUG][PatrolWalkAnim] Attempting walk anim for {self.prim_path}")
        try:
            animator = ag.get_character_animator(self.prim_path)
            if animator is None:
                print(f"[DEBUG][PatrolWalkAnim] ag.get_character_animator('{self.prim_path}') returned None")
                return
            print(f"[DEBUG][PatrolWalkAnim] Animator obtained: {animator}")
            walk_anim_path = self._find_walk_animation()
            if walk_anim_path is None:
                print(f"[DEBUG][PatrolWalkAnim] _find_walk_animation() returned None for {self.prim_path}")
                return
            print(f"[DEBUG][PatrolWalkAnim] Found walk animation: {walk_anim_path}")
            if self.anim_id is not None:
                animator.stop_animation(self.anim_id)
                self.anim_id = None
            anim = ag.load_animation(walk_anim_path, looping=True, blend_in=0.3)
            self.walk_anim_id = animator.play_animation(anim)
            print(f"[DEBUG][PatrolWalkAnim] Walk animation played, anim_id={self.walk_anim_id}")
        except Exception as e:
            print(f"[DEBUG][PatrolWalkAnim] Exception for {self.prim_path}: {e}")
            import traceback
            traceback.print_exc()

    def _stop_walk_anim(self):
        if not _HAS_ANIM_GRAPH or self.walk_anim_id is None:
            return
        try:
            animator = ag.get_character_animator(self.prim_path)
            if animator:
                animator.stop_animation(self.walk_anim_id)
        except Exception:
            pass
        self.walk_anim_id = None

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
