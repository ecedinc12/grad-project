import os
import sys
import json
import argparse
import instructor
from openai import OpenAI
from pydantic import ValidationError
from schemas import SceneConfig, Entity, PPEState, WorkerBehavior, BehaviorCommand

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

    RULES:
    - ONLY include entities the user explicitly mentions. Do NOT add background props, vehicles, or workers that were not requested.
    - Default PPEState: Workers default to hardhat=True and vest=True UNLESS the user explicitly states they are missing.
    - Entities types: 'worker', 'vehicle', 'zone'.
    - The asset_id field MUST be exactly one of: 'worker', 'forklift', 'pallet', 'rack', 'box', 'barrel', 'cone'. Never invent an asset_id. If an entity does not match, omit it.
    - Set logical anchor_zones if mentioned (e.g., 'loading dock', 'aisle 3').
    - camera_angles values MUST each be exactly one of: 'overhead', 'high_angle', 'eye_level', 'low_angle'. Choose based on the user's description; default to ['eye_level'] if unspecified.
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
