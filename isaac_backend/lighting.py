"""
Lighting Setup

Creates dome/distant/sphere lights based on lighting condition and
delegates camera + render product creation to camera.py.
"""

import omni.replicator.core as rep
from isaac_backend.camera import create_camera_and_render_product

LIGHTING_MAP = {
    "daylight": {"intensity": 800, "color": (0.85, 0.90, 1.0)},
    "overcast": {"intensity": 450, "color": (0.88, 0.90, 0.95)},
    "dusk":     {"intensity": 200, "color": (0.35, 0.40, 0.65)},
    "night":    {"intensity":  50, "color": (0.20, 0.25, 0.40)},
}

_CEILING_LAMP_XY = [(-4, -4), (0, -4), (4, -4), (-4, 0), (0, 0), (4, 0), (-4, 4), (0, 4), (4, 4)]
_CEILING_Z = 5.5


def setup_camera_and_lighting(config):
    """Create lights based on lighting condition and return (camera, render_product)."""
    condition = config.get("lighting_conditions", "daylight")
    params = LIGHTING_MAP.get(condition, LIGHTING_MAP["daylight"])
    print(f"[INFO] lighting_conditions={condition!r}  ->  intensity={params['intensity']}, color={params['color']}")
    rep.create.light(light_type="Dome", intensity=params["intensity"], color=params["color"])

    if condition == "daylight":
        rep.create.light(
            light_type="Distant",
            intensity=2500,
            color=(1.0, 0.95, 0.85),
        )

    if condition == "overcast":
        rep.create.light(
            light_type="Distant",
            intensity=150,
            color=(0.95, 0.95, 0.95),
        )

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

    camera, render_product = create_camera_and_render_product(config)
    return camera, render_product
