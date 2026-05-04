"""PBR material library for procedural layout primitives.

Replaces flat `CreateDisplayColorAttr` calls with bound `UsdPreviewSurface`
materials carrying roughness / metallic / opacity values. Each call site
still passes its existing RGB tuple as the diffuse albedo, so palette
choices made in props.py / realism.py stay intact while RTX picks up the
material response.

UsdPreviewSurface is used (not OmniPBR/MDL) for portability — RTX promotes
it automatically and there is no kit-side shader graph dependency.
"""

from pxr import UsdGeom, UsdShade, Sdf, Gf

# Class -> base shader parameters. Diffuse color stays per-instance.
MATERIAL_CLASSES = {
    "M_PaintedConcrete":   {"roughness": 0.88, "metallic": 0.0,  "opacity": 1.0},
    "M_AgedSteel":         {"roughness": 0.42, "metallic": 0.85, "opacity": 1.0},
    "M_YellowSafetyPaint": {"roughness": 0.58, "metallic": 0.0,  "opacity": 1.0},
    "M_PlasticMatte":      {"roughness": 0.55, "metallic": 0.0,  "opacity": 1.0},
    "M_PlasticGloss":      {"roughness": 0.18, "metallic": 0.0,  "opacity": 1.0},
    "M_Cardboard":         {"roughness": 0.82, "metallic": 0.0,  "opacity": 1.0},
    "M_Wood":              {"roughness": 0.72, "metallic": 0.0,  "opacity": 1.0},
    "M_StretchFilm":       {"roughness": 0.12, "metallic": 0.0,  "opacity": 0.40},
    "M_Rubber":            {"roughness": 0.88, "metallic": 0.0,  "opacity": 1.0},
    "M_PaintedWall":       {"roughness": 0.78, "metallic": 0.0,  "opacity": 1.0},
    "M_OilFilm":           {"roughness": 0.06, "metallic": 0.0,  "opacity": 0.88},
    "M_FabricMatte":       {"roughness": 0.92, "metallic": 0.0,  "opacity": 1.0},
    "M_Glass":             {"roughness": 0.05, "metallic": 0.0,  "opacity": 0.30},
    "M_Emissive":          {"roughness": 0.20, "metallic": 0.0,  "opacity": 1.0},
    "M_Default":           {"roughness": 0.65, "metallic": 0.0,  "opacity": 1.0},
}

# Cache: (class_name, color_int_tuple) -> UsdShade.Material
_material_cache = {}


def _color_tag(color):
    return f"{int(color[0] * 255):03d}_{int(color[1] * 255):03d}_{int(color[2] * 255):03d}"


def get_or_create_material(stage, class_name, color):
    """Fetch (or author) a UsdShade.Material under /World/Looks for the given
    material class + diffuse color. Reused across calls so same (class, color)
    pair shares one material prim."""
    spec = MATERIAL_CLASSES.get(class_name, MATERIAL_CLASSES["M_Default"])
    key = (class_name, int(color[0] * 255), int(color[1] * 255), int(color[2] * 255))
    cached = _material_cache.get(key)
    if cached is not None:
        return cached

    looks_path = "/World/Looks"
    if not stage.GetPrimAtPath(looks_path):
        UsdGeom.Scope.Define(stage, looks_path)

    mat_path = f"{looks_path}/{class_name}_{_color_tag(color)}"
    material = UsdShade.Material.Define(stage, mat_path)

    shader = UsdShade.Shader.Define(stage, f"{mat_path}/Shader")
    shader.CreateIdAttr("UsdPreviewSurface")
    shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*color))
    shader.CreateInput("roughness",    Sdf.ValueTypeNames.Float).Set(spec["roughness"])
    shader.CreateInput("metallic",     Sdf.ValueTypeNames.Float).Set(spec["metallic"])
    shader.CreateInput("opacity",      Sdf.ValueTypeNames.Float).Set(spec["opacity"])
    if class_name == "M_Emissive":
        shader.CreateInput("emissiveColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*color))

    material.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")
    _material_cache[key] = material
    return material


def bind_material(stage, prim_or_gprim, class_name, color):
    """Drop-in replacement for `gprim.CreateDisplayColorAttr([Gf.Vec3f(*c)])`.
    Binds a PBR material AND keeps displayColor as a non-RTX viewport fallback.

    Accepts either a Usd.Prim or any UsdGeom.Gprim subclass (Cube, Cylinder,
    Sphere, etc.) — same call signature as the displayColor flow it replaces.
    """
    if hasattr(prim_or_gprim, "GetPrim"):
        gprim = prim_or_gprim
        prim = prim_or_gprim.GetPrim()
    else:
        prim = prim_or_gprim
        gprim = UsdGeom.Gprim(prim)

    material = get_or_create_material(stage, class_name, color)
    UsdShade.MaterialBindingAPI(prim).Bind(material)

    # Keep displayColor as Hydra Storm / non-RTX fallback so previews still
    # show the intended albedo even without the shader graph.
    if gprim and gprim.GetPrim().IsValid():
        gprim.CreateDisplayColorAttr([Gf.Vec3f(*color)])


def reset_material_cache():
    """Clear the material cache. Call at the start of a new scene if the
    stage is rebuilt — material prims live on the stage, the cache holds
    stale handles otherwise."""
    _material_cache.clear()
