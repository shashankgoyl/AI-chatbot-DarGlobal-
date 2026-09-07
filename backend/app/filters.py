"""
Structured filtering over the scraped listing metadata (source, location,
beds, price).

Kept separate from ingest_pipeline/rag_pipeline so retrieval and the
/api/filters endpoint share one source of truth for what's actually in the
data — the UI never offers a city, bed count, or currency that doesn't
exist in the current index.
"""
from __future__ import annotations

import json
import re
from typing import Optional

from . import config

_PRICE_NUM_RE = re.compile(r"[\d,]{4,}")
_CURRENCY_RE = re.compile(r"(AED|SAR|SR|USD|\$|EUR|€|£|GBP)", re.IGNORECASE)
_CURRENCY_ALIASES = {"SR": "SAR", "$": "USD", "€": "EUR", "£": "GBP"}


def parse_price(price: Optional[str]) -> tuple[Optional[str], Optional[float]]:
    """Best-effort split of a free-text price string into (currency, amount).

    Prices come from the scrapers as loose text (e.g. "AED 4,200,000"), so
    this is a heuristic used only to support range filtering — never shown
    back to the user as if it were verified structured data.
    """
    if not price:
        return None, None
    currency_match = _CURRENCY_RE.search(price)
    currency = (
        _CURRENCY_ALIASES.get(currency_match.group(1).upper(), currency_match.group(1).upper())
        if currency_match
        else None
    )
    num_match = _PRICE_NUM_RE.search(price)
    amount = float(num_match.group(0).replace(",", "")) if num_match else None
    return currency, amount


def _load_all_items() -> list[dict]:
    items: list[dict] = []
    if not config.RAW_DIR.exists():
        return items
    for json_path in sorted(config.RAW_DIR.glob("*.json")):
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(data, list):
            items.extend(data)
    return items


def get_filter_options() -> dict:
    """Distinct filter values actually present in the current scrape."""
    items = _load_all_items()
    sources = sorted({i.get("source") for i in items if i.get("source")})
    locations = sorted({i["location"] for i in items if i.get("location")})
    beds = sorted({i["beds"] for i in items if i.get("beds")})
    currencies = sorted({c for i in items if (c := parse_price(i.get("price"))[0])})
    return {
        "sources": sources,
        "locations": locations,
        "beds": beds,
        "currencies": currencies,
    }


def matches_filters(metadata: dict, filters: Optional[dict]) -> bool:
    if not filters:
        return True

    source = filters.get("source")
    if source and metadata.get("source") != source:
        return False

    location = filters.get("location")
    if location and location.lower() not in (metadata.get("location") or "").lower():
        return False

    beds = filters.get("beds")
    if beds and beds.lower() not in (metadata.get("beds") or "").lower():
        return False

    price_min = filters.get("price_min")
    price_max = filters.get("price_max")
    price_currency = filters.get("price_currency")
    if price_min is not None or price_max is not None or price_currency:
        currency, amount = parse_price(metadata.get("price"))
        if amount is None:
            return False  # can't confirm it's in range, so exclude rather than guess
        if price_currency and currency != price_currency:
            return False
        if price_min is not None and amount < price_min:
            return False
        if price_max is not None and amount > price_max:
            return False

    return True
