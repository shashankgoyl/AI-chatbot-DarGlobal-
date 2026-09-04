# Estate Index — DarGlobal & Wasalt AI Chatbot

An AI chatbot that answers questions about publicly listed properties from
**DarGlobal** (darglobal.co.uk) and **Wasalt** (wasalt.sa), grounded in
data pulled by a scraper and served through a Retrieval-Augmented
Generation (RAG) pipeline.

```
├── backend/     FastAPI + LangChain/LangGraph RAG API, scrapers, Docker → Render
└── frontend/    React + Vite chat UI → Netlify
```

**Stack**
- **Scraping:** `requests` + `BeautifulSoup4`, polite (robots.txt-aware, rate-limited)
- **RAG:** LangChain (chunking, vector store) + LangGraph (retrieve → generate graph)
- **LLM:** any free model on [OpenRouter](https://openrouter.ai) — defaults to
  `openrouter/free`, which auto-routes to whatever's free right now
- **Embeddings:** [FastEmbed](https://qdrant.github.io/fastembed/) — local, free, no API key, light enough for free hosting tiers
- **Vector store:** FAISS, persisted to disk
- **Frontend:** React + Vite, deployed as a static site on Netlify
- **Backend:** Dockerized FastAPI, deployed on Render

---

## 1. Local setup

### Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# edit .env and add a free OPENROUTER_API_KEY from https://openrouter.ai/keys
```

Scrape both sites and build the vector store **once**, up front, rather
than relying on the app to do it live on every boot:

```bash
python ingest.py
```

This writes `data/raw/darglobal.json`, `data/raw/wasalt.json`, and the
FAISS index under `data/vectorstore/`. Commit these to git — that's what
lets Render start the container instantly instead of re-scraping on every
cold start (see `AUTO_INGEST_ON_STARTUP` in `.env.example`).

> **A note on scraping:** the scrapers in `backend/scraper/` check
> `robots.txt`, rate-limit themselves, and only touch public pages — no
> logins, no CAPTCHA bypassing. Site markup changes over time; if a scrape
> comes back empty or thin, open the target page in a browser, inspect the
> HTML, and adjust the selectors/regex in `scrape_darglobal.py` /
> `scrape_wasalt.py` accordingly. Also re-check each site's Terms of Use
> before scraping at any real scale or frequency.

Run the API:

```bash
uvicorn app.main:app --reload --port 8000
```

Check it's alive: `curl http://localhost:8000/api/health`

### Frontend

```bash
cd frontend
npm install
cp .env.example .env   # VITE_API_URL=http://localhost:8000
npm run dev
```

Open the printed local URL (default `http://localhost:5173`) and chat.

### Or run both with Docker Compose

```bash
cp backend/.env.example backend/.env   # add your OPENROUTER_API_KEY
docker compose up --build
```

Frontend → `http://localhost:8080`, backend → `http://localhost:8000`.

---

## 2. Push to GitHub

```bash
cd /path/to/this/project
git init
git add .
git commit -m "Initial commit: DarGlobal/Wasalt AI chatbot"
git branch -M main
git remote add origin https://github.com/<your-username>/<your-repo>.git
git push -u origin main
```

If `data/vectorstore/` ends up large (FastEmbed's model files are small,
but a big scrape can add up), consider [Git LFS](https://git-lfs.com/) for
that folder, or leave `AUTO_INGEST_ON_STARTUP=true` and let Render build it
on first boot instead of committing it.

---

## 3. Deploy the backend on Render

1. In the [Render dashboard](https://dashboard.render.com), click **New →
   Web Service** and connect the GitHub repo you just pushed.
2. Configure:
   - **Root directory:** `backend`
   - **Runtime:** Docker (Render will detect `backend/Dockerfile` automatically)
   - **Instance type:** Free
3. Add environment variables (Render → your service → Environment):
   | Key | Value |
   |---|---|
   | `OPENROUTER_API_KEY` | your free key from https://openrouter.ai/keys |
   | `OPENROUTER_MODEL` | `openrouter/free` (or a pinned `:free` model) |
   | `ALLOWED_ORIGINS` | your Netlify URL, e.g. `https://your-site.netlify.app` (add it after step 4) |
   | `AUTO_INGEST_ON_STARTUP` | `false` if you committed `data/vectorstore/`, otherwise `true` |
   | `ADMIN_TOKEN` | optional — a random string, enables `POST /api/reingest` |
4. Deploy. Render will build the image from `backend/Dockerfile` and expose
   the service on a `https://<your-service>.onrender.com` URL.
5. Confirm: `curl https://<your-service>.onrender.com/api/health`

> Render's free web services spin down after inactivity and take ~30–60s to
> wake back up on the next request — the first chat message after idle time
> will be slow. That's expected on the free tier, not a bug.

---

## 4. Deploy the frontend on Netlify

1. In the [Netlify dashboard](https://app.netlify.com), click **Add new
   site → Import an existing project**, and pick the same GitHub repo.
2. Configure:
   - **Base directory:** `frontend`
   - **Build command:** `npm run build` (already set in `frontend/netlify.toml`)
   - **Publish directory:** `frontend/dist`
3. Add an environment variable: **Site configuration → Environment
   variables**
   | Key | Value |
   |---|---|
   | `VITE_API_URL` | your Render backend URL from step 3, e.g. `https://your-service.onrender.com` |
4. Deploy. Netlify gives you a `https://<random-name>.netlify.app` URL (you
   can rename it or attach a custom domain in site settings).
5. Go back to Render and set `ALLOWED_ORIGINS` to that exact Netlify URL,
   then redeploy the backend so CORS allows it.

---

## 5. Keeping the data fresh

Two options:

- **Manual (simplest):** re-run `python ingest.py` locally, commit the
  updated `data/`, push — Render redeploys automatically.
- **On-demand endpoint:** if you set `ADMIN_TOKEN`, you can trigger a live
  re-scrape without redeploying:
  ```bash
  curl -X POST https://<your-service>.onrender.com/api/reingest \
    -H "x-admin-token: <your ADMIN_TOKEN>"
  ```
  This re-scrapes both sites and rebuilds the FAISS index in place. It's
  slow (a minute or two) and uses real requests against both target sites,
  so don't put it on a tight schedule.

---

## API reference

`POST /api/chat`
```json
// request
{ "message": "villas for sale in Riyadh", "history": [{"role": "user", "content": "..."}] }
// response
{ "answer": "…", "sources": [{"title": "...", "url": "...", "source": "wasalt", "price": "...", "location": "..."}] }
```

`GET /api/health` → `{ "status": "ok" }`

`POST /api/reingest` (header `x-admin-token`) → `{ "darglobal_docs": N, "wasalt_docs": M }`

---

## Notes & limitations

- This indexes a **snapshot** of public listing pages, not a live feed —
  prices/availability can be stale. The system prompt tells the model to
  say so rather than assert stale data as current.
- The free OpenRouter tier is rate-limited (not "unlimited"); under heavy
  use you'll see occasional 429s bubble up as a 503 from `/api/chat`.
- The scrapers are intentionally generic/defensive rather than tied to
  exact CSS classes, since both sites are actively developed products —
  expect to revisit selectors occasionally.
