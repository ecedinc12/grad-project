import omni.replicator.core as rep

LIGHTING_MAP = {
    "daylight": {"intensity": 1000, "color": (1.0,  0.98, 0.95)},
    "overcast": {"intensity":  500, "color": (0.85, 0.88, 0.95)},
    "dusk":     {"intensity":  200, "color": (0.35, 0.40, 0.65)},
    "night":    {"intensity":   50, "color": (0.20, 0.25, 0.40)},
}

_CEILING_LAMP_XY = [(-4, -4), (0, -4), (4, -4), (-4, 0), (0, 0), (4, 0), (-4, 4), (0, 4), (4, 4)]
_CEILING_Z = 5.5

def setup_camera_and_lighting(config):
    condition = config.get("lighting_conditions", "daylight")
    params = LIGHTING_MAP.get(condition, LIGHTING_MAP["daylight"])
    print(f"[INFO] lighting_conditions={condition!r}  →  intensity={params['intensity']}, color={params['color']}")
    rep.create.light(light_type="Dome", intensity=params["intensity"], color=params["color"])

    if condition == "dusk":
        rep.create.light(
            light_type="Distant",
            intensity=800,
            color=(1.0, 0.55, 0.20),
        )
        for x, y in _CEILING_LAMP_XY:
            rep.create.light(
                light_type="Sphere",
                intensity=400,
                color=(1.0, 0.85, 0.60),
                position=(x, y, _CEILING_Z),
                scale=0.15,
            )

    if condition == "night":
        for x, y in _CEILING_LAMP_XY:
            rep.create.light(
                light_type="Sphere",
                intensity=600,
                color=(1.0, 0.97, 0.88),
                position=(x, y, _CEILING_Z),
                scale=0.15,
            )

    camera = rep.create.camera(position=(0, 5, 10), look_at=(0, 0, 0))
    render_product = rep.create.render_product(camera, (1024, 1024))
    return camera, render_product
