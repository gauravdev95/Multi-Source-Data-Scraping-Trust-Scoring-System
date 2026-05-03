import re
from typing import Generator

MIN_CHUNK_CHARS   = 80    # discard chunks shorter than this
MAX_CHUNK_CHARS   = 1500  # split chunks longer than this at sentence boundary
MAX_CHUNKS        = 50    # cap output to avoid huge JSON blobs


class ContentChunker:
    def __init__(
        self,
        min_chars: int = MIN_CHUNK_CHARS,
        max_chars: int = MAX_CHUNK_CHARS,
        max_chunks: int = MAX_CHUNKS,
    ) -> None:
        self.min_chars  = min_chars
        self.max_chars  = max_chars
        self.max_chunks = max_chunks

    def chunk(self, text: str) -> list[str]:
        if not text or not text.strip():
            return []

        raw_chunks = self._split_paragraphs(text)
        refined    = []

        for chunk in raw_chunks:
            chunk = chunk.strip()
            if len(chunk) < self.min_chars:
                continue
            if len(chunk) > self.max_chars:
                refined.extend(self._split_long(chunk))
            else:
                refined.append(chunk)

        return refined[: self.max_chunks]

    # ── Paragraph split ───────────────────────────────────────────────────────
    def _split_paragraphs(self, text: str) -> list[str]:
        """Split on 2+ consecutive newlines."""
        paragraphs = re.split(r"\n{2,}", text)
        merged: list[str] = []
        buffer = ""

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            # Merge very short consecutive lines into one chunk
            if len(para) < self.min_chars and buffer:
                buffer += " " + para
            else:
                if buffer:
                    merged.append(buffer)
                buffer = para

        if buffer:
            merged.append(buffer)

        return merged

    # ── Long chunk splitter ───────────────────────────────────────────────────
    def _split_long(self, text: str) -> list[str]:
        """Split at sentence boundaries without breaking mid-sentence."""
        # Sentence-ending punctuation followed by space and capital letter
        sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z\"])", text)
        chunks: list[str] = []
        current = ""

        for sent in sentences:
            if len(current) + len(sent) + 1 <= self.max_chars:
                current = (current + " " + sent).strip() if current else sent
            else:
                if current:
                    chunks.append(current)
                current = sent

        if current:
            chunks.append(current)

        # If no split occurred (single monster sentence), hard-cut
        if not chunks:
            chunks = [
                text[i : i + self.max_chars]
                for i in range(0, len(text), self.max_chars)
            ]

        return [c.strip() for c in chunks if len(c.strip()) >= self.min_chars]
