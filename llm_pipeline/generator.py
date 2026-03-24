import os
import sys
import json
import argparse
import instructor
from openai import OpenAI
from pydantic import ValidationError
from schemas import SceneConfig, Entity, PPEState

def generate_scene_config(prompt: str, output_path: str):
    # Retrieve the API key from environment variable
    # Use Gemini's OpenAI compatible endpoint
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY environment variable is not set.", file=sys.stderr)
        print("Please export your key: export GEMINI_API_KEY='your_api_key_here'", file=sys.stderr)
        sys.exit(1)

    base_url = os.environ.get("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")

    # Patch the OpenAI client with Instructor
    client = instructor.from_openai(OpenAI(
        api_key=api_key,
        base_url=base_url
    ))
    
    model = os.environ.get("LLM_MODEL", "gemini-2.5-flash") # Or "gemini-2.5-flash-lite" if that is the exact model name
    
    system_prompt = """
    You are an expert industrial safety simulation configurator.
    Your job is to extract entities, PPE states, and scene configuration from user prompts.
    
    RULES:
    - Default PPEState: Workers default to hardhat=True and vest=True UNLESS the user explicitly states they are missing.
    - Entities types: 'worker', 'vehicle', 'zone'.
    - Use common asset_id names like 'forklift', 'worker', 'pallet', 'rack', etc.
    - Set logical anchor_zones if mentioned (e.g., 'loading dock', 'aisle 3').
    - If camera angles or lighting are not specified, make reasonable default choices.
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
