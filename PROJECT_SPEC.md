# SCLib_JZIS — Project Specification for Claude Code
> **Version:** 1.0 | **Date:** 2026-04-14 | **Author:** Jian Zhou / JZIS
> **Repo:** https://github.com/JackZH26/SCLib_JZIS
> **Domain:** jzis.org/sclib
> **Status:** Ready to build

---

## 0. Project Overview

**SCLib_JZIS** (JZIS Superconductivity Library) is the superconductivity field's equivalent of **Semantic Scholar + Materials Project + AI assistant**, unified in one open-source platform.

### What it does
- **Semantic search** over 200,000+ superconductivity papers (1986–present, daily updates)
- **Materials database** with structured Tc, pressure, and experimental data
- **AI-powered Q&A** (RAG) citing specific papers as sources
- **Open REST API** for researchers, AI agents, and ML pipelines

### Why it matters
- NIMS SuperCon database went offline in 2021 — no active public materials DB exists
- No domain-specific semantic search for superconductivity
- Mathlib-inspired: machine-verifiable, community-contributed, continuously updated

---

## 1. Tech Stack (Authoritative — Do Not Change Without Approval)

| Layer | Technology | Notes |
|-------|-----------|-------|
| **Frontend** | Next.js 14 (App Router) + Tailwind CSS + shadcn/ui | SSR for SEO |
| **Frontend Deploy** | Vercel | Free tier, global CDN |
| **API** | FastAPI (Python 3.11) | Async, auto OpenAPI docs |
| **API Deploy** | Google Cloud Run | Serverless, pay-per-request |
| **Vector DB** | **Vertex AI Vector Search** | Managed, no ops overhead |
| **Document DB** | Google Cloud Firestore | Serverless, real-time |
| **Object Storage** | Google Cloud Storage | PDFs + parsed text + chunks |
| **Embedding Model** | Vertex AI `text-embedding-005` (768d) | Best for scientific text |
| **LLM (RAG)** | Gemini 2.5 Flash | Cost-efficient, context-aware |
| **LLM (NER)** | Gemini 2.5 Flash | Material extraction from papers |
| **LaTeX Parser** | Custom Python + Pandoc | arXiv source files preferred |
| **PDF Fallback** | `opendataloader-pdf` v2.2.0 | When LaTeX unavailable |
| **CI/CD** | GitHub Actions | Auto test + deploy |
| **Package Manager** | `uv` (Python) + `pnpm` (Node) | Fast installs |

### GCP Services Required
```
Vertex AI (Vector Search + Embedding + Gemini)
Cloud Run
Cloud Firestore (Native mode, nam5 region)
Cloud Storage
Cloud Build (for CI/CD)
Secret Manager (API keys)
```

---

## 2. Repository Structure

