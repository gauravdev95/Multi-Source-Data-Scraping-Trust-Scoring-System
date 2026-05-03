"""
blog_scraper.py – Scrapes public blog posts with BeautifulSoup.

Handles:
- Multiple author formats (by-line, meta tags, JSON-LD)
- Missing dates  → "unknown"
- Language auto-detection fallback
- Spam / low-quality domain abuse prevention
"""

import logging
import re
import time
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from modules.utils import detect_language, safe_get_text, clean_text

logger = logging.getLogger(__name__)

# ── Abuse-prevention: known spam / content-farm TLDs and domains ──────────────
BLOCKLIST_DOMAINS = {
    "content-farm.com", "spammy-blog.net", "articlesubmit.biz",
    "ezinearticles.com", "hubpages.com",   # low editorial quality
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; TrustScorerBot/1.0; "
        "+https://github.com/example/trust-scorer)"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}
REQUEST_TIMEOUT = 15
MIN_CONTENT_LENGTH = 200   # chars – reject suspiciously short pages


class BlogScraper:
    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update(HEADERS)

    # ─────────────────────────────────────────────────────────────────────────
    def scrape(self, url: str) -> dict:
        domain = urlparse(url).netloc.lstrip("www.")
        if domain in BLOCKLIST_DOMAINS:
            raise ValueError(f"Domain '{domain}' is blocklisted (spam prevention).")

        resp = self._fetch(url)
        soup = BeautifulSoup(resp.text, "html.parser")

        raw_content = self._extract_content(soup)
        if len(raw_content) < MIN_CONTENT_LENGTH:
            raise ValueError(
                f"Content too short ({len(raw_content)} chars). "
                "Possible paywall or scrape-block."
            )

        return {
            "source_url":   url,
            "source_type":  "blog",
            "author":       self._extract_author(soup, url),
            "published_date": self._extract_date(soup),
            "language":     detect_language(raw_content),
            "region":       "unknown",            # blogs rarely expose region
            "domain":       domain,               # used by trust scorer
            "raw_content":  raw_content,
        }

    # ── Network ───────────────────────────────────────────────────────────────
    def _fetch(self, url: str) -> requests.Response:
        try:
            resp = self._session.get(url, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            raise RuntimeError(f"HTTP error fetching {url}: {exc}") from exc

    # ── Author ────────────────────────────────────────────────────────────────
    def _extract_author(self, soup: BeautifulSoup, url: str) -> str:
        """Try multiple heuristics; collapse multiple authors to a list string."""
        candidates: list[str] = []

        # 1. JSON-LD structured data
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                import json
                data = json.loads(script.string or "")
                for item in ([data] if isinstance(data, dict) else data):
                    author = item.get("author")
                    if isinstance(author, str):
                        candidates.append(author)
                    elif isinstance(author, dict):
                        candidates.append(author.get("name", ""))
                    elif isinstance(author, list):
                        candidates.extend(
                            a.get("name", "") if isinstance(a, dict) else str(a)
                            for a in author
                        )
            except Exception:
                pass

        # 2. <meta name="author">
        meta = soup.find("meta", attrs={"name": re.compile(r"author", re.I)})
        if meta and meta.get("content"):
            candidates.append(meta["content"])

        # 3. Common CSS classes / itemprop
        for sel in ["[rel='author']", "[class*='author']", "[itemprop='author']"]:
            for tag in soup.select(sel):
                txt = safe_get_text(tag)
                if txt:
                    candidates.append(txt)

        # 4. Fallback: domain organisation name
        if not candidates:
            candidates.append(urlparse(url).netloc.lstrip("www.").split(".")[0].title())

        # De-duplicate, strip empties, collapse
        seen, clean = set(), []
        for c in candidates:
            c = clean_text(c)
            if c and c not in seen:
                seen.add(c)
                clean.append(c)

        # Abuse check: suspiciously generic author names
        if clean and clean[0].lower() in {"admin", "administrator", "user", "author"}:
            logger.warning("Generic/fake author detected: '%s'", clean[0])
            return "unknown (flagged)"

        return " | ".join(clean[:3]) if clean else "unknown"

    # ── Date ──────────────────────────────────────────────────────────────────
    def _extract_date(self, soup: BeautifulSoup) -> str:
        # 1. <time> tag
        time_tag = soup.find("time")
        if time_tag:
            dt = time_tag.get("datetime") or safe_get_text(time_tag)
            if dt:
                return dt.strip()

        # 2. JSON-LD datePublished
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                import json
                data = json.loads(script.string or "")
                for item in ([data] if isinstance(data, dict) else data):
                    dp = item.get("datePublished") or item.get("dateModified")
                    if dp:
                        return dp
            except Exception:
                pass

        # 3. Meta tags
        for name in ("article:published_time", "og:published_time", "pubdate"):
            m = soup.find("meta", attrs={"property": name}) or \
                soup.find("meta", attrs={"name": name})
            if m and m.get("content"):
                return m["content"]

        return "unknown"

    # ── Content ───────────────────────────────────────────────────────────────
    def _extract_content(self, soup: BeautifulSoup) -> str:
        # Remove boilerplate
        for tag in soup(["script", "style", "nav", "footer",
                          "header", "aside", "form", "noscript"]):
            tag.decompose()

        # Prefer semantic content containers
        for sel in ["article", "main", "[role='main']",
                    ".post-content", ".entry-content", ".article-body"]:
            el = soup.select_one(sel)
            if el:
                return clean_text(el.get_text(separator="\n"))

        # Fallback: whole body
        body = soup.find("body")
        return clean_text(body.get_text(separator="\n") if body else "")
