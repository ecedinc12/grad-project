"""Document loading utilities for Isaac Sim 5.1 documentation and project source files.

Fetches pages from docs.isaacsim.omniverse.nvidia.com/5.1.0/, chunks them,
and saves raw markdown to data/ for offline reuse.
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

DATA_DIR = Path(__file__).parent / "data"

ISAAC_SIM_51_BASE = "https://docs.isaacsim.omniverse.nvidia.com/5.1.0/"

SEED_URLS: List[str] = [
    ISAAC_SIM_51_BASE + "replicator_tutorials/index.html",
    ISAAC_SIM_51_BASE + "replicator_tutorials/tutorial_replicator_overview.html",
    ISAAC_SIM_51_BASE + "replicator_tutorials/tutorial_replicator_getting_started.html",
    ISAAC_SIM_51_BASE + "replicator_tutorials/tutorial_replicator_scene_based_sdg.html",
    ISAAC_SIM_51_BASE + "replicator_tutorials/tutorial_replicator_object_based_sdg.html",
    ISAAC_SIM_51_BASE + "replicator_tutorials/tutorial_replicator_isaac_randomizers.html",
    ISAAC_SIM_51_BASE + "replicator_tutorials/tutorial_replicator_isaac_snippets.html",
    ISAAC_SIM_51_BASE + "core_api_tutorials/index.html",
    ISAAC_SIM_51_BASE + "core_api_tutorials/tutorial_core_hello_world.html",
    ISAAC_SIM_51_BASE + "synthetic_data_generation/index.html",
    ISAAC_SIM_51_BASE + "sensors/index.html",
]


@dataclass
class Document:
    content: str
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"content": self.content, "metadata": self.metadata}

    @classmethod
    def from_dict(cls, d: dict) -> "Document":
        return cls(content=d["content"], metadata=d.get("metadata", {}))


def _html_to_markdown(html: str, url: str) -> str:
    """Convert HTML to clean markdown, stripping navigation and boilerplate."""
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup.find_all(["nav", "header", "footer", "script", "style", "noscript"]):
        tag.decompose()

    for div in soup.find_all("div", class_=["toc", "sidebar", "related", "sphinx-sidebar"]):
        div.decompose()

    main = soup.find("main") or soup.find("div", role="main") or soup.find("div", class_="body") or soup
    if main is None:
        main = soup

    text = main.get_text(separator="\n")

    lines = text.split("\n")
    cleaned = []
    prev_blank = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if not prev_blank:
                cleaned.append("")
                prev_blank = True
            continue
        prev_blank = False
        cleaned.append(stripped)

    result = "\n".join(cleaned).strip()

    if len(result) > 15000:
        result = result[:15000] + "\n\n[... truncated]"

    return result


def fetch_page(url: str, timeout: int = 30) -> Optional[Tuple[Document, "BeautifulSoup"]]:
    """Fetch a single URL and return a Document and the parsed soup for link extraction."""
    try:
        resp = requests.get(url, timeout=timeout, headers={"User-Agent": "IsaacSimRAGBot/1.0"})
        resp.raise_for_status()
    except Exception as e:
        print(f"[WARN] Failed to fetch {url}: {e}")
        return None

    markdown = _html_to_markdown(resp.text, url)
    if len(markdown) < 100:
        print(f"[WARN] Page too short, skipping: {url}")
        return None

    title = url.split("/")[-1].replace(".html", "")
    doc = Document(
        content=markdown,
        metadata={"source": url, "title": title, "type": "isaac_sim_docs"},
    )

    soup = None
    try:
        soup = BeautifulSoup(resp.text, "html.parser")
    except Exception:
        pass

    return doc, soup


def load_curated_knowledge_base() -> List[Document]:
    """Load the curated Isaac Sim 5.1 knowledge base from the data directory."""
    kb_path = DATA_DIR / "isaac_sim_51_knowledge_base.md"
    if not kb_path.exists():
        print(f"[WARN] Curated knowledge base not found at {kb_path}")
        return []
    with open(kb_path, "r") as f:
        content = f.read()
    return [Document(
        content=content,
        metadata={"source": str(kb_path), "title": "isaac_sim_51_knowledge_base", "type": "curated_knowledge"},
    )]


def fetch_project_sources(project_root: str) -> List[Document]:
    """Load project source files as documents."""
    docs = []
    src_dirs = [
        os.path.join(project_root, "isaac_backend"),
        os.path.join(project_root, "llm_pipeline"),
        os.path.join(project_root, "scripts"),
    ]
    for src_dir in src_dirs:
        if not os.path.isdir(src_dir):
            continue
        for root, subdirs, files in os.walk(src_dir):
            for fname in sorted(files):
                if not fname.endswith(".py"):
                    continue
                fpath = os.path.join(root, fname)
                with open(fpath, "r") as f:
                    content = f.read()
                docs.append(Document(
                    content=content,
                    metadata={"source": fpath, "title": fname, "type": "project_source"},
                ))

    config_files = [
        os.path.join(project_root, "assets", "library.json"),
    ]
    for cf in config_files:
        if os.path.exists(cf):
            with open(cf, "r") as f:
                content = f.read()
            docs.append(Document(
                content=content,
                metadata={"source": cf, "title": os.path.basename(cf), "type": "project_config"},
            ))

    return docs


def hash_content(content: str) -> str:
    """Simple hash for deduplication."""
    import hashlib
    return hashlib.md5(content.encode()).hexdigest()[:12]


def crawl_docs(urls: List[str] | None = None, max_pages: int = 50) -> List[Document]:
    """Crawl Isaac Sim documentation pages.

    Args:
        urls: Starting URLs. Defaults to SEED_URLS.
        max_pages: Maximum number of pages to crawl.
    """
    if urls is None:
        urls = SEED_URLS.copy()

    visited = set()
    documents = []
    seen_hashes = set()
    queue = list(urls)

    while queue and len(visited) < max_pages:
        url = queue.pop(0)
        if url in visited:
            continue
        if "5.1" not in url and "latest" not in url and "ext_replicator" not in url:
            continue

        visited.add(url)
        print(f"[INFO] Fetching ({len(visited)}/{max_pages}): {url}")

        result = fetch_page(url)
        if result is None:
            continue

        doc, soup = result

        chash = hash_content(doc.content)
        if chash in seen_hashes:
            continue
        seen_hashes.add(chash)

        documents.append(doc)

        if soup and len(visited) < 20:
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if href.startswith("#") or href.startswith("mailto:"):
                    continue
                full_url = urljoin(url, href)
                parsed = urlparse(full_url)
                if parsed.netloc and "isaacsim" in parsed.netloc and full_url.endswith(".html"):
                    if full_url not in visited and "5.1" in full_url:
                        queue.append(full_url)

    return documents


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Fetch Isaac Sim 5.1 docs for RAG")
    parser.add_argument("--max-pages", type=int, default=40, help="Max pages to crawl")
    parser.add_argument("--project-root", type=str, default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        help="Project root directory")
    args = parser.parse_args()

    os.makedirs(DATA_DIR, exist_ok=True)

    print(f"[INFO] Crawling Isaac Sim 5.1 docs (max {args.max_pages} pages)...")
    docs = crawl_docs(max_pages=args.max_pages)

    print(f"[INFO] Fetched {len(docs)} documentation pages.")
    docs_path = DATA_DIR / "isaac_sim_docs.json"
    with open(docs_path, "w") as f:
        json.dump([d.to_dict() for d in docs], f, indent=2, ensure_ascii=False)
    print(f"[INFO] Saved to {docs_path}")

    print("[INFO] Loading project source files...")
    project_docs = fetch_project_sources(args.project_root)
    print(f"[INFO] Loaded {len(project_docs)} project source files.")

    src_path = DATA_DIR / "project_sources.json"
    with open(src_path, "w") as f:
        json.dump([d.to_dict() for d in project_docs], f, indent=2, ensure_ascii=False)
    print(f"[INFO] Saved to {src_path}")

    total = len(docs) + len(project_docs)
    print(f"[INFO] Total documents: {total}")