```
SCLib_JZIS/
├── README.md
├── CONTRIBUTING.md
├── LICENSE                          # Apache 2.0
├── .github/
│   └── workflows/
│       ├── deploy-api.yml           # API → Cloud Run
│       ├── deploy-frontend.yml      # Frontend → Vercel
│       ├── test.yml                 # Run tests on PR
│       └── ingest-daily.yml        # Daily arXiv update cron
├── api/                             # FastAPI backend
│   ├── pyproject.toml               # uv project file
│   ├── Dockerfile
│   ├── main.py                      # FastAPI app entry
│   ├── routers/
│   │   ├── search.py                # POST /search
│   │   ├── ask.py                   # POST /ask
│   │   ├── materials.py             # GET /materials
│   │   ├── papers.py                # GET /paper/{id}
│   │   ├── stats.py                 # GET /stats
│   │   ├── similar.py               # GET /similar/{id}
│   │   └── timeline.py              # GET /timeline
│   ├── services/
│   │   ├── vector_search.py         # Vertex AI Vector Search client
│   │   ├── firestore.py             # Firestore CRUD
│   │   ├── embedding.py             # text-embedding-005 client
│   │   ├── gemini.py                # RAG + NER Gemini client
│   │   └── storage.py               # GCS client
│   ├── models/
│   │   ├── paper.py                 # Paper Pydantic models
│   │   ├── material.py              # Material Pydantic models
│   │   ├── search.py                # Search request/response models
│   │   └── ask.py                   # RAG request/response models
│   └── tests/
│       ├── test_search.py
│       ├── test_ask.py
│       └── test_materials.py
├── ingestion/                       # Data pipeline
│   ├── pyproject.toml
│   ├── collect/
│   │   ├── arxiv_oai.py             # arXiv OAI-PMH bulk + incremental
│   │   └── semantic_scholar.py      # S2 API metadata enrichment
│   ├── parse/
│   │   ├── latex_parser.py          # arXiv .tar.gz source parsing
│   │   └── pdf_parser.py            # opendataloader-pdf fallback
│   ├── chunk/
│   │   └── chunker.py               # Section-aware 512-token chunks
│   ├── embed/
│   │   └── embedder.py              # Batch embedding via Vertex AI
│   ├── index/
│   │   └── indexer.py               # Upsert to Vertex AI Vector Search
│   ├── extract/
│   │   └── material_ner.py          # Gemini-based material NER
│   └── pipeline.py                  # End-to-end orchestration
├── frontend/                        # Next.js app
│   ├── package.json
│   ├── next.config.ts
│   ├── tailwind.config.ts
│   ├── app/
│   │   ├── layout.tsx               # Root layout
│   │   ├── page.tsx                 # Dashboard homepage
│   │   ├── search/
│   │   │   └── page.tsx             # Semantic search page
│   │   ├── ask/
│   │   │   └── page.tsx             # AI Q&A chat page
│   │   ├── materials/
│   │   │   ├── page.tsx             # Materials database browser
│   │   │   └── [formula]/
│   │   │       └── page.tsx         # Material detail page
│   │   ├── paper/
│   │   │   └── [id]/
│   │   │       └── page.tsx         # Paper detail page
│   │   ├── timeline/
│   │   │   └── page.tsx             # Tc records timeline
│   │   ├── stats/
│   │   │   └── page.tsx             # Statistics dashboard
│   │   ├── api-docs/
│   │   │   └── page.tsx             # Embedded Swagger UI
│   │   └── about/
│   │       └── page.tsx             # About + citation
│   └── components/
│       ├── ui/                      # shadcn/ui components
│       ├── SearchBar.tsx
│       ├── PaperCard.tsx
│       ├── MaterialTable.tsx
│       ├── TcTimeline.tsx           # Plotly.js timeline
│       ├── ChatInterface.tsx        # RAG chat UI
│       └── StatsCards.tsx
├── scripts/
│   ├── setup_gcp.sh                 # GCP project setup
│   ├── init_firestore.py            # Create Firestore indexes
│   ├── create_vector_index.py       # Create Vertex AI VS index
│   └── import_nims.py               # Import NIMS SuperCon CSV
└── docs/
    ├── API.md                       # Full API reference
    ├── INGESTION.md                 # Pipeline documentation
    └── DEPLOYMENT.md               # Deployment guide
```

---

## 3. Data Models (Exact Schemas)

### 3.1 Paper (Firestore: `papers/{paper_id}`)

```python
# models/paper.py
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

class MaterialRecord(BaseModel):
    formula: str
    tc_kelvin: Optional[float]
    tc_type: Optional[str]  # "onset" | "zero_resistance" | "midpoint"
    pressure_gpa: Optional[float]
    measurement: Optional[str]  # "resistivity" | "susceptibility" | "specific_heat"
    verified: bool = False
    confidence: float  # 0.0-1.0

class Paper(BaseModel):
    id: str                          # "arxiv:2306.07275" or "doi:10.1038/..."
    source: str                      # "arxiv" | "semantic_scholar" | "crossref"
    arxiv_id: Optional[str]
    doi: Optional[str]
    title: str
    authors: List[str]
    affiliations: Optional[List[str]]
    date_submitted: Optional[str]    # ISO date string
    date_published: Optional[str]
    journal: Optional[str]
    abstract: str
    categories: List[str]            # ["cond-mat.supr-con"]
    material_family: Optional[str]   # "cuprate"|"hydride"|"nickelate"|"iron_based"|"topological"|"2d_moire"|"kagome"|"conventional"|"other"
    status: str = "published"        # "published" | "retracted" | "preprint"
    retraction_date: Optional[str]
    retraction_reason: Optional[str]
    citation_count: int = 0
    references_count: int = 0
    chunk_count: int = 0
    materials_extracted: List[MaterialRecord] = []
    quality_flags: List[str] = []    # ["retracted", "disputed", "high_impact"]
    indexed_at: datetime
    updated_at: datetime
```

