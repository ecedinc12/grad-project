import os
import sys
import json
import argparse
import instructor
from openai import OpenAI
from pydantic import ValidationError
from schemas import SceneConfig, Entity, PPEState, WorkerBehavior, BehaviorCommand, ClutterZone, LayoutParams

LAYOUTS_PATH = os.path.join(os.path.dirname(__file__), "..", "assets", "layouts.json")
_LAYOUTS_DESCRIPTION = ""
try:
    with open(LAYOUTS_PATH) as f:
        _layouts_data = json.load(f)
    _lines = []
    for _name, _cfg in _layouts_data.items():
        _kw = ", ".join(_cfg.get("keywords", []))
        _lines.append(f"- {_name}: {_cfg['description']} (keywords: {_kw})")
    _LAYOUTS_DESCRIPTION = "\n".join(_lines)
except Exception:
    _LAYOUTS_DESCRIPTION = (
        "- standard_warehouse: Default 5-row warehouse with moderate aisles and scattered clutter.\n"
        "- narrow_aisle: Cramped high-density storage with tight passages.\n"
        "- open_floor: Sparse layout with perimeter racks and wide open areas.\n"
        "- cross_dock: L-shaped rack arrangement with wide truck corridor.\n"
        "- cold_storage: Dense grid layout with heavy barrel clustering.\n"
        "- loading_dock: Minimal racks, heavy pallet staging, truck bay area.\n"
        "- maintenance_bay: No racks, open service area with cone-marked safety zones.\n"
        "- storage_yard: 4 rack clusters with wide lanes, outdoor-style yard."
    )

