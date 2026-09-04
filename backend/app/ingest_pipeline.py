"""
Builds the vector store the chatbot retrieves from.

Flow: scraped JSON (data/raw/*.json) -> LangChain Documents -> chunks ->
local sentence-transformers embeddings -> FAISS index persisted to disk.

Kept separate from the scrapers themselves so you can re-run ingestion
against manually curated/edited JSON without re-scraping anything.
"""
from __future__ import annotations

import json
from pathlib import Path

from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document

from . import config

_embeddings = None


def get_embeddings():
    """Local, free, no-API-key embedding model (downloaded once, cached).

    Uses FastEmbed (ONNX runtime) rather than sentence-transformers/torch —
    it's far lighter on RAM and disk, which matters a lot on free-tier
    hosts like Render's free web service plan (512MB RAM).
    """
    global _embeddings
    if _embeddings is None:
        from langchain_community.embeddings import FastEmbedEmbeddings

        _embeddings = FastEmbedEmbeddings(model_name=config.EMBEDDING_MODEL)
    return _embeddings


def load_raw_documents() -> list[Document]:
    docs: list[Document] = []
    if not config.RAW_DIR.exists():
        return docs

    for json_path in sorted(config.RAW_DIR.glob("*.json")):
        try:
            items = json.loads(json_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        for item in items:
            content = (item.get("content") or "").strip()
            if not content:
                continue
            metadata = {
                "id": item.get("id"),
                "source": item.get("source"),
                "url": item.get("url"),
                "title": item.get("title"),
                "price": item.get("price"),
                "location": item.get("location"),
                "beds": item.get("beds"),
            }
            docs.append(Document(page_content=f"{item.get('title', '')}\n\n{content}", metadata=metadata))
    return docs


def build_vectorstore(docs: list[Document] | None = None):
    from langchain_community.vectorstores import FAISS

    docs = docs if docs is not None else load_raw_documents()
    if not docs:
        raise RuntimeError(
            "No scraped documents found in data/raw/. Run the scrapers first "
            "(python -m scraper.scrape_darglobal && python -m scraper.scrape_wasalt)."
        )

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=config.CHUNK_SIZE,
        chunk_overlap=config.CHUNK_OVERLAP,
    )
    chunks = splitter.split_documents(docs)

    vectorstore = FAISS.from_documents(chunks, get_embeddings())
    config.VECTORSTORE_DIR.mkdir(parents=True, exist_ok=True)
    vectorstore.save_local(str(config.VECTORSTORE_DIR))
    return vectorstore


def load_vectorstore():
    from langchain_community.vectorstores import FAISS

    index_file = config.VECTORSTORE_DIR / "index.faiss"
    if not index_file.exists():
        return None
    return FAISS.load_local(
        str(config.VECTORSTORE_DIR),
        get_embeddings(),
        allow_dangerous_deserialization=True,
    )


def load_or_build_vectorstore():
    vs = load_vectorstore()
    if vs is not None:
        return vs
    return build_vectorstore()