### 3.2 Material (Firestore: `materials/{material_id}`)

```python
# models/material.py
class TcRecord(BaseModel):
    tc_kelvin: float
    tc_type: str                     # "onset" | "zero_resistance"
    pressure_gpa: float              # 0.0 = ambient
    measurement_method: str
    sample_form: str                 # "single_crystal" | "polycrystal" | "thin_film"
    paper_id: str
    year: int
    verified: bool
    notes: Optional[str]

class Material(BaseModel):
    id: str                          # normalized formula, e.g. "La3Ni2O7"
    formula: str                     # "La₃Ni₂O₇" (unicode)
    formula_normalized: str          # "La3Ni2O7" (ASCII, for ID)
    formula_latex: str               # "La_3Ni_2O_7"
    family: str
    subfamily: Optional[str]
    crystal_structure: Optional[str]
    records: List[TcRecord]
    tc_max: Optional[float]
    tc_max_conditions: Optional[str]
    tc_ambient: Optional[float]      # highest Tc at 0 GPa
    pairing_symmetry: Optional[str]
    discovery_year: Optional[int]
    total_papers: int = 0
    status: str = "active_research"  # "active_research" | "confirmed" | "retracted"
```

### 3.3 Vector Chunk (Vertex AI Vector Search)

Each chunk stored as a vector with metadata:

```python
# Vertex AI datapoint structure
{
    "datapoint_id": "arxiv:2306.07275_chunk_005",   # unique ID
    "feature_vector": [...],                          # 768-dim float32
    "restricts": [                                    # for filtering
        {"namespace": "material_family", "allow_list": ["nickelate"]},
        {"namespace": "year", "allow_list": ["2023"]},
    ],
    "numeric_restricts": [
        {"namespace": "tc_max", "value_float": 80.0},
        {"namespace": "pressure_min", "value_float": 14.0},
    ],
    # crowding_tag for diversity
    "crowding_tag": {"value": "arxiv:2306.07275"}    # max 1 chunk per paper in top-k
}
```

Firestore `chunks/{chunk_id}` stores the text payload:
```python
{
    "id": "arxiv:2306.07275_chunk_005",
    "paper_id": "arxiv:2306.07275",
    "title": str,
    "authors_short": str,          # "Sun et al."
    "year": int,
    "section": str,                # "Results"
    "chunk_index": int,
    "text": str,                   # actual chunk text, max 512 tokens
    "material_family": str,
    "materials_mentioned": List[str],
    "has_equation": bool,
    "has_table": bool,
}
```

### 3.4 Stats Cache (Firestore: `stats/global`)

```python
{
    "total_papers": int,
    "total_materials": int,
    "total_chunks": int,
    "earliest_paper": {"id": str, "title": str, "date": str, "authors": List[str]},
    "latest_paper": {"id": str, "title": str, "date": str},
    "last_updated": datetime,
    "papers_by_year": Dict[str, int],
    "papers_by_family": Dict[str, int],
    "tc_hall_of_fame": List[{
        "rank": int, "material": str, "tc": float,
        "pressure": str, "year": int, "family": str
    }]
}
```

---

## 4. API Specification (FastAPI)

**Base URL:** `https://api.jzis.org/sclib/v1`
**Auth:** `X-API-Key: <key>` header (free registration) or anonymous (100 req/day)

### 4.1 POST /search

```python
# Request
class SearchRequest(BaseModel):
    query: str                          # natural language query
    top_k: int = 20                     # max 100
    filters: Optional[SearchFilters]
    sort: str = "relevance"             # "relevance" | "date_desc" | "citations_desc"
    include_chunks: bool = True         # include matched text snippet

class SearchFilters(BaseModel):
    year_min: Optional[int]
    year_max: Optional[int]
    material_family: Optional[List[str]]
    tc_min: Optional[float]             # minimum Tc in Kelvin
    pressure_max: Optional[float]       # max pressure in GPa (0 = ambient only)
    exclude_retracted: bool = True
    status: Optional[List[str]]

# Response
class SearchResponse(BaseModel):
    total: int
    results: List[SearchResult]
    query_time_ms: int

class SearchResult(BaseModel):
    paper_id: str
    title: str
    authors: List[str]
    year: int
    journal: Optional[str]
    relevance_score: float
    matched_chunk: Optional[str]        # best matching text snippet
    materials: List[dict]               # extracted materials with Tc
    citation_count: int
    status: str
    arxiv_url: Optional[str]
    doi_url: Optional[str]
```