def generate_scene_config(prompt: str, output_path: str):
    # Retrieve the API key from environment variable
    # Use Gemini's OpenAI compatible endpoint
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY environment variable is not set.", file=sys.stderr)
        print("Please export your key: export GEMINI_API_KEY='your_api_key_here'", file=sys.stderr)
        sys.exit(1)

    base_url = os.environ.get("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")

    # Patch the OpenAI client with Instructor using JSON mode for Gemini compatibility
    client = instructor.from_openai(
        OpenAI(api_key=api_key, base_url=base_url),
        mode=instructor.Mode.JSON
    )
    
    model = os.environ.get("LLM_MODEL", "gemini-2.5-flash") # Or "gemini-2.5-flash-lite" if that is the exact model name
    
    system_prompt = """
    You are an expert industrial safety simulation configurator.
    Your job is to extract entities, PPE states, hazard zones, scene configuration, and worker behavior sequences from user prompts.

    AVAILABLE LAYOUT PRESETS:
""" + _LAYOUTS_DESCRIPTION + """

    LAYOUT SELECTION RULES:
    - If the user mentions a specific layout by name or description, choose the matching preset.
    - If the user specifies custom dimensions (e.g. "10 rack rows", "3m aisles"), set layout="custom"
      and populate layout_params with the exact values.
    - You can also use a preset as a base and override specific params via layout_params.
    - If no layout is implied, default to "standard_warehouse".
    - Match keywords: "cramped/tight/dense" → narrow_aisle, "open/spacious" → open_floor,
      "loading/truck/shipping" → loading_dock, "maintenance/repair" → maintenance_bay,
      "yard/outdoor/container" → storage_yard, "cold/freezer" → cold_storage,
      "cross-dock/transfer" → cross_dock.

    LAYOUT PARAMS RULES (only set layout_params if overriding preset defaults or using layout="custom"):
    - rack_rows: number of rack rows (1-12). Default 5.
    - rack_cols: number of rack columns (1-3). Default 1.
    - aisle_width: distance between rack rows in meters (1.0-5.0). Default 2.0.
    - bounds_min/bounds_max: overall layout footprint in meters. Must fit within ±7m X, ±7m Y.
    - clutter_density: "low" (0-5 props), "medium" (6-12 props), "high" (13-20 props).
    - clutter_zones: optional list of area-specific clutter overrides.
      Each zone needs: area name, bounds_min, bounds_max, density, and types list.
      Types must be from: "box", "barrel", "cone", "pallet".
    - pallet_rows/pallet_cols: pallet staging grid size. Default 2x1.

    RULES:
    - ONLY include entities the user explicitly mentions. Do NOT add background props, vehicles, or workers that were not requested.
    - Default PPEState: Workers default to hardhat=True and vest=True UNLESS the user explicitly states they are missing.
    - Entities types: 'worker', 'vehicle', 'zone'.
    - The asset_id field MUST be exactly one of: 'worker', 'forklift', 'pallet', 'rack', 'box', 'barrel', 'cone'. Never invent an asset_id. If an entity does not match, omit it.
    - Set logical anchor_zones if mentioned (e.g., 'loading dock', 'aisle 3').
    - IMPORTANT: Vehicles (forklifts, carts) MUST have anchor_zone set to the zone they operate in. For example, a forklift in "forklift_aisle" should have anchor_zone="forklift_aisle". This ensures the vehicle spawns in the correct location instead of randomly.
    - camera_angles values MUST each be exactly one of: 'overhead', 'high_angle', 'eye_level', 'low_angle'. Choose based on the user's description; default to ['eye_level'] if unspecified.
    - camera_mode MUST be 'indoor' by default (fixed surveillance position). However, if the user explicitly asks for "multiple angles", "different points of view", or "orbit", you MUST set it to 'orbit'.
    - camera_position is optional. If omitted, it is auto-derived from worker and hazard zone positions. Only set it if the user specifies an exact viewpoint.
    - focal_length is optional. Default is 14.0 (wide indoor FOV ~90deg). Use 10-12 to guarantee wide shots that include all described assets, 18-24 for narrower focus on specific areas. Do NOT set it unless the user specifies a field of view preference or requests a scene with many distributed assets.
    - lighting_conditions MUST be exactly one of: 'daylight', 'overcast', 'dusk', 'night'. Choose based on the user's description; default to 'daylight' if unspecified.

    HAZARD ZONE RULES:
    - When the user mentions danger zones, restricted areas, or hazard areas, create HazardZone entries.
    - Each HazardZone needs: name (snake_case identifier), bounds_min/bounds_max (x,y in meters, within warehouse bounds ±6m x, ±6m y), and danger_level.
    - danger_level: "warning" for caution areas, "restricted" for authorized-only zones, "critical" for lethal hazards (e.g., active forklift aisle).
    - Common zone placements:
      * "forklift aisle" / "vehicle path" → bounds_min=(-5, -2), bounds_max=(5, 2), danger_level="critical"
      * "loading dock" → bounds_min=(-5, -6), bounds_max=(5, -4), danger_level="restricted"
      * "storage area" / "racking zone" → bounds_min=(-6, 3), bounds_max=(6, 7), danger_level="warning"
      * "inspection point" → small area bounds_min=(-1, -1), bounds_max=(1, 1), danger_level="warning"
    - Also create a zone entity for each hazard_zone with asset_id="cone" (to mark the zone visually with cones).

    WORKER BEHAVIOR RULES:
    - Generate one WorkerBehavior entry per worker entity in the scene, in the same order they appear in entities.
    - Assign worker_id sequentially: "worker_01", "worker_02", etc.
    - Each WorkerBehavior must have at least 3 commands.
    - GoTo commands: x and y MUST be within [-6, 6] (warehouse bounds). Set rotation to a sensible facing direction (degrees, 0–360). z is always 0.0 (set x and y only; the field named z in the command file is always 0.0).
    - Idle/LookAround commands: set duration in seconds (1–5 s). Do NOT set x, y, or rotation for these.
    - Tailor behavior to the scenario:
      * "danger zone" or "forklift" → worker GoTo path crosses the forklift aisle (y near 0, x sweeping across)
      * "patrol" → 4+ GoTo waypoints forming a loop around the warehouse perimeter
      * "inspection" → alternating short GoTo hops (1–2 m apart) and LookAround pauses
      * Default (no scenario) → mix of GoTo waypoints and Idle breaks covering different quadrants

    VEHICLE BEHAVIOR RULES:
    - Generate one VehicleBehavior entry per vehicle entity (e.g. forklift) IF movement is requested or implied.
    - Assign vehicle_id matching the vehicle's asset_id (e.g. "forklift", "forklift_01"). Note that the backend spawns multiple vehicles as asset_id_01, asset_id_02, etc. If only 1, use "forklift_01".
    - Use GoTo commands for movement waypoints. Set x and y to specify paths.
    - Use Idle commands for stops.
    - Ensure paths stay within their operating zones or logical warehouse aisles.
    """

    print(f"Generating configuration for prompt: '{prompt}'...")
    
    try:
        config: SceneConfig = client.chat.completions.create(
            model=model,
            response_model=SceneConfig,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0
        )
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        # Save validated output
        with open(output_path, "w") as f:
            f.write(config.model_dump_json(indent=4))
        print(f"Successfully saved SceneConfig to {output_path}")
        
    except ValidationError as e:
        print(f"Schema validation error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error during generation: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate SceneConfig JSON from text prompt.")
    parser.add_argument("--prompt", type=str, required=True, help="User prompt describing the scene.")
    parser.add_argument("--output", type=str, default="configs/current_scene.json", help="Output path for the JSON config.")
    
    args = parser.parse_args()
    generate_scene_config(args.prompt, args.output)
