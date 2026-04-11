"""Interactive RAG query CLI.

Usage:
    python -m rag_system.query "How to set up BasicWriter in Isaac Sim?"
    python -m rag_system.query --interactive
    python -m rag_system.query --generate "spawn a forklift near a worker"
"""

import argparse
import sys

from rag_system.vector_store import VectorStore
from rag_system.generation import retrieve_context, build_rag_prompt, generate_with_rag


def main():
    parser = argparse.ArgumentParser(description="Query the Isaac Sim RAG system")
    parser.add_argument("query", type=str, nargs="?", default=None, help="Search query")
    parser.add_argument("--interactive", "-i", action="store_true", help="Interactive query mode")
    parser.add_argument("--generate", "-g", type=str, default=None,
                        help="Generate SceneConfig using RAG augmentation")
    parser.add_argument("--output", "-o", type=str, default="configs/current_scene.json",
                        help="Output path for generated config")
    parser.add_argument("--n-results", "-n", type=int, default=5, help="Number of results")
    parser.add_argument("--doc-type", "-t", type=str, default=None,
                        help="Filter by doc type (isaac_sim_docs, project_source, project_config)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show full chunk text")
    args = parser.parse_args()

    if args.generate:
        generate_with_rag(
            prompt=args.generate,
            output_path=args.output,
            n_context=args.n_results,
            doc_type=args.doc_type,
        )
        return

    if args.interactive:
        store = VectorStore()
        print(f"Isaac Sim RAG Query ({store.count()} chunks loaded)")
        print(f"Type 'quit' or Ctrl+D to exit.\n")
        while True:
            try:
                query = input("query> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nGoodbye!")
                break
            if query.lower() in ("quit", "exit", "q"):
                break
            if not query:
                continue

            results = store.query(query_text=query, n_results=args.n_results, doc_type=args.doc_type)
            if not results:
                print("No results found.\n")
                continue
            for i, r in enumerate(results):
                meta = r["metadata"]
                dist = r.get("distance")
                print(f"\n--- Result {i+1} (dist={dist:.4f}) ---")
                print(f"  Source: {meta.get('source', '?')}")
                print(f"  Title:  {meta.get('title', '?')}")
                print(f"  Type:   {meta.get('type', '?')}")
                if args.verbose:
                    print(f"\n{r['text'][:2000]}")
                else:
                    print(f"\n{r['text'][:500]}...")
            print()

    elif args.query:
        context = retrieve_context(
            query=args.query,
            n_results=args.n_results,
            doc_type=args.doc_type,
        )
        print(context if context else "No results found.")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()