FROM python:3.11-slim

# System deps: build tools for faiss/fastembed wheels that need compiling
# on some platforms, plus certs for outbound HTTPS (scraping, OpenRouter).
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Render (and most PaaS) inject $PORT at runtime; default to 8000 for local
# `docker run`. Using shell form so the env var expands.
ENV PORT=8000
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD \
    curl -f http://localhost:${PORT}/api/health || exit 1

CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT}
