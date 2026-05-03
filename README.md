# Multi-Source Data Scraping & Trust Scoring System

A production-grade Python pipeline that scrapes content from **blogs**, **YouTube videos**, and **PubMed articles**, enriches each record with NLP-derived metadata, and assigns a quantitative **trust score**.

---

## Project Structure

```
scraping_system/
├── main.py                    # Orchestrator – run this
├── requirements.txt
├── scrapers/
│   ├── __init__.py
│   ├── blog_scraper.py        # Scrapes public blog posts
│   ├── youtube_scraper.py     # Extracts YouTube metadata + transcript
│   └── pubmed_scraper.py      # Fetches PubMed articles via Entrez API
├── modules/
│   ├── __init__.py
│   ├── tagging.py             # Keyword / topic-tag extraction
│   ├── chunking.py            # Content splitting into paragraphs
│   ├── trust_score.py         # Trust scoring formula
│   └── utils.py               # Shared helpers (lang detection, text cleaning)
└── output/
    └── results.json           # Generated output (6 records)
```

---

## Quick Start

### 1. Prerequisites

- Python 3.11+
- Internet access (scraper fetches live URLs)

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

NLTK data is downloaded automatically on first run.

### 3. Run the pipeline

```bash
python main.py
```

Output is written to `output/results.json`.

### 4. Customise sources

Edit the top of `main.py`:

```python
BLOG_URLS    = ["https://..."]
YOUTUBE_IDS  = ["VIDEO_ID", ...]   # 11-char ID or full URL
PUBMED_IDS   = ["PMID", ...]
```

---

## Output Schema

Each JSON record contains:

| Field | Type | Description |
|---|---|---|
| `source_url` | str | Canonical URL |
| `source_type` | str | `blog` / `youtube` / `pubmed` |
| `author` | str | Author(s); multiple joined with ` \| ` |
| `published_date` | str | ISO date or "unknown" |
| `language` | str | ISO 639-1 code (auto-detected) |
| `region` | str | Geographic region or "unknown" |
| `topic_tags` | list[str] | Up to 10 auto-generated keywords |
| `content_chunks` | list[str] | Paragraph-split content (max 50) |
| `trust_score` | float | 0.0 – 1.0 |

---

## Trust Score Formula

```
trust_score = Σ weight_i × sub_score_i

Sub-scores (each in [0, 1]):
  author_credibility  × 0.25   (source type, fake-author detection)
  citation_score      × 0.20   (logistic curve on citation count)
  domain_authority    × 0.20   (whitelist, TLD heuristics, HTTPS)
  recency_score       × 0.20   (exponential decay; > 5 years → 0.05)
  disclaimer_score    × 0.15   (medical disclaimer presence)

Penalties (multiplicative):
  × 0.90  if content < 300 chars
  × 0.90  if author unknown/flagged
  × 0.85  if YouTube video has no transcript
  → hard cap 0.10 for retracted PubMed articles
```

---

## Abuse Prevention

| Signal | Action |
|---|---|
| Domain in spam blocklist | Raises `ValueError` before fetching |
| Generic author (`admin`, `user`, …) | Flagged; `author_credibility = 0` |
| Content too short (< 200 chars) | Raises `ValueError` |
| Article retracted (PubMed) | `trust_score` hard-capped at 0.10 |
| Content older than 5 years | `recency_score = 0.05`; logged as warning |
| No YouTube transcript | 15% trust penalty |

---

## Edge Cases Handled

- **Missing date** → stored as `"unknown"`; recency defaults to neutral 0.40
- **Multiple authors** → joined as `"Author A | Author B (+ N more)"`
- **No transcript** → falls back to video title/description for content
- **PubMed no abstract** → falls back to article title
- **YAKE not installed** → gracefully falls back to NLTK, then pure Python
- **Network timeout** → caught, error stored in record, pipeline continues
- **Non-English content** → language detected, pipeline still runs

---

## Limitations

1. **Citation counts** – PubMed XML does not include citation counts in its Entrez feed. The `citation_count` field is `0` as a placeholder; a future enhancement could query the iCite API (`https://icite.od.nih.gov/api`).

2. **Domain Authority** – The current whitelist is hand-curated. A production system would integrate a commercial DA API (Moz, Ahrefs, SEMrush).

3. **YouTube metadata** – Without a Google API key, upload dates are unavailable from noembed. Recency scoring falls back to neutral.

4. **Region detection** – Not implemented for blogs. IP-to-region lookup or content-based detection would be needed.

5. **Rate limiting** – Runs sequentially. Production use should add async I/O and per-domain rate limiting.

6. **Transcript quality** – Auto-generated YouTube transcripts can contain errors that may reduce tagging quality.

---

## Dependencies

| Package | Purpose |
|---|---|
| `requests` | HTTP fetching |
| `beautifulsoup4` + `lxml` | HTML parsing |
| `youtube-transcript-api` | YouTube transcripts |
| `biopython` | PubMed Entrez API |
| `nltk` | Tokenisation, stop words |
| `yake` | Keyword extraction |
| `langdetect` | Language identification |
