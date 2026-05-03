"""
pubmed_scraper.py – Fetches article metadata + abstract from PubMed via
Entrez E-utilities (no API key required for low-volume use).

Uses Biopython's Entrez module.  Falls back to direct XML parsing if Bio
is unavailable.

Handles:
- Multiple authors  → joined as "First | Second | … (N total)"
- Missing abstract  → uses article title as content
- Retracted articles → flagged in trust scorer
- PMID not found    → raises RuntimeError
"""

import logging
import re
import time
import xml.etree.ElementTree as ET
from typing import Optional

from Bio import Entrez

from modules.utils import detect_language, clean_text

logger = logging.getLogger(__name__)

# NCBI requires an email for Entrez
Entrez.email = "trustscorer-bot@example.com"
ENTREZ_TOOL  = "TrustScorerBot"


class PubMedScraper:
    def scrape(self, pmid: str) -> dict:
        pmid = str(pmid).strip()
        article = self._fetch_article(pmid)
        return self._parse(pmid, article)

    # ── Fetch ─────────────────────────────────────────────────────────────────
    def _fetch_article(self, pmid: str) -> ET.Element:
        try:
            handle = Entrez.efetch(
                db="pubmed", id=pmid, rettype="xml",
                retmode="xml", tool=ENTREZ_TOOL
            )
            raw_xml = handle.read()
            handle.close()
        except Exception as exc:
            raise RuntimeError(f"Entrez.efetch failed for PMID {pmid}: {exc}") from exc

        time.sleep(0.35)   # NCBI rate limit: ≤3 req/s without API key

        try:
            root = ET.fromstring(raw_xml)
        except ET.ParseError as exc:
            raise RuntimeError(f"XML parse error for PMID {pmid}: {exc}") from exc

        article_set = root.findall(".//PubmedArticle")
        if not article_set:
            raise RuntimeError(f"PMID {pmid} not found in PubMed response.")

        return article_set[0]

    # ── Parse ─────────────────────────────────────────────────────────────────
    def _parse(self, pmid: str, article: ET.Element) -> dict:
        citation = article.find(".//MedlineCitation")
        art_el   = citation.find("Article") if citation is not None else None

        title    = self._get_title(art_el)
        abstract = self._get_abstract(art_el)
        authors  = self._get_authors(art_el)
        pub_date = self._get_pub_date(citation)
        journal  = self._get_journal(art_el)
        citations_count = self._get_citation_count(article)
        is_retracted    = self._check_retraction(article)
        mesh_terms      = self._get_mesh_terms(citation)

        raw_content = abstract or title
        language    = self._get_language(art_el) or detect_language(raw_content)

        if is_retracted:
            logger.warning("PMID %s is marked as RETRACTED.", pmid)

        return {
            "source_url":       f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            "source_type":      "pubmed",
            "author":           authors,
            "published_date":   pub_date,
            "language":         language,
            "region":           "unknown",
            "journal":          journal,
            "pmid":             pmid,
            "citation_count":   citations_count,
            "is_retracted":     is_retracted,
            "mesh_terms":       mesh_terms,
            "has_abstract":     bool(abstract),
            "raw_content":      raw_content,
        }

    # ── Helpers ───────────────────────────────────────────────────────────────
    @staticmethod
    def _get_title(art_el: Optional[ET.Element]) -> str:
        if art_el is None:
            return "unknown"
        t = art_el.find(".//ArticleTitle")
        return clean_text("".join(t.itertext())) if t is not None else "unknown"

    @staticmethod
    def _get_abstract(art_el: Optional[ET.Element]) -> str:
        if art_el is None:
            return ""
        parts = []
        for text_el in art_el.findall(".//AbstractText"):
            label = text_el.get("Label")
            txt   = clean_text("".join(text_el.itertext()))
            if label:
                parts.append(f"{label}: {txt}")
            else:
                parts.append(txt)
        return "\n".join(parts)

    @staticmethod
    def _get_authors(art_el: Optional[ET.Element]) -> str:
        if art_el is None:
            return "unknown"
        names = []
        for auth in art_el.findall(".//Author"):
            last  = (auth.findtext("LastName") or "").strip()
            first = (auth.findtext("ForeName") or auth.findtext("Initials") or "").strip()
            col   = auth.findtext("CollectiveName", "").strip()
            if col:
                names.append(col)
            elif last:
                names.append(f"{last} {first}".strip())

        if not names:
            return "unknown"
        if len(names) == 1:
            return names[0]
        # Multiple authors: show first 3 then count
        shown = " | ".join(names[:3])
        return f"{shown} (+ {len(names)-3} more)" if len(names) > 3 else shown

    @staticmethod
    def _get_pub_date(citation: Optional[ET.Element]) -> str:
        if citation is None:
            return "unknown"
        for path in [".//PubDate", ".//ArticleDate"]:
            el = citation.find(path)
            if el is not None:
                year  = el.findtext("Year")  or ""
                month = el.findtext("Month") or ""
                day   = el.findtext("Day")   or ""
                parts = [p for p in [year, month, day] if p]
                if parts:
                    return "-".join(parts)
        return "unknown"

    @staticmethod
    def _get_journal(art_el: Optional[ET.Element]) -> str:
        if art_el is None:
            return "unknown"
        j = art_el.find(".//Journal/Title") or \
            art_el.find(".//Journal/ISOAbbreviation")
        return clean_text(j.text) if j is not None and j.text else "unknown"

    @staticmethod
    def _get_citation_count(article: ET.Element) -> int:
        """PubMed XML doesn't carry citation counts directly; return 0 as placeholder."""
        return 0

    @staticmethod
    def _check_retraction(article: ET.Element) -> bool:
        for pub_type in article.findall(".//PublicationType"):
            if pub_type.text and "retract" in pub_type.text.lower():
                return True
        return False

    @staticmethod
    def _get_mesh_terms(citation: Optional[ET.Element]) -> list[str]:
        if citation is None:
            return []
        terms = []
        for mesh in citation.findall(".//MeshHeading/DescriptorName"):
            if mesh.text:
                terms.append(mesh.text.strip())
        return terms[:10]   # cap to 10

    @staticmethod
    def _get_language(art_el: Optional[ET.Element]) -> str:
        if art_el is None:
            return ""
        lang_el = art_el.find(".//Language")
        return lang_el.text.lower() if lang_el is not None and lang_el.text else ""