**Implementation:** Embed query with `text-embedding-005`, query Vertex AI VS with filters, fetch chunk text from Firestore, fetch paper metadata from Firestore, merge and return.

### 4.2 POST /ask

```python
# Request
class AskRequest(BaseModel):
    question: str
    max_sources: int = 10
    filters: Optional[SearchFilters]    # same as search
    language: str = "auto"             # "auto" | "en" | "zh"
    model: str = "gemini-2.5-flash"

# Response
class AskResponse(BaseModel):
    answer: str                         # markdown formatted
    sources: List[AskSource]
    tokens_used: int
    model: str
    query_time_ms: int

class AskSource(BaseModel):
    paper_id: str
    title: str
    authors_short: str
    year: int
    relevance: float
    matched_text: str                   # the chunk used
```

**Implementation:**
1. Embed question → retrieve top 10 chunks from VS
2. Build RAG prompt with retrieved chunks + citation markers [1], [2], etc.
3. Call Gemini 2.5 Flash with system prompt enforcing citation format
4. Parse response, attach source metadata, return

**RAG System Prompt:**
```
You are SCLib, an AI research assistant specialized in superconductivity.
Answer based ONLY on the provided papers. Cite sources as [1], [2], etc.
Be precise about Tc values, pressures, and material formulas.
If the answer is not in the provided papers, say so clearly.
Distinguish between theoretical predictions and experimental measurements.
Language: {language}
```

### 4.3 GET /materials

```
GET /materials?family=nickelate&tc_min=50&pressure_max=0&sort=tc_desc&limit=50&offset=0
```

Query params: `family`, `tc_min`, `tc_max`, `pressure_min`, `pressure_max`, `year_min`, `year_max`, `sort` (`tc_desc`|`tc_asc`|`papers_desc`|`year_asc`), `limit` (max 200), `offset`

Returns paginated list of Material objects with summary fields.

### 4.4 GET /materials/{formula}

URL-encoded formula, e.g. `/materials/La3Ni2O7`

Returns full Material object including all TcRecords, timeline, related materials.

### 4.5 GET /paper/{id}

`/paper/arxiv:2306.07275` or `/paper/doi:10.1038/s41586-023-06408-7`

Returns full Paper object with all fields.

### 4.6 GET /similar/{paper_id}

```
GET /similar/arxiv:2306.07275?top_k=10
```

Returns top-k similar papers using average chunk vector of the given paper.

### 4.7 GET /stats

Returns global stats cache from Firestore. Refreshed daily by cron.

### 4.8 GET /timeline

```
GET /timeline?family=all&ambient_only=false
```

Returns array of `{year, material, formula, tc, pressure_gpa, paper_id, family}` sorted by date, suitable for frontend visualization.

---

## 5. Ingestion Pipeline

### 5.1 Chunking Strategy

```python
# chunk/chunker.py

MAX_TOKENS = 512
OVERLAP_TOKENS = 64
MIN_CHUNK_TOKENS = 100

def chunk_paper(parsed: dict) -> List[dict]:
    """
    Section-aware chunking:
    1. Split by \section{} boundaries first
    2. Within each section, slide with 512-token window + 64-token overlap
    3. Preserve equations as atomic units (never split mid-equation)
    4. Prepend "Title: {title}\nSection: {section}\n" to each chunk for context
    5. Skip reference list sections
    """
```

### 5.2 Embedding Batch Size

Vertex AI `text-embedding-005` supports batch up to 250 texts per request.
Use batch embedding with exponential backoff on rate limits.

```python
# embed/embedder.py
BATCH_SIZE = 250
DIMENSIONS = 768
MODEL = "text-embedding-005"
TASK_TYPE = "RETRIEVAL_DOCUMENT"  # for indexing; use RETRIEVAL_QUERY for queries
```

