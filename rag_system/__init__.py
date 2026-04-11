"""RAG System for Isaac Sim Project.

Provides Retrieval-Augmented Generation using Isaac Sim 5.1 documentation
and project source files. Uses ChromaDB + sentence-transformers for
vector storage and similarity search.

Quick start:
    1. Install dependencies:  pip install -r requirements.txt
    2. Build the index:        python -m rag_system.build_index
    3. Query:                  python -m rag_system.query "How to use BasicWriter?"
    4. Generate with RAG:      python -m rag_system.query --generate "spawn forklift near worker"
"""

__version__ = "0.1.0"

from rag_system.vector_store import VectorStore
from rag_system.generation import retrieve_context, build_rag_prompt, generate_with_rag, RAGGenerationError, MissingAPIKeyError, SchemaValidationError

__all__ = [
    "VectorStore",
    "retrieve_context",
    "build_rag_prompt",
    "generate_with_rag",
    "RAGGenerationError",
    "MissingAPIKeyError",
    "SchemaValidationError",
]