"""
Vehicle Animator

Animates non-biped vehicles (e.g. forklifts) over simulation frames using
distance-proportional waypoint interpolation and per-frame angular velocity limiting.
"""

import math


class VehicleAnimator:
    """Animates non-biped vehicles like forklifts over the simulation frames."""

    # Max yaw change per frame — limits turn speed to ~45 deg/s at 30 fps.
    # Real forklifts (especially loaded) turn slower than this; 60 deg/s
    # looked twitchy on heavy yaw blends near pickup waypoints.
    MAX_ROT_PER_FRAME = 1.5
    # Realistic forklift cruising speed (m/s). ~2.5 m/s ≈ 9 km/h.
    MAX_SPEED_MPS = 2.5
    # Creep speed used in the final approach to a docked (pick/place) waypoint.
    # Real operators slow to a near-stop before fork insertion / deposit.
    CREEP_SPEED_MPS = 0.5
    # Distance ahead of a docked waypoint over which speed tapers to creep.
    APPROACH_DIST_M = 1.5

    def __init__(self, vehicle_behaviors, stage, fps=30,
                 layout_bounds_min=None, layout_bounds_max=None):
        self.stage = stage
        self.fps = fps
        self.vehicles = []

        # Prefer the baked navmesh — once obstacles are tagged with
        # NavMeshExcludeAPI it routes around them in 3D and shares one set of
        # tunables with the worker pathfinder. LayoutPlanner stays as a 2D-grid
        # fallback for the case where the bake failed and get_navmesh() is None.
        self._use_navmesh = self._navmesh_available()
        self._planner = None
        if (not self._use_navmesh
                and layout_bounds_min is not None
                and layout_bounds_max is not None
                and vehicle_behaviors):
            try:
                from isaac_backend.layout_planner import LayoutPlanner
                self._planner = LayoutPlanner(stage, layout_bounds_min, layout_bounds_max)
                print("[INFO] VehicleAnimator: navmesh unavailable, using LayoutPlanner fallback")
            except Exception as e:
                print(f"[WARN] VehicleAnimator: LayoutPlanner unavailable ({e})")
        elif self._use_navmesh:
            print("[INFO] VehicleAnimator: routing via baked navmesh")

        for vb in vehicle_behaviors:
            v_id = vb.get("vehicle_id")
            prim_path = f"/World/Entities/{v_id}"
            prim = self.stage.GetPrimAtPath(prim_path)
            if not prim or not prim.IsValid():
                print(f"[WARN] VehicleAnimator: Prim not found for {v_id} at {prim_path}")
                continue

            waypoints = self._extract_waypoints(vb.get("commands", []))
            if len(waypoints) < 2:
                print(f"[WARN] VehicleAnimator: Not enough waypoints for {v_id}")
                continue

            if self._use_navmesh:
                waypoints = self._expand_via_navmesh(waypoints, v_id)
            elif self._planner is not None:
                waypoints = self._expand_via_layout(waypoints, v_id)

            # Cache XformOp references once at init — looking them up every frame
            # via GetOrderedXformOps() can return stale or reordered results when
            # Replicator flushes its USD layer at the camera trigger interval.
            from pxr import UsdGeom
            xformable = UsdGeom.Xformable(prim)
            translate_op = None
            rotate_op = None
            for op in xformable.GetOrderedXformOps():
                if op.GetOpType() == UsdGeom.XformOp.TypeTranslate:
                    translate_op = op
                elif op.GetOpType() in (UsdGeom.XformOp.TypeRotateXYZ, UsdGeom.XformOp.TypeOrient):
                    rotate_op = op
            if translate_op is None:
                translate_op = xformable.AddTranslateOp()
            if rotate_op is None:
                rotate_op = xformable.AddRotateXYZOp()

            seg_lens = [
                math.sqrt((waypoints[i+1]["x"] - waypoints[i]["x"])**2 +
                          (waypoints[i+1]["y"] - waypoints[i]["y"])**2)
                for i in range(len(waypoints) - 1)
            ]
            cum_dist = [0.0]
            for L in seg_lens:
                cum_dist.append(cum_dist[-1] + L)
            total_dist = cum_dist[-1]
            seg_speeds = self._compute_seg_speeds(waypoints, seg_lens)
            self.vehicles.append({
                "id": v_id,
                "waypoints": waypoints,
                "seg_lens": seg_lens,
                "cum_dist": cum_dist,
                "seg_speeds": seg_speeds,
                "total_dist": total_dist,
                "traveled": 0.0,
                "translate_op": translate_op,
                "rotate_op": rotate_op,
                "current_rot": None,
            })
            print(f"[INFO] VehicleAnimator tracking {v_id} with {len(waypoints)} waypoints (total dist {total_dist:.1f}m)")

    @staticmethod
    def _navmesh_available():
        try:
            import omni.anim.navigation.core as nav_core
            return nav_core.acquire_interface().get_navmesh() is not None
        except Exception:
            return False

    def _extract_waypoints(self, commands):
        """Build waypoint list from GoTo/Idle command dicts."""
        waypoints = []
        for cmd in commands:
            if cmd.get("command") == "GoTo":
                waypoints.append({
                    "x": cmd.get("x", 0.0),
                    "y": cmd.get("y", 0.0),
                    "z": cmd.get("z", 0.0),
                    "rot": cmd.get("rotation"),
                })
            elif cmd.get("command") == "Idle" and waypoints:
                # Duplicate last waypoint to hold position for the idle duration.
                waypoints.append(waypoints[-1].copy())
        return waypoints

    def _compute_seg_speeds(self, waypoints, seg_lens):
        """Per-segment speed cap. Segments leading into a docked waypoint
        (one carrying an explicit rotation — i.e. a pickup/dropoff target)
        creep at CREEP_SPEED_MPS for the final APPROACH_DIST_M, mimicking how
        real operators slow to a near-stop before fork insertion."""
        speeds = [self.MAX_SPEED_MPS] * len(seg_lens)
        for i in range(len(seg_lens)):
            if waypoints[i + 1].get("rot") is None:
                continue
            remaining = self.APPROACH_DIST_M
            j = i
            while j >= 0 and remaining > 0:
                speeds[j] = min(speeds[j], self.CREEP_SPEED_MPS)
                remaining -= seg_lens[j]
                j -= 1
        return speeds

    def _expand_via_layout(self, waypoints, v_id):
        """Route around static layout obstacles using a 2D occupancy grid."""
        expanded = [waypoints[0]]
        for i in range(len(waypoints) - 1):
            p1, p2 = waypoints[i], waypoints[i + 1]
            dx, dy = p2["x"] - p1["x"], p2["y"] - p1["y"]
            if dx * dx + dy * dy < 0.01:
                expanded.append(p2)
                continue
            pts = self._planner.plan(p1["x"], p1["y"], p2["x"], p2["y"])
            if pts is None:
                print(f"[WARN] VehicleAnimator: layout planner found no path for {v_id} "
                      f"({p1['x']:.1f},{p1['y']:.1f})->({p2['x']:.1f},{p2['y']:.1f})")
            elif pts:
                for (wx, wy) in pts:
                    expanded.append({"x": wx, "y": wy, "z": p2["z"], "rot": None})
                print(f"[INFO] VehicleAnimator: layout planner added {len(pts)} waypoints for {v_id}")
            expanded.append(p2)
        return expanded

    def _expand_via_navmesh(self, waypoints, v_id):
        """Replace straight-line segments with navmesh-queried paths."""
        try:
            import omni.anim.navigation.core as nav_core
            import carb
            interface = nav_core.acquire_interface()
            navmesh = interface.get_navmesh()
            if navmesh is None:
                print(f"[WARN] VehicleAnimator: navmesh not available for {v_id}, using straight-line paths")
                return waypoints
        except Exception as e:
            print(f"[WARN] VehicleAnimator: could not acquire navmesh for {v_id}: {e}")
            return waypoints

        def _query(p1, p2, radius):
            start = carb.Float3(p1["x"], p1["y"], 0.0)
            end = carb.Float3(p2["x"], p2["y"], 0.0)
            try:
                nav_path = navmesh.query_shortest_path(start, end, agent_radius=radius)
                return nav_path.get_points() if nav_path else None
            except Exception:
                return None

        def _resolve(p1, p2, depth=0):
            """Recursively subdivide a segment until navmesh returns a curved path
            or the subsegment is short enough that straight-line is acceptable."""
            dx, dy = p2["x"] - p1["x"], p2["y"] - p1["y"]
            seg_len = math.sqrt(dx * dx + dy * dy)
            # Try a few agent radii — too generous a radius can fail to find a path
            # through aisles narrower than 1m of clearance. Start near the actual
            # forklift half-width (~0.55 m body, +forks) and back off only if the
            # navmesh refuses, since smaller radii routinely clip pallets.
            for r in (0.85, 0.6, 0.4):
                pts = _query(p1, p2, r)
                if pts and len(pts) > 2:
                    return [{"x": pt[0], "y": pt[1], "z": p2["z"], "rot": None}
                            for pt in pts[1:-1]]
            # Straight-line returned. If the segment is short or we've recursed
            # deep, accept it (likely a clear corridor). Otherwise subdivide.
            if seg_len < 2.0 or depth >= 3:
                return None
            mid = {"x": (p1["x"] + p2["x"]) / 2.0,
                   "y": (p1["y"] + p2["y"]) / 2.0,
                   "z": p2["z"], "rot": None}
            left = _resolve(p1, mid, depth + 1) or []
            right = _resolve(mid, p2, depth + 1) or []
            if left or right:
                return left + [mid] + right
            return None

        expanded = [waypoints[0]]
        for i in range(len(waypoints) - 1):
            p1, p2 = waypoints[i], waypoints[i + 1]
            dx, dy = p2["x"] - p1["x"], p2["y"] - p1["y"]
            if dx * dx + dy * dy < 0.01:
                expanded.append(p2)
                continue
            intermediates = _resolve(p1, p2)
            if intermediates:
                expanded.extend(intermediates)
                print(f"[INFO] VehicleAnimator: navmesh added {len(intermediates)} intermediate points for {v_id}")
            else:
                print(f"[WARN] VehicleAnimator: navmesh returned straight-line path for {v_id} "
                      f"({p1['x']:.1f},{p1['y']:.1f})->({p2['x']:.1f},{p2['y']:.1f}) — accepted as clear corridor")
            expanded.append(p2)
        return expanded

    def update(self, current_frame, total_frames):
        """Update all vehicle positions/rotations for the given frame."""
        if not self.vehicles:
            return

        from pxr import Gf, UsdGeom

        dt = 1.0 / self.fps
        for v in self.vehicles:
            wps = v["waypoints"]
            if not wps:
                continue

            # Variable-speed integration: each segment carries its own speed cap
            # (cruise on long hauls, creep on the final approach to a docked
            # waypoint). Advance traveled distance by speed*dt of whichever
            # segment we're currently inside, so deceleration into pickups is
            # smooth instead of a uniform sweep that runs over pallets.
            total_dist = v.get("total_dist", 0.0)
            cum = v["cum_dist"]
            seg_speeds = v["seg_speeds"]

            traveled = v["traveled"]
            segment_idx = len(wps) - 2
            t = 1.0
            if total_dist > 1e-6 and traveled < total_dist:
                # Locate current segment for speed lookup, then advance.
                for i in range(len(cum) - 1):
                    if traveled <= cum[i + 1]:
                        segment_idx = i
                        break
                traveled = min(total_dist, traveled + seg_speeds[segment_idx] * dt)
                v["traveled"] = traveled

            # Resolve segment + interpolation t for the (possibly advanced) traveled.
            for i in range(len(cum) - 1):
                if traveled <= cum[i + 1]:
                    segment_idx = i
                    span = cum[i + 1] - cum[i]
                    t = (traveled - cum[i]) / span if span > 1e-6 else 0.0
                    break

            p1, p2 = wps[segment_idx], wps[segment_idx + 1]
            cur_x = p1["x"] + (p2["x"] - p1["x"]) * t
            cur_y = p1["y"] + (p2["y"] - p1["y"]) * t
            cur_z = p1["z"] + (p2["z"] - p1["z"]) * t

            dx = p2["x"] - p1["x"]
            dy = p2["y"] - p1["y"]

            if dx * dx + dy * dy > 0.001:
                # Asset faces +Y at 0°; subtract 90° to align with travel direction.
                travel_rot = math.degrees(math.atan2(dy, dx)) - 90.0
                dest_rot = p2.get("rot")
                if dest_rot is not None and t >= 0.7:
                    # Blend into docking orientation in the final 30% of the segment.
                    blend_t = (t - 0.7) / 0.3
                    diff = ((dest_rot - travel_rot + 180) % 360) - 180
                    target_rot = travel_rot + diff * blend_t
                else:
                    target_rot = travel_rot
            else:
                # Stationary (Idle): hold the waypoint's explicit rotation.
                target_rot = (
                    p2.get("rot") if p2.get("rot") is not None
                    else (p1.get("rot") if p1.get("rot") is not None else 0.0)
                )

            # Clamp yaw change per frame for smooth, realistic turns.
            if v["current_rot"] is None:
                v["current_rot"] = target_rot
            else:
                diff = ((target_rot - v["current_rot"] + 180) % 360) - 180
                clamped = max(-self.MAX_ROT_PER_FRAME, min(self.MAX_ROT_PER_FRAME, diff))
                v["current_rot"] += clamped

            v["translate_op"].Set(Gf.Vec3d(cur_x, cur_y, cur_z))
            if v["rotate_op"].GetOpType() == UsdGeom.XformOp.TypeRotateXYZ:
                v["rotate_op"].Set(Gf.Vec3d(0, 0, v["current_rot"]))
