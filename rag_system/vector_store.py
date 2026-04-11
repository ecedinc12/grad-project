"""Embedding and vector store using ChromaDB for RAG retrieval.

Uses sentence-transformers (all-MiniLM-L6-v2) for embeddings —
no GPU required, runs on CPU in the standard Python environment.
"""

from pathlib import Path
from typing import List, Optional

from rag_system.chunker import Chunk

VECTOR_STORE_DIR = Path(__file__).parent / "data" / "chroma_db"

_DEFAULT_EMBEDDING_MODEL = "all-MiniLM-L6-v2"


class VectorStore:
    """ChromaDB-backed vector store for RAG chunk retrieval."""

    def __init__(
        self,
        collection_name: str = "isaac_sim_rag",
        embedding_model: str = _DEFAULT_EMBEDDING_MODEL,
        persist_directory: Optional[str] = None,
    ):
        self.collection_name = collection_name
        self.embedding_model_name = embedding_model
        self.persist_directory = persist_directory or str(VECTOR_STORE_DIR)
        self._collection = None
        self._client = None
        self._embedding_fn = None

    def _get_embedding_fn(self):
        """Lazy-load the embedding function."""
        if self._embedding_fn is not None:
            return self._embedding_fn

        try:
            from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
            self._embedding_fn = SentenceTransformerEmbeddingFunction(
                model_name=self.embedding_model_name,
                device="cpu",
            )
        except ImportError:
            raise ImportError(
                "chromadb and sentence-transformers are required. "
                "Install with: pip install chromadb sentence-transformers"
            )
        return self._embedding_fn

    def _get_client(self):
        """Lazy-load the ChromaDB client."""
        if self._client is not None:
            return self._client

        import chromadb
        self._client = chromadb.PersistentClient(path=self.persist_directory)
        return self._client

    def _get_collection(self):
        """Get or create the ChromaDB collection."""
        if self._collection is not None:
            return self._collection

        client = self._get_client()
        embedding_fn = self._get_embedding_fn()
        self._collection = client.get_or_create_collection(
            name=self.collection_name,
            embedding_function=embedding_fn,
        )
        return self._collection

    def add_chunks(self, chunks: List[Chunk]) -> int:
        """Add chunks to the vector store. Returns number of chunks added."""
        collection = self._get_collection()

        existing = collection.get(include=[])
        existing_ids = set(existing["ids"]) if existing["ids"] else set()

        ids = []
        documents = []
        metadatas = []
        skipped = 0

        for i, chunk in enumerate(chunks):
            src = chunk.metadata.get("source", "unknown")
            idx = chunk.metadata.get("chunk_index", i)
            chunk_id = f"{src}_{idx}_{hash(src + str(idx)) % 10000:04d}"
            chunk_id = chunk_id.replace("/", "_").replace(" ", "_").replace(".", "_")[:200]

            if chunk_id in existing_ids:
                skipped += 1
                continue

            ids.append(chunk_id)
            documents.append(chunk.text)
            metadatas.append(chunk.metadata)

        if not ids:
            if skipped:
                print(f"[INFO] All {skipped} chunks already exist in vector store. Use reset() to rebuild.")
            else:
                print("[INFO] No new chunks to add.")
            return 0

        batch_size = 200
        total_added = 0
        for start in range(0, len(ids), batch_size):
            end = min(start + batch_size, len(ids))
            collection.add(
                ids=ids[start:end],
                documents=documents[start:end],
                metadatas=metadatas[start:end],
            )
            total_added += end - start

        print(f"[INFO] Added {total_added} chunks to vector store (collection: {self.collection_name})")
        if skipped:
            print(f"[INFO] Skipped {skipped} existing chunks (re-index detected, use reset() to force rebuild)")
        return total_added

    def query(
        self,
        query_text: str,
        n_results: int = 5,
        doc_type: Optional[str] = None,
    ) -> List[dict]:
        """Query the vector store for relevant chunks.

        Args:
            query_text: The search query.
            n_results: Number of results to return.
            doc_type: Optional filter by document type ('isaac_sim_docs', 'project_source', etc.)

        Returns:
            List of dicts with 'text', 'metadata', 'distance' keys.
        """
        collection = self._get_collection()

        where_filter = None
        if doc_type:
            where_filter = {"type": doc_type}

        results = collection.query(
            query_texts=[query_text],
            n_results=n_results,
            where=where_filter,
        )

        output = []
        if results and results["ids"] and results["ids"][0]:
            for i in range(len(results["ids"][0])):
                output.append({
                    "text": results["documents"][0][i],
                    "metadata": results["metadatas"][0][i],
                    "distance": results["distances"][0][i] if "distances" in results else None,
                })

        return output

    def count(self) -> int:
        """Return the number of chunks in the store."""
        collection = self._get_collection()
        return collection.count()

    def reset(self):
        """Delete and recreate the collection."""
        client = self._get_client()
        try:
            client.delete_collection(self.collection_name)
        except Exception:
            pass
        self._collection = None
        self._get_collection()
        print(f"[INFO] Reset collection: {self.collection_name}")