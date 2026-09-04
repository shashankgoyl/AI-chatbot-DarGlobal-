from __future__ import annotations

import logging

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("chatbot")

app = FastAPI(
    title="DarGlobal & Wasalt AI Chatbot",
    description="RAG chatbot over publicly scraped DarGlobal + Wasalt real-estate listings, "
    "powered by a free OpenRouter model.",
    version="1.0.0",
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


class ChatRequest(BaseModel):
    message: str
    history: list[ChatTurn] = Field(default_factory=list)


class ChatResponse(BaseModel):
    answer: str
    sources: list[dict]


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="message must not be empty")

    from .rag_pipeline import answer_question

    try:
        history = [t.model_dump() for t in req.history]
        result = answer_question(req.message, history)
        return ChatResponse(answer=result["answer"], sources=result["sources"])
    except RuntimeError as exc:
        # e.g. missing OPENROUTER_API_KEY or empty vector store
        logger.error("chat failed: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover
        logger.exception("unexpected chat error")
        raise HTTPException(status_code=500, detail="internal error") from exc


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
