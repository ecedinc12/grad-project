"""CLI script to build the RAG vector index.

Usage:
    python -m rag_system.build_index [--project-root PATH] [--max-pages N] [--chunk-size N] [--reset]

Steps:
1. Fetch Isaac Sim 5.1 documentation from the web (or load cached)
2. Load project source files
3. Chunk all documents
4. Embed and store in ChromaDB
"""

import argparse
import json
import os
import sys
from pathlib import Path

from rag_system.loader import DATA_DIR, fetch_project_sources, crawl_docs, load_curated_knowledge_base
from rag_system.chunker import chunk_documents
from rag_system.vector_store import VectorStore


def build_index(
    project_root: str | None = None,
    max_pages: int = 40,
    chunk_size: int = 1200,
    chunk_overlap: int = 200,
    reset: bool = False,
    skip_crawl: bool = False,
):
    """Build the full RAG index pipeline."""
    if project_root is None:
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    print("=" * 60)
    print("RAG Index Builder for Isaac Sim Project")
    print("=" * 60)

    store = VectorStore()

    if reset:
        print("\n[1/5] Resetting vector store...")
        store.reset()

    all_documents = []

    # --- Load cached docs or crawl ---
    docs_cache_path = DATA_DIR / "isaac_sim_docs.json"
    if skip_crawl and docs_cache_path.exists():
        print("\n[1/5] Loading cached Isaac Sim docs...")
        from rag_system.loader import Document
        with open(docs_cache_path, "r") as f:
            cached = json.load(f)
        docs = [Document.from_dict(d) for d in cached]
        print(f"      Loaded {len(docs)} cached documents.")
    else:
        print(f"\n[1/5] Crawling Isaac Sim 5.1 docs (max {max_pages} pages)...")
        docs = crawl_docs(max_pages=max_pages)
        print(f"      Fetched {len(docs)} documentation pages.")

        os.makedirs(DATA_DIR, exist_ok=True)
        with open(docs_cache_path, "w") as f:
            json.dump([d.to_dict() for d in docs], f, indent=2, ensure_ascii=False)
        print(f"      Cached to {docs_cache_path}")

    all_documents.extend(docs)

    # --- Load curated knowledge base ---
    print("\n[1.5/5] Loading curated Isaac Sim 5.1 knowledge base...")
    kb_docs = load_curated_knowledge_base()
    print(f"      Loaded {len(kb_docs)} curated knowledge documents.")
    all_documents.extend(kb_docs)

    # --- Load project sources ---
    print("\n[2/5] Loading project source files...")
    project_docs = fetch_project_sources(project_root)
    print(f"      Loaded {len(project_docs)} project source files.")
    all_documents.extend(project_docs)

    # --- Chunk ---
    print(f"\n[3/5] Chunking documents (chunk_size={chunk_size}, overlap={chunk_overlap})...")
    chunks = chunk_documents(all_documents, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    print(f"      Created {len(chunks)} chunks from {len(all_documents)} documents.")

    doc_type_counts = {}
    for chunk in chunks:
        dt = chunk.metadata.get("type", "unknown")
        doc_type_counts[dt] = doc_type_counts.get(dt, 0) + 1
    for dt, count in sorted(doc_type_counts.items()):
        print(f"        {dt}: {count} chunks")

    # --- Embed and store ---
    print("\n[4/5] Embedding chunks and adding to vector store...")
    print("      (This may take a few minutes on first run — downloading embedding model)")
    added = store.add_chunks(chunks)
    print(f"      Added {added} new chunks. Total in store: {store.count()}")

    # --- Summary ---
    print("\n[5/5] Build complete!")
    print(f"      Vector store: {store.persist_directory}")
    print(f"      Collection:   {store.collection_name}")
    print(f"      Total chunks:  {store.count()}")
    print(f"      Embedding model: {store.embedding_model_name}")

    print("\n  Quick test queries:")
    test_queries = [
        "How to set up Replicator BasicWriter for COCO output?",
        "How to spawn a forklift in Isaac Sim?",
        "How to apply semantic labels to prims?",
    ]
    for q in test_queries:
        results = store.query(q, n_results=2)
        if results:
            top = results[0]
            print(f"    Q: {q}")
            print(f"    -> {top['metadata'].get('title', '?')} (dist={top['distance']:.3f})")
            print(f"       {top['text'][:120]}...")
        else:
            print(f"    Q: {q} -> No results")
        print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build RAG vector index")
    parser.add_argument("--project-root", type=str, default=None,
                        help="Project root directory (auto-detected)")
    parser.add_argument("--max-pages", type=int, default=40,
                        help="Max pages to crawl from Isaac Sim docs")
    parser.add_argument("--chunk-size", type=int, default=1200,
                        help="Target chunk size in tokens")
    parser.add_argument("--chunk-overlap", type=int, default=200,
                        help="Chunk overlap in tokens")
    parser.add_argument("--reset", action="store_true",
                        help="Reset the vector store before building")
    parser.add_argument("--skip-crawl", action="store_true",
                        help="Use cached docs instead of re-crawling")
    args = parser.parse_args()

    build_index(
        project_root=args.project_root,
        max_pages=args.max_pages,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
        reset=args.reset,
        skip_crawl=args.skip_crawl,
    )