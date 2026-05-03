"""
youtube_scraper.py – Extracts metadata + transcript from YouTube videos.

Handles:
- Transcript unavailable (auto-generated vs manual)
- Private / deleted videos
- Multiple-author / channel verification
- Age-restricted content (graceful fail)
"""

import logging
import re
from typing import Optional

import requests
from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled

from modules.utils import detect_language, clean_text

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    )
}
YT_WATCH = "https://www.youtube.com/watch?v={vid_id}"
NOEMBED   = "https://noembed.com/embed?url=" + YT_WATCH   # lightweight oEmbed


class YouTubeScraper:
    def scrape(self, video_id: str) -> dict:
        video_id = self._sanitise_id(video_id)
        metadata = self._fetch_metadata(video_id)
        transcript, language = self._fetch_transcript(video_id)

        if transcript is None:
            logger.warning("Transcript unavailable for %s; falling back to description.", video_id)

        raw_content = transcript or metadata.get("description", "")
        if not raw_content or not raw_content.strip():
            raw_content = "No content available"
            logger.warning("YouTube content empty for %s; using default placeholder.", video_id)

        if not language or language == "unknown":
            language = detect_language(raw_content)

        logger.info("YouTube content length for %s: %d chars", video_id, len(raw_content))

        return {
            "source_url":     YT_WATCH.format(vid_id=video_id),
            "source_type":    "youtube",
            "author":         metadata.get("channel", "unknown"),
            "published_date": metadata.get("upload_date", "unknown"),
            "language":       language,
            "region":         "unknown",
            "channel_id":     metadata.get("channel_id", ""),
            "view_count":     metadata.get("view_count", 0),
            "transcript_available": bool(transcript),
            "raw_content":    raw_content,
        }

    # ── Sanitise ─────────────────────────────────────────────────────────────
    @staticmethod
    def _sanitise_id(video_id: str) -> str:
        """Accept full URL or bare ID."""
        match = re.search(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})", video_id)
        if match:
            return match.group(1)
        if re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
            return video_id
        raise ValueError(f"Cannot parse YouTube video ID from: '{video_id}'")

    # ── Metadata ─────────────────────────────────────────────────────────────
    def _fetch_metadata(self, video_id: str) -> dict:
        """
        Primary:  noembed (no API key needed).
        Fallback: parse <meta> tags from watch page.
        """
        try:
            resp = requests.get(
                NOEMBED.format(vid_id=video_id), headers=HEADERS, timeout=10
            )
            resp.raise_for_status()
            data = resp.json()
            if "error" in data:
                raise ValueError(data["error"])
            return {
                "channel":     data.get("author_name", "unknown"),
                "channel_id":  "",
                "upload_date": "unknown",   # noembed doesn't expose date
                "view_count":  0,
                "description": data.get("title", ""),
            }
        except Exception as e:
            logger.warning("noembed failed (%s); falling back to page scrape.", e)
            return self._scrape_watch_page(video_id)

    def _scrape_watch_page(self, video_id: str) -> dict:
        from bs4 import BeautifulSoup
        url = YT_WATCH.format(vid_id=video_id)
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(f"Cannot fetch YouTube watch page: {exc}") from exc

        soup = BeautifulSoup(resp.text, "html.parser")

        def meta_value(attr_name: str, attr: str = "name") -> str:
            tag = soup.find("meta", attrs={attr: attr_name})
            return tag["content"].strip() if tag and tag.get("content") else ""

        def itemprop_value(prop_name: str) -> str:
            tag = soup.find(attrs={"itemprop": prop_name})
            return tag["content"].strip() if tag and tag.get("content") else ""

        channel = meta_value("author") or itemprop_value("author") or itemprop_value("name")
        if not channel:
            channel = meta_value("og:site_name", "property")
        channel = self._normalize_author(channel)

        desc = meta_value("og:description", "property") or meta_value("description") or ""
        pub_date = meta_value("uploadDate") or "unknown"

        if not channel or channel == "unknown":
            logger.warning("Unable to extract author name for %s; using unknown.", video_id)
        if not desc:
            logger.warning("YouTube description missing for %s; content may be limited.", video_id)

        return {
            "channel":     channel or "unknown",
            "channel_id":  "",
            "upload_date": pub_date,
            "view_count":  0,
            "description": desc,
        }

    @staticmethod
    def _normalize_author(author: str) -> str:
        author = author.split("|")[0].split("-")[0].split("•")[0].strip()
        author = re.sub(r"\s*\bYouTube\b.*$", "", author, flags=re.IGNORECASE).strip()
        if len(author) > 64:
            author = author[:64].rstrip()
        return author or "unknown"

    # ── Transcript ────────────────────────────────────────────────────────────
    def _fetch_transcript(self, video_id: str) -> tuple[Optional[str], str]:
        """Return (full_text, language_code). Returns (None, 'unknown') on failure."""
        try:
            if hasattr(YouTubeTranscriptApi, "get_transcript"):
                return self._fetch_transcript_with_get(video_id)
            return self._fetch_transcript_with_list(video_id)
        except (NoTranscriptFound, TranscriptsDisabled) as exc:
            logger.warning("Transcript disabled/not found for %s: %s", video_id, exc)
            return None, "unknown"
        except Exception as exc:
            logger.error("Unexpected transcript error for %s: %s", video_id, exc)
            return None, "unknown"

    def _fetch_transcript_with_get(self, video_id: str) -> tuple[Optional[str], str]:
        transcript_data = None
        language_code = "unknown"

        for lang in ["en", "en-US", "en-GB"]:
            try:
                transcript_data = YouTubeTranscriptApi.get_transcript(video_id, languages=[lang])
                language_code = lang
                break
            except (NoTranscriptFound, TranscriptsDisabled):
                raise
            except Exception:
                continue

        if transcript_data is None:
            transcript_data = YouTubeTranscriptApi.get_transcript(video_id)

        return self._normalize_transcript_data(video_id, transcript_data, language_code)

    def _fetch_transcript_with_list(self, video_id: str) -> tuple[Optional[str], str]:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        transcript_obj = None
        language_code = "unknown"

        for method in ("find_transcript", "find_generated_transcript", "find_transcripts"):
            try:
                transcript_obj = getattr(transcript_list, method)(["en"])
                language_code = "en"
                break
            except Exception:
                continue

        if transcript_obj is None:
            for transcript in transcript_list:
                transcript_obj = transcript
                language_code = getattr(transcript, "language_code", "unknown")
                break

        if transcript_obj is None:
            raise NoTranscriptFound(f"No transcript found for {video_id}")

        transcript_data = transcript_obj.fetch()
        return self._normalize_transcript_data(video_id, transcript_data, language_code)

    def _normalize_transcript_data(
        self, video_id: str, transcript_data: list[dict], language_code: str
    ) -> tuple[Optional[str], str]:
        if not transcript_data:
            logger.warning("No transcript content returned for video %s", video_id)
            return None, "unknown"

        text = " ".join(item.get("text", "") for item in transcript_data)
        text = clean_text(text)
        if not text.strip():
            logger.warning("Transcript text empty for %s after fetching.", video_id)
            return None, "unknown"

        logger.info(
            "Transcript fetched for %s (%d chars, lang=%s)",
            video_id, len(text), language_code
        )
        return text, language_code