### 5.3 Vertex AI Vector Search Index Configuration

```python
# scripts/create_vector_index.py
index_config = {
    "display_name": "sclib-papers-v1",
    "description": "SCLib paper chunks, 768d, ~1.5M vectors",
    "metadata": {
        "contentsDeltaUri": "gs://sclib-jzis/vs-index/",
        "config": {
            "dimensions": 768,
            "approximateNeighborsCount": 150,
            "distanceMeasureType": "DOT_PRODUCT_DISTANCE",
            "algorithm_config": {
                "treeAhConfig": {
                    "leafNodeEmbeddingCount": 1000,
                    "leafNodesToSearchPercent": 7
                }
            }
        }
    }
}

# Deploy to endpoint for serving
endpoint_config = {
    "display_name": "sclib-papers-endpoint",
    "public_endpoint_enabled": True
}
```

### 5.4 Material NER Prompt

```python
MATERIAL_NER_PROMPT = """
Extract superconducting materials from this text. Return JSON array only.
For each material found, extract:
- formula: chemical formula (e.g., "La3Ni2O7")  
- tc_kelvin: critical temperature in Kelvin (null if not stated)
- tc_type: "onset" | "zero_resistance" | "midpoint" | "unknown"
- pressure_gpa: pressure in GPa (0.0 if ambient, null if not stated)
- measurement: "resistivity" | "susceptibility" | "specific_heat" | "unknown"
- confidence: 0.0-1.0

Rules:
- Only extract materials explicitly measured for superconductivity
- Do not invent data not in the text
- Flag unusual Tc values (>300K or <0.1K) with confidence < 0.3
- Distinguish theoretical predictions from experimental measurements

Text:
{text}

Return: [{...}, {...}] or [] if no materials found.
"""
```

### 5.5 Daily Update Cron (GitHub Actions)

```yaml
# .github/workflows/ingest-daily.yml
name: Daily arXiv Ingestion
on:
  schedule:
    - cron: '0 6 * * *'    # 6 AM UTC = 2 PM UTC+8
  workflow_dispatch:

jobs:
  ingest:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run incremental ingestion
        run: |
          cd ingestion
          uv run pipeline.py --mode incremental --date yesterday
        env:
          GOOGLE_APPLICATION_CREDENTIALS: ${{ secrets.GCP_SA_KEY }}
          GCP_PROJECT: ${{ secrets.GCP_PROJECT }}
```

---

## 6. Frontend Pages Specification

### 6.1 Homepage (`/`) — Dashboard

**Components:**
- `StatsCards` — 4 cards: Total Papers, Total Materials, Coverage Start (1986), Last Updated
- `SearchBar` — large, centered, placeholder: "Search 200K+ superconductivity papers..."
- `TcTimeline` — interactive Plotly.js chart, Tc records 1986–present
- `FamilyGrid` — 8 material families with paper counts, click → /search?family=X
- `LatestPapers` — last 5 indexed papers from /stats endpoint
- `QuickAsk` — small prompt box linking to /ask

### 6.2 Search Page (`/search`)

**Layout:** Sidebar filters + main results grid

**Sidebar filters:**
- Year range slider (1986–2026)
- Material family checkboxes (8 options)
- Min Tc slider (0–300K)
- Max pressure slider (0–200 GPa)
- Exclude retracted toggle (default: on)

**Result card:** Title, authors (truncated), year, journal, relevance badge, Tc pill(s), matched text snippet with query highlighting, arXiv/DOI links

**Pagination:** 20 per page, infinite scroll or page buttons

### 6.3 Ask Page (`/ask`)

Chat interface. Each exchange:
- User message bubble
- Assistant response (markdown rendered, citations as superscript links)
- Collapsible "Sources" section showing paper cards
- Copy button on responses

### 6.4 Materials Page (`/materials`)

Sortable, filterable table:
- Columns: Formula, Family, Tc Max, Pressure, Year, Papers
- Clicking formula → /materials/{formula}
- Export CSV button
- Quick filter bar at top

### 6.5 Material Detail Page (`/materials/{formula}`)

