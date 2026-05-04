"""Project camera frustum to ground plane and fit camera to entities."""

import math

from isaac_backend.camera.bounds import (
    WAREHOUSE_INTERIOR_X,
    WAREHOUSE_INTERIOR_Y,
    INTERIOR_MARGIN,
    CEILING_Z,
    MIN_INDOOR_HEIGHT,
    clamp_to_warehouse,
)

SENSOR_WIDTH_MM = 36.0
SENSOR_HEIGHT_MM = 20.25
VISIBLE_MARGIN_FRACTION = 0.25
MIN_VISIBLE_SIZE = 2.0


def compute_ground_visible_area(cam_pos, look_at, focal_length=14.0,
                                margin_fraction=VISIBLE_MARGIN_FRACTION):
    cam_x, cam_y, cam_z = cam_pos
    la_x, la_y, la_z = look_at

    dx = la_x - cam_x
    dy = la_y - cam_y
    dz = la_z - cam_z
    d_len = math.sqrt(dx * dx + dy * dy + dz * dz)
    if d_len < 1e-6:
        dz = -1.0
        d_len = 1.0
    dx /= d_len
    dy /= d_len
    dz /= d_len

    right_len = math.sqrt(dy * dy + dx * dx)
    if right_len < 1e-4:
        rx, ry, rz = 1.0, 0.0, 0.0
    else:
        rx = -dy / right_len
        ry = dx / right_len
        rz = 0.0

    ux = dy * rz - dz * ry
    uy = dz * rx - dx * rz
    uz = dx * ry - dy * rx
    u_len = math.sqrt(ux * ux + uy * uy + uz * uz)
    if u_len < 1e-6:
        ux, uy, uz = 0.0, 1.0, 0.0
    else:
        ux /= u_len
        uy /= u_len
        uz /= u_len

    half_hfov = math.atan(SENSOR_WIDTH_MM / (2.0 * focal_length))
    half_vfov = math.atan(SENSOR_HEIGHT_MM / (2.0 * focal_length))

    ground_points = []

    for sh, sv in [(-1, -1), (1, -1), (-1, 1), (1, 1)]:
        ray_dx = dx + math.tan(half_hfov) * sh * rx + math.tan(half_vfov) * sv * ux
        ray_dy = dy + math.tan(half_hfov) * sh * ry + math.tan(half_vfov) * sv * uy
        ray_dz = dz + math.tan(half_hfov) * sh * rz + math.tan(half_vfov) * sv * uz

        if ray_dz < -1e-6:
            t = -cam_z / ray_dz
            if t > 0:
                gx = cam_x + ray_dx * t
                gy = cam_y + ray_dy * t
                gx = max(WAREHOUSE_INTERIOR_X[0], min(WAREHOUSE_INTERIOR_X[1], gx))
                gy = max(WAREHOUSE_INTERIOR_Y[0], min(WAREHOUSE_INTERIOR_Y[1], gy))
                ground_points.append((gx, gy))

    if len(ground_points) < 2:
        fallback_radius = 3.0
        cx = cam_x + dx * max(cam_z, 1.0)
        cy = cam_y + dy * max(cam_z, 1.0)
        ground_points = [
            (cx - fallback_radius, cy - fallback_radius),
            (cx + fallback_radius, cy - fallback_radius),
            (cx - fallback_radius, cy + fallback_radius),
            (cx + fallback_radius, cy + fallback_radius),
        ]
        print("[CAMERA] Too few ground intersections, using fallback region around camera projection")

    min_x = min(p[0] for p in ground_points)
    max_x = max(p[0] for p in ground_points)
    min_y = min(p[1] for p in ground_points)
    max_y = max(p[1] for p in ground_points)

    span_x = max(max_x - min_x, MIN_VISIBLE_SIZE)
    span_y = max(max_y - min_y, MIN_VISIBLE_SIZE)
    min_x += span_x * margin_fraction / 2.0
    max_x -= span_x * margin_fraction / 2.0
    min_y += span_y * margin_fraction / 2.0
    max_y -= span_y * margin_fraction / 2.0

    if max_x - min_x < MIN_VISIBLE_SIZE:
        cx = (min_x + max_x) / 2.0
        min_x = cx - MIN_VISIBLE_SIZE / 2.0
        max_x = cx + MIN_VISIBLE_SIZE / 2.0
    if max_y - min_y < MIN_VISIBLE_SIZE:
        cy = (min_y + max_y) / 2.0
        min_y = cy - MIN_VISIBLE_SIZE / 2.0
        max_y = cy + MIN_VISIBLE_SIZE / 2.0

    wh_min_x = WAREHOUSE_INTERIOR_X[0] + INTERIOR_MARGIN
    wh_max_x = WAREHOUSE_INTERIOR_X[1] - INTERIOR_MARGIN
    wh_min_y = WAREHOUSE_INTERIOR_Y[0] + INTERIOR_MARGIN
    wh_max_y = WAREHOUSE_INTERIOR_Y[1] - INTERIOR_MARGIN
    min_x = max(min_x, wh_min_x)
    max_x = min(max_x, wh_max_x)
    min_y = max(min_y, wh_min_y)
    max_y = min(max_y, wh_max_y)

    print(f"[CAMERA] Ground visible area: x=[{min_x:.2f}, {max_x:.2f}] y=[{min_y:.2f}, {max_y:.2f}]")
    return (min_x, max_x, min_y, max_y)


