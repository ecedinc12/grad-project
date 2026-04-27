"""
Vehicle Animator

Animates non-biped vehicles (e.g. forklifts) over simulation frames using
distance-proportional waypoint interpolation and per-frame angular velocity limiting.
"""

import math


class VehicleAnimator:
    """Animates non-biped vehicles like forklifts over the simulation frames."""

    # Max yaw change per frame — limits turn speed to ~60 deg/s at 30 fps.
    MAX_ROT_PER_FRAME = 2.0
    # Realistic forklift cruising speed (m/s). ~2.5 m/s ≈ 9 km/h.
    MAX_SPEED_MPS = 2.5

    def __init__(self, vehicle_behaviors, stage, fps=30,
                 layout_bounds_min=None, layout_bounds_max=None):
        self.stage = stage
        self.fps = fps
        self.vehicles = []

        self._planner = None
        if layout_bounds_min is not None and layout_bounds_max is not None and vehicle_behaviors:
            try:
                from isaac_backend.layout_planner import LayoutPlanner
                self._planner = LayoutPlanner(stage, layout_bounds_min, layout_bounds_max)
            except Exception as e:
                print(f"[WARN] VehicleAnimator: LayoutPlanner unavailable ({e}); falling back to navmesh")

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

            if self._planner is not None:
                waypoints = self._expand_via_layout(waypoints, v_id)
            else:
                waypoints = self._expand_via_navmesh(waypoints, v_id)

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

            total_dist = sum(
                math.sqrt((waypoints[i+1]["x"] - waypoints[i]["x"])**2 +
                          (waypoints[i+1]["y"] - waypoints[i]["y"])**2)
                for i in range(len(waypoints) - 1)
            )
            self.vehicles.append({
                "id": v_id,
                "waypoints": waypoints,
                "cum_norm": self._compute_cum_norm(waypoints),
                "total_dist": total_dist,
                "translate_op": translate_op,
                "rotate_op": rotate_op,
                "current_rot": None,
            })
            print(f"[INFO] VehicleAnimator tracking {v_id} with {len(waypoints)} waypoints (total dist {total_dist:.1f}m)")

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

    def _compute_cum_norm(self, waypoints):
        """Precompute cumulative normalized distances for speed-consistent interpolation."""
        cum_dists = [0.0]
        for i in range(1, len(waypoints)):
            p1, p2 = waypoints[i - 1], waypoints[i]
            d = math.sqrt((p2["x"] - p1["x"])**2 + (p2["y"] - p1["y"])**2)
            cum_dists.append(cum_dists[-1] + d)
        total = cum_dists[-1]
        if total > 0:
            return [d / total for d in cum_dists]
        n = len(waypoints) - 1
        return [i / n if n > 0 else 0.0 for i in range(len(waypoints))]

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
            # through aisles narrower than 1m of clearance.
            for r in (0.5, 0.3, 0.15):
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

        for v in self.vehicles:
            wps = v["waypoints"]
            if not wps:
                continue

            # Speed-capped progress: distance traveled is bounded by MAX_SPEED_MPS.
            # Once the path is consumed, the vehicle idles at its final waypoint
            # instead of warping or finishing too quickly.
            total_dist = v.get("total_dist", 0.0)
            if total_dist > 1e-6:
                traveled = min(total_dist, (current_frame / self.fps) * self.MAX_SPEED_MPS)
                progress = traveled / total_dist
            else:
                progress = 1.0
            cum = v["cum_norm"]

            # Distance-proportional segment lookup: each segment's share of frames
            # is proportional to its length, giving consistent travel speed.
            segment_idx = len(wps) - 2
            t = 1.0
            for i in range(len(cum) - 1):
                if progress <= cum[i + 1]:
                    segment_idx = i
                    span = cum[i + 1] - cum[i]
                    t = (progress - cum[i]) / span if span > 1e-6 else 0.0
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