- Header: formula (large), family badge, Tc max chip
- Tc Records table: all records with conditions, paper links
- Timeline chart: Tc over time (papers reporting this material)
- Related materials section
- Recent papers mentioning this material (from /search)

### 6.6 Timeline Page (`/timeline`)

- Interactive Plotly.js scatter plot
- X: year, Y: Tc (K), color: family, size: citation count
- Toggle: All / Ambient pressure only / Per family
- Hover: material card with paper link
- Annotation markers for milestone events (YBCO 1987, H3S 2015, etc.)

### 6.7 Stats Page (`/stats`)

- Papers by year bar chart
- Papers by family pie chart
- Tc Hall of Fame table (top 20 highest Tc)
- Coverage stats (earliest/latest paper)

---

## 7. Environment Variables

### API Service (Cloud Run)
```bash
GCP_PROJECT=jzis-sclib
GCP_REGION=us-central1
VERTEX_AI_INDEX_ENDPOINT=projects/.../locations/.../indexEndpoints/...
VERTEX_AI_DEPLOYED_INDEX_ID=sclib_papers_v1
FIRESTORE_DATABASE=(default)
GCS_BUCKET=sclib-jzis
GEMINI_MODEL=gemini-2.5-flash
EMBEDDING_MODEL=text-embedding-005
API_KEYS_COLLECTION=api_keys          # Firestore collection for key validation
ANON_RATE_LIMIT=100                   # requests per day for anonymous
```

### Frontend (Vercel)
```bash
NEXT_PUBLIC_API_BASE=https://api.jzis.org/sclib/v1
NEXT_PUBLIC_SITE_URL=https://jzis.org/sclib
```

### Ingestion Pipeline
```bash
GCP_PROJECT=jzis-sclib
GCS_BUCKET=sclib-jzis
ARXIV_OAI_SET=cs.supcon               # arXiv OAI-PMH set for cond-mat.supr-con
S2_API_KEY=...                        # Semantic Scholar API key (free tier ok)
VERTEX_AI_INDEX_ID=...
EMBEDDING_BATCH_SIZE=250
```

---

## 8. GCP Setup Script

```bash
# scripts/setup_gcp.sh
#!/bin/bash
set -e

PROJECT_ID="jzis-sclib"
REGION="us-central1"
BUCKET="sclib-jzis"

# Create project (if not exists)
gcloud projects create $PROJECT_ID --name="SCLib JZIS" || true
gcloud config set project $PROJECT_ID

# Enable APIs
gcloud services enable \
  aiplatform.googleapis.com \
  firestore.googleapis.com \
  storage.googleapis.com \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  secretmanager.googleapis.com

# Create GCS bucket
gsutil mb -p $PROJECT_ID -l $REGION gs://$BUCKET/
gsutil lifecycle set lifecycle.json gs://$BUCKET/  # 30-day lifecycle for temp files

# Create Firestore database
gcloud firestore databases create --region=$REGION

# Create service account
gcloud iam service-accounts create sclib-api \
  --display-name="SCLib API Service Account"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:sclib-api@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/aiplatform.user"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:sclib-api@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/datastore.user"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:sclib-api@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/storage.objectViewer"

echo "GCP setup complete. Next: create Vertex AI Vector Search index."
```

---

## 9. Cost Estimates (Updated)

### 9.1 One-Time Build (full ingestion 1986–2026)

| Item | Quantity | Cost |
|------|---------|------|
| Vertex AI Embedding (text-embedding-005) | ~1.5M chunks × 512 tokens ≈ 768M tokens | ~$0.77 |
| GCS Storage (250GB PDFs + 25GB text) | 275 GB | ~$5.50/month |
| Cloud Run (ingestion jobs) | ~50 hrs | ~$10 |
| Gemini Flash (material NER, 50K papers) | ~25M tokens | ~$2.50 |
| **Total one-time** | | **~$19** |

### 9.2 Monthly Operations

| Item | Cost/month |
|------|-----------|
| Vertex AI Vector Search (1 node, us-central1) | ~$65 |
| Cloud Run API (100K req/month) | ~$5 |
| Cloud Firestore (reads/writes/storage) | ~$5 |
| GCS Storage (275GB) | ~$5.50 |
| Vertex AI Embedding (daily updates ~30 papers) | ~$0.01 |
| Gemini Flash (RAG Q&A ~1K/month) | ~$2 |
| Gemini Flash (daily NER) | ~$0.05 |
| Vercel (frontend, free tier) | $0 |
| **Monthly total** | **~$83** |