def fit_camera_to_entities(cam_pos, look_at, entity_positions, focal_length=14.0, margin=0.85):
    if not entity_positions:
        return cam_pos, focal_length

    cam_x, cam_y, cam_z = cam_pos
    la_x, la_y, la_z = look_at

    dx = la_x - cam_x
    dy = la_y - cam_y
    dz = la_z - cam_z
    d_len = math.sqrt(dx*dx + dy*dy + dz*dz)
    if d_len < 1e-6:
        return cam_pos, focal_length
    fx, fy, fz = dx/d_len, dy/d_len, dz/d_len

    right_len = math.sqrt(fy*fy + fx*fx)
    if right_len < 1e-4:
        rx, ry, rz = 1.0, 0.0, 0.0
    else:
        rx = -fy / right_len
        ry =  fx / right_len
        rz =  0.0

    ux = fy*rz - fz*ry
    uy = fz*rx - fx*rz
    uz = fx*ry - fy*rx
    u_len = math.sqrt(ux*ux + uy*uy + uz*uz)
    if u_len < 1e-6:
        ux, uy, uz = 0.0, 1.0, 0.0
    else:
        ux /= u_len; uy /= u_len; uz /= u_len

    def get_tan_fovs(fl):
        hf = math.tan(math.atan(SENSOR_WIDTH_MM  / (2.0 * fl))) * margin
        vf = math.tan(math.atan(SENSOR_HEIGHT_MM / (2.0 * fl))) * margin
        return hf, vf

    tan_hfov, tan_vfov = get_tan_fovs(focal_length)

    max_delta = 0.0
    min_depth = 0.5

    for ex, ey in entity_positions:
        ex_rel = ex - cam_x
        ey_rel = ey - cam_y
        ez_rel = 0.0 - cam_z

        depth      = ex_rel*fx + ey_rel*fy + ez_rel*fz
        right_proj = ex_rel*rx + ey_rel*ry + ez_rel*rz
        up_proj    = ex_rel*ux + ey_rel*uy + ez_rel*uz

        entity_delta = max(0.0, min_depth - depth)
        if tan_hfov > 0:
            entity_delta = max(entity_delta, abs(right_proj) / tan_hfov - depth)
        if tan_vfov > 0:
            entity_delta = max(entity_delta, abs(up_proj)    / tan_vfov - depth)

        max_delta = max(max_delta, entity_delta)

    if max_delta < 0.05:
        return cam_pos, focal_length

    proposed_z = cam_z - fz * max_delta

    if proposed_z > CEILING_Z:
        limited_delta = (CEILING_Z - cam_z) / (-fz) if abs(fz) > 1e-4 else max_delta
        limited_delta = max(0.0, min(limited_delta, max_delta))

        cam_x -= fx * limited_delta
        cam_y -= fy * limited_delta
        cam_z -= fz * limited_delta

        current_dist = d_len + limited_delta
        needed_dist = d_len + max_delta
        zoom_factor = current_dist / needed_dist
        focal_length = max(8.0, focal_length * zoom_factor)

        print(f"[CAMERA] fit_camera_to_entities: Hit ceiling at {CEILING_Z}m. Zooming out to {focal_length:.1f}mm")
    else:
        cam_x -= fx * max_delta
        cam_y -= fy * max_delta
        cam_z -= fz * max_delta

    new_cam_pos = clamp_to_warehouse(cam_x, cam_y, cam_z)
    new_cam_pos = (new_cam_pos[0], new_cam_pos[1], max(new_cam_pos[2], MIN_INDOOR_HEIGHT))

    print(f"[CAMERA] fit_camera_to_entities: shifted {max_delta:.2f}m back → "
          f"({new_cam_pos[0]:.2f}, {new_cam_pos[1]:.2f}, {new_cam_pos[2]:.2f}) fl={focal_length:.1f}mm")
    return new_cam_pos, focal_length
