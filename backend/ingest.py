"""
One-shot pipeline: scrape DarGlobal + Wasalt, then build the FAISS index.

Run this locally before your first deploy (and whenever you want fresh
data). Commit the resulting data/raw/*.json and data/vectorstore/ files to
git so Render doesn't have to scrape live sites on every cold start —
set AUTO_INGEST_ON_STARTUP=false once you do that.

    cd backend
    pip install -r requirements.txt
    python ingest.py
"""
from __future__ import annotations

import sys

from app import config
from app.ingest_pipeline import build_vectorstore
from scraper.scrape_darglobal import crawl as crawl_darglobal
from scraper.scrape_wasalt import crawl as crawl_wasalt
from scraper.utils import save_docs


def main() -> None:
    print("== Scraping DarGlobal (darglobal.co.uk) ==")
    dar_docs = crawl_darglobal()
    dar_path = config.RAW_DIR / "darglobal.json"
    save_docs(dar_docs, dar_path)
    print(f"Saved {len(dar_docs)} docs -> {dar_path}")

    print("\n== Scraping Wasalt (wasalt.sa) ==")
    wasalt_docs = crawl_wasalt()
    wasalt_path = config.RAW_DIR / "wasalt.json"
    save_docs(wasalt_docs, wasalt_path)
    print(f"Saved {len(wasalt_docs)} docs -> {wasalt_path}")

    total = len(dar_docs) + len(wasalt_docs)
    if total == 0:
        print(
            "\nNo documents were scraped (both sites returned nothing — check your "
            "network access / robots.txt / whether the sites changed markup).\n"
            "The vector store was NOT built. Fix the scrapers or add sample data "
            "under backend/data/raw/*.json and re-run."
        )
        sys.exit(1)

    print(f"\n== Building vector store from {total} documents ==")
    build_vectorstore()
    print(f"Done. Vector store saved to {config.VECTORSTORE_DIR}")


if __name__ == "__main__":
    main()
