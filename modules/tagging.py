import logging
import re
import string
from collections import Counter
from typing import Optional

logger = logging.getLogger(__name__)

# NLTK resources are downloaded lazily
_NLTK_READY = False


def _ensure_nltk() -> None:
    global _NLTK_READY
    if _NLTK_READY:
        return
    import nltk
    for resource in ("stopwords", "punkt", "punkt_tab"):
        try:
            nltk.data.find(f"tokenizers/{resource}")
        except LookupError:
            nltk.download(resource, quiet=True)
    _NLTK_READY = True


class TagExtractor:
    """Extract up to `max_tags` representative keywords from free-form text."""

    def __init__(self, max_tags: int = 10, language: str = "en") -> None:
        self.max_tags = max_tags
        self.language = language

    def extract(self, text: str) -> list[str]:
        if not text or not text.strip():
            return []
        text = text[:50_000]   # cap to avoid memory issues

        # 1. YAKE
        tags = self._yake(text)
        if tags:
            return tags

        # 2. NLTK frequency
        tags = self._nltk_frequency(text)
        if tags:
            return tags

        # 3. Baseline
        return self._baseline(text)

    # ── YAKE ─────────────────────────────────────────────────────────────────
    def _yake(self, text: str) -> list[str]:
        try:
            import yake  # type: ignore
            kw_extractor = yake.KeywordExtractor(
                lan=self.language,
                n=2,             # unigrams + bigrams
                dedupLim=0.7,
                top=self.max_tags,
            )
            keywords = kw_extractor.extract_keywords(text)
            # YAKE returns (keyword, score) – lower score = more relevant
            return [kw for kw, _ in keywords]
        except ImportError:
            logger.debug("yake not installed; skipping.")
            return []
        except Exception as exc:
            logger.warning("YAKE extraction failed: %s", exc)
            return []

    # ── NLTK Frequency ────────────────────────────────────────────────────────
    def _nltk_frequency(self, text: str) -> list[str]:
        try:
            _ensure_nltk()
            from nltk.tokenize import word_tokenize
            from nltk.corpus import stopwords

            stop = set(stopwords.words("english"))
            tokens = word_tokenize(text.lower())
            words  = [
                w for w in tokens
                if w.isalpha() and len(w) > 3 and w not in stop
            ]
            most_common = Counter(words).most_common(self.max_tags)
            return [w for w, _ in most_common]
        except Exception as exc:
            logger.warning("NLTK frequency extraction failed: %s", exc)
            return []

    # ── Baseline ──────────────────────────────────────────────────────────────
    def _baseline(self, text: str) -> list[str]:
        """Pure Python fallback: frequency after basic stop-word removal."""
        STOP = {
            "the", "a", "an", "and", "or", "but", "is", "are", "was",
            "were", "be", "been", "being", "have", "has", "had", "do",
            "does", "did", "will", "would", "could", "should", "may",
            "might", "shall", "can", "that", "this", "these", "those",
            "it", "its", "of", "in", "on", "at", "to", "for", "with",
            "by", "from", "as", "into", "through", "about", "than",
            "so", "if", "then", "not", "no", "nor", "only", "such",
            "also", "more", "just", "like", "they", "them", "their",
        }
        words = re.findall(r"[a-z]{4,}", text.lower())
        filtered = [w for w in words if w not in STOP]
        return [w for w, _ in Counter(filtered).most_common(self.max_tags)]
