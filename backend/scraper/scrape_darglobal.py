"""
Scraper for publicly available pages on darglobal.co.uk (DarGlobal PLC).

DarGlobal's site is a fairly standard marketing site (projects, insights,
press releases) rather than a searchable property portal, so this scraper
works as a small polite crawler:

  1. Start from a handful of public seed pages (homepage + known section
     roots).
  2. Follow same-domain links that look like project / insight / press
     pages, up to MAX_PAGES.
  3. Pull the page title, meta description and main visible text.
  4. Try to pull a launch price / bed count out of the text if present
     (DarGlobal project pages often mention "Launch price: X AED" and
     "1 - 4 Beds" style copy).

Because marketing sites restyle fairly often, the text extraction here is
intentionally generic (readable body text) rather than tied to specific
CSS classes. If you want structured fields (exact price, delivery date,
etc.) inspect the live page HTML and tighten `parse_detail_page`.

Usage:
    python -m scraper.scrape_darglobal
"""
from __future__ import annotations

import re
from pathlib import Path

from bs4 import BeautifulSoup

from .utils import (
    ScrapedDoc,
    absolute_links,
    clean_text,
    extract_main_text,
    fetch,
    guess_beds,
    guess_price,
    save_docs,
)

BASE_URL = "https://darglobal.co.uk"
SEED_PATHS = [
    "/",
    "/our-projects",
    "/insights",
    "/press",
]

# Links worth following: project pages, insight articles, press releases.
LINK_PATTERN = re.compile(r"/(our-projects|projects|insights|press)/[a-z0-9\-]+", re.IGNORECASE)

MAX_PAGES = 40  # keep the crawl small and polite by default


def parse_detail_page(url: str, html: str) -> ScrapedDoc | None:
    soup = BeautifulSoup(html, "html.parser")

    title_tag = soup.find("h1") or soup.find("title")
    title = clean_text(title_tag.get_text()) if title_tag else url

    meta_desc_tag = soup.find("meta", attrs={"name": "description"})
    meta_desc = clean_text(meta_desc_tag["content"]) if meta_desc_tag and meta_desc_tag.get("content") else ""

    body_text = extract_main_text(soup)
    full_text = f"{meta_desc} {body_text}".strip()

    if len(full_text) < 80:
        # Too thin to be useful (nav-only page, redirect stub, etc.)
        return None

    doc_id = re.sub(r"[^a-z0-9]+", "-", urlpath(url).lower()).strip("-") or "darglobal-home"

    return ScrapedDoc(
        id=f"darglobal-{doc_id}",
        source="darglobal",
        url=url,
        title=title or "DarGlobal",
        content=full_text,
        price=guess_price(full_text),
        beds=guess_beds(full_text),
        location=None,
        extra={"meta_description": meta_desc},
    )


def urlpath(url: str) -> str:
    from urllib.parse import urlparse

    return urlparse(url).path


def crawl() -> list[ScrapedDoc]:
    seen: set[str] = set()
    to_visit: list[str] = [BASE_URL + p for p in SEED_PATHS]
    docs: list[ScrapedDoc] = []

    while to_visit and len(seen) < MAX_PAGES:
        url = to_visit.pop(0)
        if url in seen:
            continue
        seen.add(url)

        html = fetch(url)
        if not html:
            continue

        doc = parse_detail_page(url, html)
        if doc:
            docs.append(doc)
            print(f"[ok] {url} -> {len(doc.content)} chars")

        # Discover more same-site links to follow.
        for link in absolute_links(html, BASE_URL, LINK_PATTERN):
            if link not in seen and link.startswith(BASE_URL):
                to_visit.append(link)

    return docs


if __name__ == "__main__":
    out_path = Path(__file__).resolve().parent.parent / "data" / "raw" / "darglobal.json"
    docs = crawl()
    n = save_docs(docs, out_path)
    print(f"Saved {n} DarGlobal documents -> {out_path}")
