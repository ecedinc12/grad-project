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
    # This allows flexibility to use Groq, OpenAI, or other providers via OpenAI compatible endpoint
    api_key = os.environ.get("OPENAI_API_KEY", "dummy-key")
    base_url = os.environ.get("OPENAI_BASE_URL") # e.g., "https://api.groq.com/openai/v1"

    # Patch the OpenAI client with Instructor
    client = instructor.from_openai(OpenAI(
        api_key=api_key,
        base_url=base_url
    ))
    
    model = os.environ.get("LLM_MODEL", "gpt-3.5-turbo") # Can be overridden (e.g., "mixtral-8x7b-32768" for Groq)
    
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
    parser.add_argument("--output", type=str, default="/workspace/configs/current_scene.json", help="Output path for the JSON config.")
    
    args = parser.parse_args()
    generate_scene_config(args.prompt, args.output)
