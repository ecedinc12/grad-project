"""RAG-augmented scene generation.

Retrieves relevant Isaac Sim documentation and project context,
then augments the LLM prompt with that context before calling
the existing Generator pipeline.
"""

import os
import sys
import argparse
from typing import List, Optional

from rag_system.vector_store import VectorStore


class RAGGenerationError(Exception):
    """Raised when RAG generation fails."""


class MissingAPIKeyError(RAGGenerationError):
    """Raised when GEMINI_API_KEY is not set."""


class SchemaValidationError(RAGGenerationError):
    """Raised when the LLM output fails schema validation."""


def retrieve_context(
    query: str,
    n_results: int = 8,
    doc_type: Optional[str] = None,
    max_context_tokens: int = 6000,
    vector_store: Optional[VectorStore] = None,
) -> str:
    """Retrieve relevant context from the vector store.

    Args:
        query: The user prompt / search query.
        n_results: Number of chunks to retrieve.
        doc_type: Optional filter for doc type.
        max_context_tokens: Approximate max tokens of context to include.
        vector_store: Optional pre-initialized VectorStore instance.

    Returns:
        Formatted context string for RAG augmentation.
    """
    store = vector_store or VectorStore()
    if store.count() == 0:
        print("[WARN] Vector store is empty. Run `python -m rag_system.build_index` first.")
        return ""

    results = store.query(query_text=query, n_results=n_results, doc_type=doc_type)

    if not results:
        return ""

    context_parts = []
    estimated_tokens = 0

    for i, r in enumerate(results):
        text = r["text"]
        meta = r["metadata"]
        source = meta.get("source", "unknown")
        title = meta.get("title", "unknown")
        doc_type_val = meta.get("type", "unknown")
        distance = r.get("distance")
        relevance = f" (distance: {distance:.3f})" if distance is not None else ""

        header = f"--- Context [{i+1}] from: {title} ({doc_type_val}){relevance} ---\nSource: {source}\n"
        entry = header + text + "\n"
        entry_tokens = len(entry) // 4

        if estimated_tokens + entry_tokens > max_context_tokens:
            context_parts.append(entry[: (max_context_tokens - estimated_tokens) * 4])
            break

        context_parts.append(entry)
        estimated_tokens += entry_tokens

    return "\n".join(context_parts)


def build_rag_prompt(user_prompt: str, context: str) -> str:
    """Build the RAG-augmented system prompt for scene generation.

    Combines the original system prompt from generator.py with
    retrieved Isaac Sim documentation context.
    """
    context_section = ""
    if context:
        context_section = f"""
RETRIEVED ISAAC SIM DOCUMENTATION CONTEXT:
The following documentation snippets were retrieved based on the user's prompt.
Use this context to inform your understanding of Isaac Sim 5.1+ APIs, Replicator,
camera setup, lighting, semantics, and synthetic data generation.

{context}

END OF RETRIEVED CONTEXT.
"""

    system_prompt = f"""{context_section}
You are an expert industrial safety simulation configurator using NVIDIA Isaac Sim 5.1+.
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
- Each HazardZone needs: name (snake_case identifier), bounds_min/bounds_max (x,y in meters, within warehouse bounds +/-6m x, +/-6m y), and danger_level.
- danger_level: "warning" for caution areas, "restricted" for authorized-only zones, "critical" for lethal hazards (e.g., active forklift aisle).
- Common zone placements:
  * "forklift aisle" / "vehicle path" -> bounds_min=(-5, -2), bounds_max=(5, 2), danger_level="critical"
  * "loading dock" -> bounds_min=(-5, -6), bounds_max=(5, -4), danger_level="restricted"
  * "storage area" / "racking zone" -> bounds_min=(-6, 3), bounds_max=(6, 7), danger_level="warning"
  * "inspection point" -> small area bounds_min=(-1, -1), bounds_max=(1, 1), danger_level="warning"
- Also create a zone entity for each hazard_zone with asset_id="cone" (to mark the zone visually with cones).

WORKER BEHAVIOR RULES:
- Generate one WorkerBehavior entry per worker entity in the scene, in the same order they appear in entities.
- Assign worker_id sequentially: "worker_01", "worker_02", etc.
- Each WorkerBehavior must have at least 3 commands.
- GoTo commands: x and y MUST be within [-6, 6] (warehouse bounds). Set rotation to a sensible facing direction (degrees, 0-360). z is always 0.0 (set x and y only; the field named z in the command file is always 0.0).
- Idle/LookAround commands: set duration in seconds (1-5 s). Do NOT set x, y, or rotation for these.
- Tailor behavior to the scenario:
  * "danger zone" or "forklift" -> worker GoTo path crosses the forklift aisle (y near 0, x sweeping across)
  * "patrol" -> 4+ GoTo waypoints forming a loop around the warehouse perimeter
  * "inspection" -> alternating short GoTo hops (1-2 m apart) and LookAround pauses
  * Default (no scenario) -> mix of GoTo waypoints and Idle breaks covering different quadrants
"""
    return system_prompt


def generate_with_rag(
    prompt: str,
    output_path: str = "configs/current_scene.json",
    n_context: int = 8,
    doc_type: Optional[str] = None,
):
    """Generate a SceneConfig using RAG-augmented prompts.

    Retrieves relevant Isaac Sim documentation, builds an augmented system prompt,
    then calls the existing generator pipeline.
    """
    import instructor
    from openai import OpenAI
    from pydantic import ValidationError
    from llm_pipeline.schemas import SceneConfig

    print(f"[RAG] Retrieving context for: '{prompt[:80]}...'")
    context = retrieve_context(query=prompt, n_results=n_context, doc_type=doc_type)

    if context:
        print(f"[RAG] Retrieved {len(context)} chars of context.")
    else:
        print("[RAG] No context retrieved, proceeding without RAG augmentation.")

    system_prompt = build_rag_prompt(prompt, context)

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise MissingAPIKeyError("GEMINI_API_KEY environment variable is not set.")

    base_url = os.environ.get("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")

    client = instructor.from_openai(
        OpenAI(api_key=api_key, base_url=base_url),
        mode=instructor.Mode.JSON,
    )

    model = os.environ.get("LLM_MODEL", "gemini-2.5-flash")

    print(f"[RAG] Generating SceneConfig with model={model}...")

    try:
        config: SceneConfig = client.chat.completions.create(
            model=model,
            response_model=SceneConfig,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
        )

        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        with open(output_path, "w") as f:
            f.write(config.model_dump_json(indent=4))
        print(f"[RAG] Successfully saved SceneConfig to {output_path}")

    except ValidationError as e:
        raise SchemaValidationError(f"Schema validation error: {e}") from e
    except Exception as e:
        raise RAGGenerationError(f"Error during generation: {e}") from e


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate SceneConfig with RAG augmentation")
    parser.add_argument("--prompt", type=str, required=True, help="User prompt describing the scene")
    parser.add_argument("--output", type=str, default="configs/current_scene.json", help="Output path for JSON config")
    parser.add_argument("--n-context", type=int, default=8, help="Number of context chunks to retrieve")
    parser.add_argument("--doc-type", type=str, default=None, help="Filter context by doc type")
    args = parser.parse_args()

    try:
        generate_with_rag(
            prompt=args.prompt,
            output_path=args.output,
            n_context=args.n_context,
            doc_type=args.doc_type,
        )
    except MissingAPIKeyError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except RAGGenerationError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)