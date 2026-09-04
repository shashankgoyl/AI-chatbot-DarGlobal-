import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
# Load backend/.env explicitly so this works no matter what directory
# the server is started from.
load_dotenv(BASE_DIR / ".env")

# --- OpenRouter (free-tier) ---------------------------------------------
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
# "openrouter/free" auto-routes to whichever free model is available right
# now, so the app keeps working even as OpenRouter rotates its free lineup.
# Pin a specific free model instead if you want reproducible behaviour, e.g.
# "meta-llama/llama-3.1-8b-instruct:free" or "google/gemma-2-9b-it:free"
# (check https://openrouter.ai/models?max_price=0 for the current list).
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openrouter/free")

# Sent to OpenRouter for their leaderboard/analytics — optional but recommended.
OPENROUTER_SITE_URL = os.getenv("OPENROUTER_SITE_URL", "https://github.com/")
OPENROUTER_APP_NAME = os.getenv("OPENROUTER_APP_NAME", "DarGlobal-Wasalt-AI-Chatbot")

# --- Embeddings (local, free, no API key needed) ------------------------
# FastEmbed (ONNX) model — small, fast, no torch dependency. Good fit for
# free-tier hosts. See https://qdrant.github.io/fastembed/ for the catalog.
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")

# --- Data / vector store --------------------------------------------------
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
RAW_DIR = DATA_DIR / "raw"
VECTORSTORE_DIR = Path(os.getenv("VECTORSTORE_DIR", DATA_DIR / "vectorstore"))

CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "800"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "120"))
RETRIEVER_K = int(os.getenv("RETRIEVER_K", "5"))

# --- Server ---------------------------------------------------------------
PORT = int(os.getenv("PORT", "8000"))
# Comma-separated list of allowed frontend origins, e.g. your Netlify URL(s).
ALLOWED_ORIGINS = [
    o.strip() for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:5173").split(",") if o.strip()
]

# Auto-run the scrape+ingest pipeline on first boot if no vector store is
# found on disk yet. Turn this off (set to "false") if you'd rather run
# `python ingest.py` yourself and ship the built index.
AUTO_INGEST_ON_STARTUP = os.getenv("AUTO_INGEST_ON_STARTUP", "true").lower() == "true"

# Simple shared-secret to protect the manual re-ingest endpoint.
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")
