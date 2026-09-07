from __future__ import annotations

import json
import logging
from typing import Optional

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from . import config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("chatbot")

app = FastAPI(
    title="DarGlobal & Wasalt AI Chatbot",
    description="RAG chatbot over publicly scraped DarGlobal + Wasalt real-estate listings, "
    "powered by OpenRouter with automatic Gemini fallback.",
    version="1.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatTurn(BaseModel):
    role: str = Field(..., description="'user' or 'assistant'")
    content: str


class ChatFilters(BaseModel):
    """All optional — only values actually present in the current scrape are
    meaningful; see GET /api/filters for what to offer in a picker."""

    source: Optional[str] = Field(default=None, description="'darglobal' or 'wasalt'")
    location: Optional[str] = Field(default=None, description="substring match, case-insensitive")
    beds: Optional[str] = Field(default=None, description="substring match, case-insensitive")
    price_currency: Optional[str] = Field(default=None, description="e.g. 'AED', 'SAR', 'USD'")
    price_min: Optional[float] = None
    price_max: Optional[float] = None


class ChatRequest(BaseModel):
    message: str
    history: list[ChatTurn] = Field(default_factory=list)
    filters: ChatFilters = Field(default_factory=ChatFilters)


class ChatResponse(BaseModel):
    answer: str
    sources: list[dict]
    provider: str


@app.get("/api/health")
def health():
    return {"status": "ok"}


def _count_docs(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return len(data) if isinstance(data, list) else 0
    except (FileNotFoundError, json.JSONDecodeError):
        return 0


@app.get("/api/stats")
def stats():
    """Real counts from the last successful scrape, for the UI's stat cards.

    No invented numbers here — if a source hasn't been scraped yet (or
    returned nothing), its count is honestly 0 until /api/reingest runs.
    """
    darglobal_count = _count_docs(config.RAW_DIR / "darglobal.json")
    wasalt_count = _count_docs(config.RAW_DIR / "wasalt.json")
    vectorstore_ready = (config.VECTORSTORE_DIR / "index.faiss").exists()

    return {
        "darglobal_count": darglobal_count,
        "wasalt_count": wasalt_count,
        "total_indexed": darglobal_count + wasalt_count,
        "vectorstore_ready": vectorstore_ready,
        "model": config.OPENROUTER_MODEL,
        "fallback_model": config.GEMINI_MODEL,
        "gemini_configured": bool(config.GEMINI_API_KEY),
    }


@app.get("/api/filters")
def filters_options():
    """Distinct source/location/beds/currency values actually present in the
    current index, so the UI's filter picker never offers a choice that
    would silently return nothing."""
    from .filters import get_filter_options

    return get_filter_options()


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="message must not be empty")

    from .rag_pipeline import answer_question

    try:
        history = [t.model_dump() for t in req.history]
        filters = req.filters.model_dump(exclude_none=True)
        result = answer_question(req.message, history, filters)
        return ChatResponse(answer=result["answer"], sources=result["sources"], provider=result["provider"])
    except RuntimeError as exc:
        # e.g. no provider configured/available, or empty vector store
        logger.error("chat failed: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover
        logger.exception("unexpected chat error")
        raise HTTPException(status_code=500, detail="internal error") from exc


@app.post("/api/chat/stream")
def chat_stream(req: ChatRequest):
    """Server-Sent Events version of /api/chat.

    Emits one JSON object per event, each as `data: <json>\\n\\n`:
      {"type": "sources", "sources": [...]}          — once, right away
      {"type": "token", "text": "..."}                — many, as they arrive
      {"type": "done", "provider": "openrouter"|"gemini"}  — on success
      {"type": "error", "message": "..."}             — on failure
    Plain fetch + ReadableStream on the frontend, not the EventSource API,
    since EventSource can't send a POST body (needed for history + filters).
    """
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="message must not be empty")

    from .rag_pipeline import stream_answer

    history = [t.model_dump() for t in req.history]
    filters = req.filters.model_dump(exclude_none=True)

    def event_source():
        try:
            for event in stream_answer(req.message, history, filters):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as exc:  # pragma: no cover — last-resort safety net
            logger.exception("unexpected streaming error")
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # keep nginx/proxies from buffering the stream
        },
    )


@app.post("/api/reingest")
def reingest(x_admin_token: str = Header(default="")):
    """Re-scrape + rebuild the vector store on demand.

    Protected by a shared secret (ADMIN_TOKEN env var) since scraping +
    embedding is expensive; leave ADMIN_TOKEN unset to disable this route
    entirely.
    """
    if not config.ADMIN_TOKEN or x_admin_token != config.ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="forbidden")

    from scraper.scrape_darglobal import crawl as crawl_darglobal
    from scraper.scrape_wasalt import crawl as crawl_wasalt
    from scraper.utils import save_docs
    from .ingest_pipeline import build_vectorstore
    from .rag_pipeline import reset_vectorstore_cache

    dar_docs = crawl_darglobal()
    save_docs(dar_docs, config.RAW_DIR / "darglobal.json")

    wasalt_docs = crawl_wasalt()
    save_docs(wasalt_docs, config.RAW_DIR / "wasalt.json")

    build_vectorstore()
    reset_vectorstore_cache()

    return {"darglobal_docs": len(dar_docs), "wasalt_docs": len(wasalt_docs)}


@app.on_event("startup")
def on_startup():
    if not config.AUTO_INGEST_ON_STARTUP:
        return
    try:
        from .ingest_pipeline import load_vectorstore

        if load_vectorstore() is not None:
            logger.info("Vector store already present on disk — skipping auto-ingest.")
            return

        logger.info("No vector store found. Running scrape + ingest once at startup…")
        from scraper.scrape_darglobal import crawl as crawl_darglobal
        from scraper.scrape_wasalt import crawl as crawl_wasalt
        from scraper.utils import save_docs
        from .ingest_pipeline import build_vectorstore

        dar_docs = crawl_darglobal()
        save_docs(dar_docs, config.RAW_DIR / "darglobal.json")

        wasalt_docs = crawl_wasalt()
        save_docs(wasalt_docs, config.RAW_DIR / "wasalt.json")

        if dar_docs or wasalt_docs:
            build_vectorstore()
            logger.info("Auto-ingest complete: %d DarGlobal + %d Wasalt docs.", len(dar_docs), len(wasalt_docs))
        else:
            logger.warning(
                "Scraping returned no documents (site may be blocking requests). "
                "The chatbot will report an empty knowledge base until you run "
                "ingest.py manually or POST /api/reingest."
            )
    except Exception:
        logger.exception(
            "Auto-ingest failed at startup. The app will still boot; fix data "
            "with `python ingest.py` and restart, or set AUTO_INGEST_ON_STARTUP=false."
        )
