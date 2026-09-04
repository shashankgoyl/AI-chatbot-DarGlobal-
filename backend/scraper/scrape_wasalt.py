"""
Scraper for publicly available listing pages on wasalt.sa (Wasalt).

Wasalt is a searchable property portal, so the approach differs from the
DarGlobal scraper:

  1. Visit a configurable list of public category/listing pages (e.g.
     "villas for sale in Riyadh"), each of which is paginated.
  2. Collect links to individual `/en/property/...` detail pages.
  3. Visit each detail page and pull title, price, location and a short
     description out of the readable text.

Wasalt's listing markup may change over time (it's a live, actively
developed product) — the regexes below are intentionally forgiving
(price/location are pulled from the page text rather than a specific
CSS class) so the scraper degrades gracefully instead of breaking
outright. If Wasalt ships a redesign, re-inspect a live page and adjust
`LISTING_LINK_PATTERN` / `parse_detail_page` accordingly.

Usage:
    python -m scraper.scrape_wasalt
"""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .utils import (
    ScrapedDoc,
    clean_text,
    extract_main_text,
    fetch,
    guess_beds,
    guess_price,
    save_docs,
)

BASE_URL = "https://wasalt.sa"

# A handful of public, high-signal category pages. Add/remove freely —
# each one is a normal category listing page and fully public.
CATEGORY_PATHS = [
    "/en/villas-for-sale-in-riyadh",
    "/en/villas-for-sale-in-jeddah",
    "/en/apartments-for-sale-in-riyadh",
    "/en/apartments-for-sale-in-jeddah",
    "/en/properties-for-sale-in-riyadh",
    "/en/properties-for-sale-in-jeddah",
    "/en/buildings-for-sale-in-saudi-arabia",
    "/en/lands-for-sale-in-riyadh",
]

PAGES_PER_CATEGORY = 2          # how many result pages to walk per category
MAX_LISTINGS_TOTAL = 120        # hard cap so a run stays fast & polite

LISTING_LINK_PATTERN = re.compile(r"/en/property/(sale|rent)/[a-z0-9\-]+", re.IGNORECASE)


def collect_listing_links(category_path: str) -> list[str]:
    links: set[str] = set()
    for page in range(1, PAGES_PER_CATEGORY + 1):
        url = urljoin(BASE_URL, category_path) + (f"?page={page}" if page > 1 else "")
        html = fetch(url)
        if not html:
            continue
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.find_all("a", href=True):
            if LISTING_LINK_PATTERN.search(a["href"]):
                links.add(urljoin(BASE_URL, a["href"].split("?")[0]))
    return sorted(links)


def parse_detail_page(url: str, html: str) -> ScrapedDoc | None:
    soup = BeautifulSoup(html, "html.parser")

    title_tag = soup.find("h1") or soup.find("title")
    title = clean_text(title_tag.get_text()) if title_tag else url

    meta_desc_tag = soup.find("meta", attrs={"property": "og:description"}) or soup.find(
        "meta", attrs={"name": "description"}
    )
    meta_desc = clean_text(meta_desc_tag["content"]) if meta_desc_tag and meta_desc_tag.get("content") else ""

    body_text = extract_main_text(soup, max_chars=3000)
    full_text = f"{title}. {meta_desc} {body_text}".strip()

    if len(full_text) < 60:
        return None

    # Location is frequently rendered right after the title as an h6/h5
    # breadcrumb-style line ("Al Ruwase, South Jeddah, Jeddah").
    location = None
    loc_tag = soup.find(["h5", "h6"])
    if loc_tag:
        candidate = clean_text(loc_tag.get_text())
        if 2 < len(candidate) < 120:
            location = candidate

    listing_id = url.rstrip("/").split("-")[-1]
    listing_id = listing_id if listing_id.isdigit() else re.sub(r"[^a-z0-9]+", "-", url.lower())[-12:]

    return ScrapedDoc(
        id=f"wasalt-{listing_id}",
        source="wasalt",
        url=url,
        title=title or "Wasalt property",
        content=full_text,
        price=guess_price(full_text),
        beds=guess_beds(full_text),
        location=location,
        extra={"meta_description": meta_desc},
    )


def crawl() -> list[ScrapedDoc]:
    docs: list[ScrapedDoc] = []
    seen_urls: set[str] = set()

    for category_path in CATEGORY_PATHS:
        if len(docs) >= MAX_LISTINGS_TOTAL:
            break
        for link in collect_listing_links(category_path):
            if len(docs) >= MAX_LISTINGS_TOTAL:
                break
            if link in seen_urls:
                continue
            seen_urls.add(link)

            html = fetch(link)
            if not html:
                continue
            doc = parse_detail_page(link, html)
            if doc:
                docs.append(doc)
                print(f"[ok] {link} -> price={doc.price} loc={doc.location}")

    return docs


if __name__ == "__main__":
    out_path = Path(__file__).resolve().parent.parent / "data" / "raw" / "wasalt.json"
    docs = crawl()
    n = save_docs(docs, out_path)
    print(f"Saved {n} Wasalt documents -> {out_path}")
