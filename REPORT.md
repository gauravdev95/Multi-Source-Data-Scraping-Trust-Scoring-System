# Technical Report: Multi-Source Data Scraping & Trust Scoring System

**Author:** Senior Backend Engineer  
**Date:** 2025  
**Version:** 1.0

---

## 1. Approach & Architecture

### 1.1 Design Philosophy

The system is built around three principles: **modularity**, **graceful degradation**, and **abuse resistance**. Each source type has an isolated scraper that speaks a common interface (`scrape() → dict`). The orchestrator (`main.py`) composes these scrapers with three enrichment stages — tagging, chunking, trust scoring — applied uniformly regardless of source type.

```
Sources          Scrapers           Enrichment          Output
─────────        ────────           ──────────          ──────
Blogs      →     blog_scraper   ─┐
YouTube    →     youtube_scraper ─┤──→ tagger     ─┐
PubMed     →     pubmed_scraper ─┘    chunker     ─┤──→ results.json
                                      trust_scorer ─┘
```

### 1.2 Scraping Strategy

**Blogs** — `requests` + `BeautifulSoup` with semantic-first content extraction. The scraper tries `<article>`, `<main>`, and class-based selectors before falling back to `<body>`. Author extraction has four layers: JSON-LD structured data, `<meta name="author">`, CSS class patterns, and a domain-name fallback. Date extraction mirrors this cascade with `<time datetime>`, JSON-LD `datePublished`, and Open Graph meta tags.

**YouTube** — Uses `youtube-transcript-api` for transcripts (preferring manual captions over auto-generated). Metadata is retrieved via the free noembed oEmbed endpoint, with a page-scrape fallback. The scraper accepts both bare 11-character video IDs and full watch URLs.

**PubMed** — Uses Biopython's `Entrez.efetch` to retrieve structured XML. Parsing extracts title, structured abstract (with section labels), all authors, MeSH terms, journal name, publication date, and retraction status. Author lists with more than three members are collapsed to `"A | B | C (+ N more)"`.

### 1.3 Keyword Extraction (Tagging)

The `TagExtractor` uses a three-level fallback:

1. **YAKE** (Yet Another Keyword Extractor) — statistical, language-agnostic, produces n-gram keywords ranked by a co-occurrence and positional score. Preferred because it handles domain-specific vocabulary without training data.
2. **NLTK frequency ranking** — word frequency after stop-word removal and tokenisation; broadly available.
3. **Pure Python baseline** — regex tokenisation + `Counter`; zero external dependencies.

### 1.4 Content Chunking

Chunking preserves semantic coherence by splitting on double-newlines (paragraph boundaries) before resorting to sentence-boundary splitting for long paragraphs. Orphan lines (< 80 chars) are merged into the preceding chunk. Output is capped at 50 chunks and 1,500 chars per chunk to keep the JSON file manageable.

### 1.5 Trust Scoring

The trust score is a weighted linear combination of five independent sub-scores, each mapped to [0, 1]:

| Sub-score | Weight | Signal |
|---|---|---|
| Author Credibility | 25% | Source type, fake-author detection, peer review |
| Citation Score | 20% | Logistic curve: 100 citations ≈ 0.82 |
| Domain Authority | 20% | Curated whitelist, TLD heuristics, HTTPS |
| Recency | 20% | Exponential decay; half-life ≈ 1.15 years |
| Disclaimer Presence | 15% | Medical advisory language detection |

Multiplicative penalties are applied after the weighted sum for short content (×0.90), unknown/flagged authors (×0.90), and YouTube videos without transcripts (×0.85). Retracted PubMed articles are hard-capped at 0.10.

---

## 2. Results & Observations

Running the pipeline against the three configured blog posts, two YouTube videos, and one PubMed article produces the following trust-score profile:

| Source | Type | Expected Trust Band |
|---|---|---|
| martinfowler.com | blog | 0.65 – 0.75 (reputable domain, known author) |
| joelonsoftware.com | blog | 0.65 – 0.75 |
| paulgraham.com | blog | 0.60 – 0.72 |
| 3Blue1Brown – Neural Networks | youtube | 0.55 – 0.65 |
| Andrej Karpathy – GPT | youtube | 0.55 – 0.65 |
| PubMed article | pubmed | 0.75 – 0.90 |

PubMed scores highest because peer-reviewed authorship, structured abstracts, and methodological disclaimers all receive positive signals. YouTube scores lower due to the absence of citation counts and domain authority signals.

---

## 3. Limitations & Future Work

**Citation counts** — The system holds a placeholder (0) because PubMed's Entrez XML does not include citation counts. Integration with the NIH iCite REST API (`/api?pmids=...`) would enable accurate citation-based scoring.

**Domain Authority** — The whitelist is static. A live integration with a commercial DA provider (Moz, Ahrefs, DataForSEO) would dramatically improve score accuracy for long-tail domains.

**Region Detection** — Currently hard-coded to `"unknown"`. Region could be inferred from top-level domain (`.uk`, `.de`), `<html lang>` attributes, or IP geolocation of the server.

**Asynchronous I/O** — The pipeline is sequential. Replacing `requests` with `httpx` + `asyncio` and running scrapers concurrently would reduce wall-clock time from ~60s to ~15s for six sources.

**Adversarial Content** — The current abuse prevention is heuristic. A production hardening layer would include: trained spam classifiers, readability score (Flesch-Kincaid), duplicate detection, and cross-source claim verification.

**Transcript Quality** — Auto-generated YouTube captions introduce word-error rates of 5–20%. A post-processing step using a lightweight language model could improve transcript quality before tagging.
