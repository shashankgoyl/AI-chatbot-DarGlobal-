"""
Shared helpers for the DarGlobal / Wasalt scrapers.

Design goals:
- Be polite: custom User-Agent, request delay, timeout, small retry budget.
- Respect robots.txt for the target host before crawling anything.
- Only ever touch publicly reachable pages (no login walls, no bypassing
  paywalls / CAPTCHAs). If a site blocks us, we stop rather than work
  around the block.
- Produce clean, structured JSON so the ingestion pipeline downstream
  doesn't have to deal with HTML at all.
"""
from __future__ import annotations

import json
import re
import time
import urllib.robotparser as robotparser
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

USER_AGENT = (
    "GrowBroResearchBot/1.0 (+https://github.com/; contact: set-your-email-here) "
    "Python-requests"
)
DEFAULT_TIMEOUT = 15
DEFAULT_DELAY_SECONDS = 1.5  # be nice to the target servers
MAX_RETRIES = 2

_session = requests.Session()
_session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en"})

_robots_cache: dict[str, robotparser.RobotFileParser] = {}


def _robots_for(url: str) -> robotparser.RobotFileParser:
    parsed = urlparse(url)
    root = f"{parsed.scheme}://{parsed.netloc}"
    if root not in _robots_cache:
        rp = robotparser.RobotFileParser()
        rp.set_url(urljoin(root, "/robots.txt"))
        try:
            rp.read()
        except Exception:
            # If robots.txt can't be fetched, default to a conservative
            # "allow nothing extra" posture is overkill; treat as allowed
            # but log nothing further (requests below will fail naturally
            # if the site is unreachable).
            pass
        _robots_cache[root] = rp
    return _robots_cache[root]


def allowed_by_robots(url: str) -> bool:
    """Check the target host's robots.txt before fetching `url`."""
    try:
        rp = _robots_for(url)
        return rp.can_fetch(USER_AGENT, url)
    except Exception:
        # Fail open on parser errors, fail closed would block everything;
        # we choose to proceed cautiously since robots.txt fetch itself failed.
        return True


def fetch(url: str, delay: float = DEFAULT_DELAY_SECONDS) -> Optional[str]:
    """GET a URL politely. Returns HTML text or None if blocked/failed."""
    if not allowed_by_robots(url):
        print(f"[skip] robots.txt disallows: {url}")
        return None

    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = _session.get(url, timeout=DEFAULT_TIMEOUT)
            if resp.status_code == 200 and "text/html" in resp.headers.get("Content-Type", ""):
                time.sleep(delay)
                return resp.text
            if resp.status_code in (429, 503):
                time.sleep(delay * (attempt + 2))
                continue
            print(f"[skip] {resp.status_code} for {url}")
            return None
        except requests.RequestException as exc:
            print(f"[retry {attempt}] {url} -> {exc}")
            time.sleep(delay)
    return None


def clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text


def extract_main_text(soup: BeautifulSoup, max_chars: int = 6000) -> str:
    """Best-effort extraction of the readable body text of a page."""
    for tag in soup(["script", "style", "noscript", "svg", "form", "nav", "footer"]):
        tag.decompose()

    main = soup.find("main") or soup.find("article") or soup.body or soup
    text = clean_text(main.get_text(separator=" "))
    return text[:max_chars]


PRICE_RE = re.compile(
    r"(AED|SAR|SR|USD|\$|EUR|€|£|GBP)\s?[\d,]{4,}|"
    r"[\d,]{4,}\s?(AED|SAR|SR|USD|EUR|GBP)",
    re.IGNORECASE,
)
BEDS_RE = re.compile(r"(studio|\d+\s?[-–]?\s?\d*\s?bed(room)?s?)", re.IGNORECASE)


def guess_price(text: str) -> Optional[str]:
    m = PRICE_RE.search(text)
    return clean_text(m.group(0)) if m else None


def guess_beds(text: str) -> Optional[str]:
    m = BEDS_RE.search(text)
    return clean_text(m.group(0)) if m else None


def absolute_links(html: str, base_url: str, href_pattern: re.Pattern) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href_pattern.search(href):
            links.add(urljoin(base_url, href.split("?")[0]))
    return sorted(links)


@dataclass
class ScrapedDoc:
    id: str
    source: str          # "darglobal" | "wasalt"
    url: str
    title: str
    content: str
    price: Optional[str] = None
    location: Optional[str] = None
    beds: Optional[str] = None
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def save_docs(docs: Iterable[ScrapedDoc], path: str | Path) -> int:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [d.to_dict() for d in docs]
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(payload)
