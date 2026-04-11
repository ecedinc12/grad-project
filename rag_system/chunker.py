"""Text chunking strategies for RAG documents.

Splits documents into overlapping chunks of token-appropriate size
while preserving code blocks and semantic boundaries.
"""

from dataclasses import dataclass
from typing import List, Optional

from rag_system.loader import Document


@dataclass
class Chunk:
    text: str
    metadata: dict

    def to_dict(self) -> dict:
        return {"text": self.text, "metadata": self.metadata}

    @classmethod
    def from_dict(cls, d: dict) -> "Chunk":
        return cls(text=d["text"], metadata=d.get("metadata", {}))


DEFAULT_CHUNK_SIZE = 1200
DEFAULT_CHUNK_OVERLAP = 200


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token for English/code."""
    return len(text) // 4


def _overlap_lines(chunk_overlap: int, for_code: bool = False) -> int:
    """Convert chunk_overlap (estimated tokens) to overlap line count.

    Heuristic: ~15 tokens/line for prose, ~10 for code.
    """
    per_line = 10 if for_code else 15
    return max(3, chunk_overlap // per_line)


def _split_code_blocks(text: str) -> List[str]:
    """Split text while keeping code blocks intact."""
    parts = []
    in_code = False
    code_buf = []
    text_buf = []

    lines = text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("```") and not in_code:
            if text_buf:
                parts.append("\n".join(text_buf))
                text_buf = []
            in_code = True
            code_buf = [line]
            i += 1
            continue
        elif line.strip().startswith("```") and in_code:
            code_buf.append(line)
            in_code = False
            parts.append("\n".join(code_buf))
            code_buf = []
            i += 1
            continue

        if in_code:
            code_buf.append(line)
        else:
            text_buf.append(line)
        i += 1

    if text_buf:
        parts.append("\n".join(text_buf))
    if code_buf:
        parts.append("\n".join(code_buf))

    return [p for p in parts if p.strip()]


def chunk_document(
    doc: Document,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> List[Chunk]:
    """Split a single Document into overlapping Chunks.

    Preserves code blocks by splitting on code-block boundaries first,
    then merging/splitting on paragraph boundaries within prose sections.
    """
    content = doc.content
    metadata = dict(doc.metadata)
    source = metadata.get("source", "unknown")

    parts = _split_code_blocks(content)

    all_chunks: List[Chunk] = []
    current_text = ""
    chunk_idx = 0

    def flush(text: str, idx: int) -> Optional[Chunk]:
        if not text.strip():
            return None
        if _estimate_tokens(text) < 30:
            return None
        meta = dict(metadata)
        meta["chunk_index"] = idx
        meta["source"] = source
        return Chunk(text=text.strip(), metadata=meta)

    for part in parts:
        is_code = part.strip().startswith("```")

        if is_code:
            code_tokens = _estimate_tokens(part)
            if _estimate_tokens(current_text) + code_tokens <= chunk_size and current_text:
                current_text += "\n\n" + part
            else:
                if current_text:
                    chunk = flush(current_text, chunk_idx)
                    if chunk:
                        all_chunks.append(chunk)
                        chunk_idx += 1
                if code_tokens > chunk_size:
                    first_fence = part.split("\n", 1)[0]
                    lang = first_fence.strip().lstrip("`").strip()
                    fence_open = f"```{lang}" if lang else "```"
                    all_lines = part.split("\n")
                    inner_lines = all_lines[1:]
                    if inner_lines and inner_lines[-1].strip().startswith("```"):
                        inner_lines = inner_lines[:-1]
                    ol_count = _overlap_lines(chunk_overlap, for_code=True)
                    buf = ""
                    for line in inner_lines:
                        if _estimate_tokens(buf + "\n" + line) > chunk_size and buf:
                            fenced = f"{fence_open}\n{buf}\n```"
                            chunk = flush(fenced, chunk_idx)
                            if chunk:
                                all_chunks.append(chunk)
                                chunk_idx += 1
                            overlap = buf.split("\n")[-ol_count:]
                            buf = "\n".join(overlap) + "\n" + line
                        else:
                            buf = buf + "\n" + line if buf else line
                    if buf.strip():
                        current_text = f"{fence_open}\n{buf}\n```"
                    else:
                        current_text = ""
                else:
                    current_text = part
        else:
            paragraphs = part.split("\n\n")
            for para in paragraphs:
                para_tokens = _estimate_tokens(para)
                if _estimate_tokens(current_text) + para_tokens > chunk_size and current_text:
                    chunk = flush(current_text, chunk_idx)
                    if chunk:
                        all_chunks.append(chunk)
                        chunk_idx += 1
                    overlap_count = _overlap_lines(chunk_overlap, for_code=False)
                    overlap_text = current_text.split("\n")[-overlap_count:]
                    current_text = "\n".join(overlap_text) + "\n\n" + para if overlap_text else para
                else:
                    current_text = current_text + "\n\n" + para if current_text else para

    if current_text:
        chunk = flush(current_text, chunk_idx)
        if chunk:
            all_chunks.append(chunk)

    return all_chunks


def chunk_documents(
    documents: List[Document],
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> List[Chunk]:
    """Chunk a list of Documents into Chunks."""
    all_chunks: List[Chunk] = []
    for doc in documents:
        all_chunks.extend(chunk_document(doc, chunk_size, chunk_overlap))
    return all_chunks