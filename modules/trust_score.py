import logging
import math
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
WEIGHTS = {
    "author_credibility": 0.25,
    "citation_score":     0.20,
    "domain_authority":   0.20,
    "recency_score":      0.20,
    "disclaimer_score":   0.15,
}
assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9

# High-authority domains (heuristic whitelist)
TRUSTED_DOMAINS = {
    "nature.com", "nejm.org", "sciencedirect.com", "pubmed.ncbi.nlm.nih.gov",
    "who.int", "cdc.gov", "nih.gov", "bmj.com", "thelancet.com",
    "martinfowler.com", "paulgraham.com", "joelonsoftware.com",
    "youtube.com",              # YouTube baseline trust
    "arxiv.org", "ieee.org", "acm.org", "springer.com",
}
MEDIUM_TRUST_TLDS = {".edu", ".gov", ".org"}

SPAM_DOMAINS = {
    "content-farm.com", "spammy-blog.net", "click-bait-news.xyz",
    "free-articles.info", "seoarticle.biz",
}
FAKE_AUTHOR_TOKENS = {
    "admin", "administrator", "user", "author", "editor",
    "webmaster", "anonymous", "unknown (flagged)",
}

MEDICAL_DISCLAIMER_PATTERNS = [
    r"consult\s+(a\s+)?physician",
    r"not\s+medical\s+advice",
    r"consult\s+(your\s+)?doctor",
    r"healthcare\s+professional",
    r"talk\s+to\s+your\s+doctor",
    r"for\s+informational\s+purposes\s+only",
    r"disclaimer",
]


class TrustScorer:
    def score(self, record: dict) -> float:
        if record.get("is_retracted"):
            logger.warning(
                "Source %s is retracted – trust capped at 0.10", record.get("source_url")
            )
            return 0.10

        sub_scores = {
            "author_credibility": self._author_credibility(record),
            "citation_score":     self._citation_score(record),
            "domain_authority":   self._domain_authority(record),
            "recency_score":      self._recency_score(record),
            "disclaimer_score":   self._disclaimer_score(record),
        }

        raw = sum(WEIGHTS[k] * v for k, v in sub_scores.items())

        # Penalties
        raw = self._apply_penalties(raw, record)

        trust = round(max(0.0, min(1.0, raw)), 4)
        logger.debug("Trust scores for %s: %s → %.4f", record.get("source_url"), sub_scores, trust)
        return trust

    # ── Sub-scores ────────────────────────────────────────────────────────────
    def _author_credibility(self, record: dict) -> float:
        author = (record.get("author") or "").lower().strip()

        if not author or author == "unknown":
            return 0.2

        # Check for fake/generic authors
        for token in FAKE_AUTHOR_TOKENS:
            if token in author:
                logger.warning("Fake/generic author detected: '%s'", author)
                return 0.0

        # PubMed articles carry peer-reviewed authorship
        if record.get("source_type") == "pubmed":
            return 0.90

        # YouTube: verified channels get higher credibility
        if record.get("source_type") == "youtube":
            return 0.65   # reasonable baseline; no API key for verification

        # Blog: multiple authors slightly better than single unknown
        n_authors = len(author.split("|"))
        return min(0.80, 0.50 + 0.10 * n_authors)

    def _citation_score(self, record: dict) -> float:
        count = record.get("citation_count", 0) or 0
        # Logistic normalisation; 100 citations ≈ 0.80
        return round(1 / (1 + math.exp(-0.05 * (count - 20))), 4)

    def _domain_authority(self, record: dict) -> float:
        url    = record.get("source_url", "")
        domain = urlparse(url).netloc.lstrip("www.")

        if domain in SPAM_DOMAINS:
            logger.warning("Spam domain detected: %s", domain)
            return 0.0

        if domain in TRUSTED_DOMAINS:
            return 0.95

        tld = "." + domain.rsplit(".", 1)[-1] if "." in domain else ""
        if tld in MEDIUM_TRUST_TLDS:
            return 0.75

        # HTTPS presence adds modest trust
        return 0.55 if url.startswith("https://") else 0.35

    def _recency_score(self, record: dict) -> float:
        date_str = record.get("published_date", "unknown")
        if not date_str or date_str == "unknown":
            return 0.40   # neutral when unknown

        year = self._extract_year(date_str)
        if year is None:
            return 0.40

        now       = datetime.now(timezone.utc)
        age_years = (now.year - year) + (now.month - 1) / 12.0

        if age_years > 5:
            logger.warning(
                "Content at %s may be outdated (age ~%.1f years)",
                record.get("source_url"), age_years
            )
            return 0.05

        # Exponential decay: fresh (0 y) = 1.0, 5 y = ~0.05
        return round(math.exp(-0.60 * age_years), 4)

    def _disclaimer_score(self, record: dict) -> float:
        """Presence of medical disclaimer is a positive trust signal for health content."""
        source_type = record.get("source_type", "")
        if source_type == "pubmed":
            return 1.0   # peer-reviewed articles implicitly carry methodological disclaimers

        content = " ".join(
            record.get("content_chunks") or [record.get("raw_content", "")]
        ).lower()

        for pat in MEDICAL_DISCLAIMER_PATTERNS:
            if re.search(pat, content):
                return 0.85

        return 0.50   # absence of disclaimer is neutral, not negative

    # ── Penalties ─────────────────────────────────────────────────────────────
    def _apply_penalties(self, score: float, record: dict) -> float:
        chunks = record.get("content_chunks", [])
        total_chars = sum(len(c) for c in chunks)

        # Suspiciously short content
        if total_chars < 300:
            logger.warning(
                "Very short content (%d chars) at %s – applying penalty.",
                total_chars, record.get("source_url")
            )
            score *= 0.90

        # Unknown / flagged author
        author = (record.get("author") or "").lower()
        if "unknown" in author or "flagged" in author:
            score *= 0.90

        # YouTube without transcript – less verifiable
        if record.get("source_type") == "youtube" and \
                not record.get("transcript_available", True):
            score *= 0.85

        return score

    # ── Utility ───────────────────────────────────────────────────────────────
    @staticmethod
    def _extract_year(date_str: str) -> int | None:
        match = re.search(r"\b(19|20)\d{2}\b", str(date_str))
        return int(match.group()) if match else None