> **Note:** Vertex AI Vector Search minimum is ~$65/month for 1 dedicated node. This is the primary cost driver vs the Qdrant self-hosted alternative (~$25/month). Trade-off: fully managed, no ops, better SLA.

---

## 10. Build Order for Claude Code

Build in this exact order. Each phase should be functional before proceeding.

### Phase 0: Repo + GCP Setup (Day 1)
```
1. Clone repo, set up monorepo structure per Section 2
2. Create pyproject.toml files with uv
3. Create package.json with pnpm
4. Run scripts/setup_gcp.sh
5. Create Vertex AI Vector Search index (scripts/create_vector_index.py)
6. Set up GitHub Actions secrets
7. Verify GCP connectivity from local env
```

### Phase 1: Ingestion Pipeline (Days 2-4)
```
1. ingestion/collect/arxiv_oai.py — OAI-PMH client, parse XML, download .tar.gz
2. ingestion/parse/latex_parser.py — extract title/abstract/sections/equations/refs
3. ingestion/parse/pdf_parser.py — opendataloader-pdf fallback
4. ingestion/chunk/chunker.py — section-aware chunker
5. ingestion/embed/embedder.py — batch embedding with Vertex AI
6. ingestion/index/indexer.py — upsert to Vertex AI VS + Firestore chunks
7. ingestion/extract/material_ner.py — Gemini NER pipeline
8. ingestion/pipeline.py — orchestrate all steps, support --mode bulk|incremental
9. Test with 100 papers, verify VS query returns results
```

### Phase 2: API (Days 5-7)
```
1. api/services/*.py — all GCP clients with proper auth
2. api/models/*.py — all Pydantic models per Section 3
3. api/routers/search.py — vector search + Firestore fetch + merge
4. api/routers/ask.py — RAG: embed → VS → Firestore → Gemini → response
5. api/routers/materials.py — Firestore query + pagination
6. api/routers/papers.py — single paper fetch
7. api/routers/stats.py — return cached stats
8. api/routers/similar.py — avg chunk vector → VS query
9. api/routers/timeline.py — Firestore query + format
10. api/main.py — wire all routers, CORS, auth middleware, rate limiting
11. Dockerfile — multi-stage build
12. Deploy to Cloud Run, verify all endpoints
13. Write api/tests/*.py
```

### Phase 3: Frontend (Days 8-12)
```
1. frontend/app/layout.tsx — root layout, nav, footer
2. frontend/components/ui/ — install shadcn/ui components
3. frontend/app/page.tsx — Dashboard with stats cards + search bar
4. frontend/components/TcTimeline.tsx — Plotly.js chart
5. frontend/app/search/page.tsx — full search UI with filters
6. frontend/app/ask/page.tsx — chat interface
7. frontend/app/materials/page.tsx — sortable table
8. frontend/app/materials/[formula]/page.tsx — material detail
9. frontend/app/paper/[id]/page.tsx — paper detail
10. frontend/app/timeline/page.tsx — full timeline page
11. frontend/app/stats/page.tsx — statistics dashboard
12. frontend/app/api-docs/page.tsx — embed Swagger UI iframe
13. frontend/app/about/page.tsx — about + citation format
14. Deploy to Vercel, configure jzis.org/sclib route
```

### Phase 4: Automation + Polish (Days 13-14)
```
1. .github/workflows/ingest-daily.yml — daily cron
2. .github/workflows/deploy-api.yml — CD for API
3. .github/workflows/deploy-frontend.yml — CD for frontend
4. .github/workflows/test.yml — CI on PR
5. scripts/import_nims.py — bulk import NIMS SuperCon CSV
6. Seed initial data: run bulk ingestion for 2023-2026 papers first (fastest path to demo)
7. README.md with setup instructions
8. CONTRIBUTING.md
9. docs/API.md — full API reference with examples
```

---

## 11. Key Implementation Notes for Claude Code

