import json
import logging
from datetime import datetime
from pathlib import Path

from scrapers.blog_scraper import BlogScraper
from scrapers.youtube_scraper import YouTubeScraper
from scrapers.pubmed_scraper import PubMedScraper
from modules.tagging import TagExtractor
from modules.chunking import ContentChunker
from modules.trust_score import TrustScorer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

# ── Sources to scrape ──────────────────────────────────────────────────────────
BLOG_URLS = [
    "https://martinfowler.com/articles/microservices.html",
    "https://www.joelonsoftware.com/2002/11/11/the-law-of-leaky-abstractions/",
    "https://paulgraham.com/greatwork.html",
]

YOUTUBE_IDS = [
    "aircAruvnKk",   # 3Blue1Brown – Neural Networks
    "kCc8FmEb1nY",   # Andrej Karpathy – GPT from scratch
]

PUBMED_IDS = [
    "37234567",       # recent article; fallback handled in scraper
]


def run_pipeline() -> list[dict]:
    """Run all scrapers and enrich each record."""
    tagger  = TagExtractor()
    chunker = ContentChunker()
    scorer  = TrustScorer()

    records: list[dict] = []

    # ── Blogs ──────────────────────────────────────────────────────────────────
    blog_scraper = BlogScraper()
    for url in BLOG_URLS:
        logger.info("Scraping blog: %s", url)
        try:
            record = blog_scraper.scrape(url)
            record = _enrich(record, tagger, chunker, scorer)
            records.append(record)
        except Exception as exc:
            logger.error("Blog scrape failed for %s: %s", url, exc)
            records.append(_error_record(url, "blog", str(exc)))

    # ── YouTube ───────────────────────────────────────────────────────────────
    yt_scraper = YouTubeScraper()
    for vid_id in YOUTUBE_IDS:
        logger.info("Scraping YouTube: %s", vid_id)
        try:
            record = yt_scraper.scrape(vid_id)
            record = _enrich(record, tagger, chunker, scorer)
            records.append(record)
        except Exception as exc:
            logger.error("YouTube scrape failed for %s: %s", vid_id, exc)
            records.append(_error_record(
                f"https://www.youtube.com/watch?v={vid_id}", "youtube", str(exc)
            ))

    # ── PubMed ────────────────────────────────────────────────────────────────
    pm_scraper = PubMedScraper()
    for pmid in PUBMED_IDS:
        logger.info("Scraping PubMed PMID: %s", pmid)
        try:
            record = pm_scraper.scrape(pmid)
            record = _enrich(record, tagger, chunker, scorer)
            records.append(record)
        except Exception as exc:
            logger.error("PubMed scrape failed for PMID %s: %s", pmid, exc)
            records.append(_error_record(
                f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/", "pubmed", str(exc)
            ))

    return records


def _enrich(record: dict, tagger: TagExtractor,
            chunker: ContentChunker, scorer: TrustScorer) -> dict:
    """Apply tagging, chunking and trust scoring to a raw record."""
    full_text = record.get("raw_content", "")
    record["topic_tags"]     = tagger.extract(full_text)
    record["content_chunks"] = chunker.chunk(full_text)
    record["trust_score"]    = scorer.score(record)
    record.pop("raw_content", None)          # remove large raw field from output
    return record


def _error_record(url: str, source_type: str, error: str) -> dict:
    """Return a minimal record when scraping completely fails."""
    return {
        "source_url":    url,
        "source_type":   source_type,
        "author":        "unknown",
        "published_date": "unknown",
        "language":      "unknown",
        "region":        "unknown",
        "topic_tags":    [],
        "content_chunks": [],
        "trust_score":   0.0,
        "error":         error,
    }


def save_output(records: list[dict], path: str = "output/results.json") -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(records, fh, indent=2, ensure_ascii=False, default=str)
    logger.info("Saved %d records to %s", len(records), path)


if __name__ == "__main__":
    logger.info("=== Multi-Source Scraping Pipeline START ===")
    results = run_pipeline()
    save_output(results)
    logger.info("=== Pipeline COMPLETE – %d records written ===", len(results))
