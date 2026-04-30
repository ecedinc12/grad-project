"""
Camera and Lighting Setup

Creates dome/distant/sphere lights based on lighting condition and
returns a camera + render product for Replicator SDG.
"""

import random

import omni.replicator.core as rep

# Dome = ambient skylight only. Was 800 — too flat/washed. Cut hard so directional
# sun + ceiling banks read on the floor.
LIGHTING_MAP = {
    "daylight": {"intensity": 300, "color": (0.85, 0.90, 1.0)},
    "overcast": {"intensity": 380, "color": (0.88, 0.90, 0.95)},
    "dusk":     {"intensity": 120, "color": (0.35, 0.40, 0.65)},
    "night":    {"intensity":  25, "color": (0.20, 0.25, 0.40)},
}

_CEILING_LAMP_XY = [(-4, -4), (0, -4), (4, -4), (-4, 0), (0, 0), (4, 0), (-4, 4), (0, 4), (4, 4)]
_CEILING_Z = 5.5

# Fluorescent fixture footprint (long thin troffer). Rect light normal is -Z by
# default, so no rotation needed at ceiling Z.
_FIXTURE_W = 1.2
_FIXTURE_D = 0.3

# Real fluorescent banks drift in age/temperature. Per-lamp jitter breaks the
# "every fixture identical" CG tell.
_LAMP_RNG = random.Random(7)


def _ceiling_bank(intensity_base, color_base, jitter=True):
    """Spawn the 9 ceiling fixtures as Rect lights with optional per-lamp jitter."""
    for x, y in _CEILING_LAMP_XY:
        if jitter:
            i_mul = _LAMP_RNG.uniform(0.78, 1.15)
            # Color temperature drift: some lamps warmer, some cooler.
            warm = _LAMP_RNG.uniform(-0.04, 0.04)
            color = (
                max(0.0, min(1.0, color_base[0] + warm)),
                color_base[1],
                max(0.0, min(1.0, color_base[2] - warm)),
            )
        else:
            i_mul = 1.0
            color = color_base
        rep.create.light(
            light_type="Rect",
            intensity=intensity_base * i_mul,
            color=color,
            position=(x, y, _CEILING_Z),
            scale=(_FIXTURE_W, _FIXTURE_D, 1.0),
        )


def setup_camera_and_lighting(config):
    """Create lights based on lighting condition and return (camera, render_product)."""
    condition = config.get("lighting_conditions", "daylight")
    params = LIGHTING_MAP.get(condition, LIGHTING_MAP["daylight"])
    print(f"[INFO] lighting_conditions={condition!r}  ->  intensity={params['intensity']}, color={params['color']}")
    rep.create.light(light_type="Dome", intensity=params["intensity"], color=params["color"])

    if condition == "daylight":
        # Sun: angled, not straight down. Gives shelves directional shadows.
        rep.create.light(
            light_type="Distant",
            intensity=3500,
            color=(1.0, 0.95, 0.85),
            rotation=(-55, 25, 0),
        )
        _ceiling_bank(intensity_base=6500, color_base=(1.0, 0.98, 0.92))

    if condition == "overcast":
        rep.create.light(
            light_type="Distant",
            intensity=220,
            color=(0.95, 0.95, 0.95),
            rotation=(-70, 0, 0),
        )
        # Overcast = interior banks dominate. Slightly cooler.
        _ceiling_bank(intensity_base=5500, color_base=(0.98, 0.99, 1.0))

    if condition == "dusk":
        rep.create.light(
            light_type="Distant",
            intensity=900,
            color=(1.0, 0.55, 0.20),
            rotation=(-15, 30, 0),
        )
        _ceiling_bank(intensity_base=7500, color_base=(1.0, 0.85, 0.60))

    if condition == "night":
        _ceiling_bank(intensity_base=9000, color_base=(1.0, 0.97, 0.88))

    focal_length = config.get("focal_length") or 14.0
    camera = rep.create.camera(position=(0, 0, 3), look_at=(0, 0, 1), focal_length=focal_length)
    print(f"[INFO] Camera focal_length={focal_length}mm")
    width = config.get("resolution_width", 1920)
    height = config.get("resolution_height", 1080)
    render_product = rep.create.render_product(camera, (width, height))
    return camera, render_product