### Authentication
- Use Workload Identity Federation for Cloud Run (no service account key files in prod)
- For local dev: use `gcloud auth application-default login`
- API keys stored in Firestore `api_keys/{key_hash}` collection
- Rate limiting: use Firestore increment + TTL documents

### Vertex AI Vector Search Specifics
```python
# Query example
from google.cloud import aiplatform

def search_vectors(query_embedding: List[float], top_k: int = 20, filters: dict = None):
    index_endpoint = aiplatform.MatchingEngineIndexEndpoint(
        index_endpoint_name=INDEX_ENDPOINT_NAME
    )
    
    # Build numeric/categorical restricts from filters
    numeric_restricts = []
    restricts = []
    
    if filters:
        if filters.get("year_min"):
            numeric_restricts.append(
                aiplatform.matching_engine.matching_engine_index_endpoint.NumericRestriction(
                    namespace="year",
                    value_int=filters["year_min"],
                    op="GREATER_EQUAL"
                )
            )
        if filters.get("material_family"):
            restricts.append(
                aiplatform.matching_engine.matching_engine_index_endpoint.Restriction(
                    namespace="material_family",
                    allow_list=filters["material_family"]
                )
            )
    
    response = index_endpoint.find_neighbors(
        deployed_index_id=DEPLOYED_INDEX_ID,
        queries=[query_embedding],
        num_neighbors=top_k,
        numeric_filter_restricts=numeric_restricts,
        filter_restricts=restricts,
        return_full_datapoint=False
    )
    return response[0]  # List of MatchNeighbor
```

### Firestore Indexes Required
```python
# scripts/init_firestore.py
# Create composite indexes for:
# papers: (material_family ASC, date_published DESC)
# papers: (status ASC, date_published DESC)  
# materials: (family ASC, tc_max DESC)
# materials: (family ASC, total_papers DESC)
# chunks: (paper_id ASC, chunk_index ASC)
```

### Error Handling
- All API endpoints return RFC 7807 Problem Details format on error
- Retry with exponential backoff on all GCP calls (max 3 retries)
- Log structured JSON to Cloud Logging

### CORS Configuration
```python
# api/main.py
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://jzis.org", "https://www.jzis.org", "http://localhost:3000"],
    allow_methods=["GET", "POST"],
    allow_headers=["X-API-Key", "Content-Type"],
)
```

---

## 12. Acceptance Criteria (MVP)

The build is complete when:

- [ ] `POST /search` returns relevant papers for "nickelate superconductor ambient pressure" in < 500ms
- [ ] `POST /ask` returns a cited answer for "What is the highest ambient-pressure Tc?" in < 5s
- [ ] `GET /materials?family=nickelate&sort=tc_desc` returns La₃Ni₂O₇ as top result
- [ ] `GET /stats` shows total_papers > 10,000 (MVP seed with 2020–2026 papers)
- [ ] `GET /timeline` returns data suitable for Plotly rendering
- [ ] Frontend dashboard loads at jzis.org/sclib in < 3s
- [ ] Search page returns results with highlighted snippets
- [ ] Ask page returns cited responses with paper cards
- [ ] Materials table is sortable and filterable
- [ ] Daily GitHub Actions cron runs without error
- [ ] All API endpoints documented in Swagger at /api-docs
- [ ] README complete with quickstart for local dev

---

## 13. References & Assets

- **Repo:** https://github.com/JackZH26/SCLib_JZIS
- **Domain:** jzis.org/sclib (configure in Vercel + Cloudflare)
- **GCP Project:** jzis-sclib (to be created)
- **arXiv OAI-PMH endpoint:** http://export.arxiv.org/oai2
- **arXiv set for superconductivity:** `cond-mat.supr-con`
- **Semantic Scholar API:** https://api.semanticscholar.org/graph/v1
- **NIMS SuperCon data:** Already downloaded at `research/superconductor-databases/supercon2_v22.12.03.csv` (40,325 records)
- **Vertex AI VS docs:** https://cloud.google.com/vertex-ai/docs/vector-search/overview
- **License:** Apache 2.0 (code) + CC BY 4.0 (data)

---

*SCLib_JZIS Project Specification v1.0 — Ready for Claude Code*
*Generated by 瓦力 (Wall-E) | JZIS | 2026-04-14*
