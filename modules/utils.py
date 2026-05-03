import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)


def detect_language(text: str) -> str:
    """Return ISO 639-1 language code, or 'unknown' on failure."""
    if not text or len(text.strip()) < 20:
        return "unknown"
    try:
        from langdetect import detect, LangDetectException  # type: ignore
        return detect(text[:3000])
    except ImportError:
        logger.debug("langdetect not installed – language detection unavailable.")
        return "unknown"
    except Exception as exc:
        logger.debug("Language detection failed: %s", exc)
        return "unknown"


def safe_get_text(tag) -> str:
    """Safely extract stripped text from a BeautifulSoup tag."""
    if tag is None:
        return ""
    try:
        return tag.get_text(separator=" ").strip()
    except Exception:
        return ""


def clean_text(text: str) -> str:
    """
    Normalise whitespace, remove control characters, and strip leading/trailing
    blank lines from a text string.
    """
    if not text:
        return ""
    # Replace non-breaking spaces and common Unicode spaces
    text = text.replace("\u00a0", " ").replace("\u200b", "")
    # Collapse multiple spaces on the same line
    text = re.sub(r"[ \t]{2,}", " ", text)
    # Collapse 3+ consecutive newlines to 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def truncate(text: str, max_chars: int = 500) -> str:
    """Truncate text to max_chars with an ellipsis."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "…"
