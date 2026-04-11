"""RAG System for Isaac Sim Project.

Provides Retrieval-Augmented Generation using Isaac Sim 5.1 documentation
and project source files. Uses ChromaDB + sentence-transformers for
vector storage and similarity search.

Quick start:
    1. Install dependencies:  pip install -r requirements.txt
    2. Build the index:        python -m rag_system.build_index
    3. Query:                  python -m rag_system.query "How to use BasicWriter?"
    4. Generate with RAG:      python -m rag_system.query --generate "spawn forklift near worker"

Modules:
    - loader:       Fetch Isaac Sim 5.1 docs and project source files
    - chunker:     Split documents into retrieval-sized chunks
    - vector_store: ChromaDB-backed vector store with sentence-transformers embeddings
    - generation:   RAG-augmented SceneConfig generation
    - build_index:  CLI to build the vector index
    - query:        CLI to query the RAG system interactively
"""

__version__ = "0.1.0"

from rag_system.vector_store import VectorStore
from rag_system.generation import retrieve_context, build_rag_prompt, generate_with_rag

__all__ = [
    "VectorStore",
    "retrieve_context",
    "build_rag_prompt",
    "generate_with_rag",
]