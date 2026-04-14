# SCLib_JZIS — Project Specification for Claude Code
> **Version:** 2.1 | **Date:** 2026-04-14 | **Author:** Jian Zhou / JZIS
> **Repo:** https://github.com/JackZH26/SCLib_JZIS
> **Domain:** jzis.org/sclib (frontend) | api.jzis.org/sclib (API)
> **Deployment:** Self-hosted VPS2 (all app services) + GCP (data layer)
> **Status:** Confirmed by Jack — Ready to build

---

## 0. Project Overview

**SCLib_JZIS** (JZIS Superconductivity Library) is the superconductivity field's equivalent of **Semantic Scholar + Materials Project + AI assistant**, unified in one open-source platform, fully self-hosted on JZIS VPS.

### What it does
- **Semantic search** over 200,000+ superconductivity papers (1986–present, daily updates)
- **Materials database** with structured Tc, pressure, and experimental data
- **AI-powered Q&A** (RAG) citing specific papers as sources
- **Open REST API** for registered researchers and AI agents

### Access Model
| User Type | Registration | API Access | Free Queries |
|-----------|-------------|-----------|--------------|
| **Guest** | None | View docs + landing only | 3 queries/day/IP |
| **Registered User** | Required (email verified) | Full API with API key | Unlimited |

---

## 1. Infrastructure

### VPS2 (JZIS VPS) — Application Servers
```
IP:       72.62.251.29
CPU:      8 vCPU (upgraded)
RAM:      8 GB
SSD:      96 GB NVMe (93 GB free)
OS:       Ubuntu
Running:  Nginx + Docker (no containers currently)
SSH:      root@72.62.251.29
```

**Existing sites on VPS2 (do NOT break these):**
- `jzis.org` → `/var/www/jzis` (JZIS homepage, static)
- `asrp.jzis.org` → `/var/www/asrp` + proxy to `:3001` (ASRP website)

**SCLib will add:**
- `jzis.org/sclib` → proxy to Next.js `:3000`
- `api.jzis.org` → proxy to FastAPI `:8000`

> **Note:** VPS1 (76.13.191.130) runs OpenClaw only. Do not touch VPS1.

### GCP (Data Layer Only — No Servers to Manage)
```
Project:  jzis-sclib (create in GCP Console)
Services:
  - Vertex AI Vector Search  (768d vectors, managed)
  - Vertex AI Embedding API  (text-embedding-005)
  - Gemini API               (gemini-2.5-flash, RAG + NER)
  - Cloud Storage            (PDFs + parsed text)
```

### Tech Stack

| Layer | Technology |
|-------|-----------|
| **Frontend** | Next.js 14 (App Router) + Tailwind CSS + shadcn/ui |
| **API** | FastAPI (Python 3.11) |
| **Reverse Proxy** | Nginx (existing on VPS2, add new server blocks) |
| **Database** | PostgreSQL 16 (Docker on VPS2) |
| **Cache / Rate Limit** | Redis 7 (Docker on VPS2) |
| **Email** | Resend API |
| **Vector DB** | Vertex AI Vector Search |
| **Embedding** | Vertex AI text-embedding-005 (768d) |
| **LLM** | Gemini 2.5 Flash (RAG + material NER) |
| **Object Storage** | Google Cloud Storage |
| **LaTeX Parser** | Custom Python + Pandoc |
| **PDF Fallback** | opendataloader-pdf v2.2.0 |
| **CI/CD** | GitHub Actions (auto SSH deploy on push to main) |
| **Package Manager** | uv (Python) + pnpm (Node) |

---

## 2. VPS2 Deployment Architecture

```
Internet (80/443)
       │
       ▼
   Nginx (existing)
   ├── jzis.org          → /var/www/jzis   (static, existing)
   ├── asrp.jzis.org     → /var/www/asrp + proxy :3001 (existing)
   ├── jzis.org/sclib    → proxy :3000  ← NEW (Next.js)
   └── api.jzis.org      → proxy :8000  ← NEW (FastAPI)
           │
    Docker Compose (new)
    ├── sclib-frontend  :3000  (Next.js)
    ├── sclib-api       :8000  (FastAPI)
    ├── postgres        :5432  (internal only)
    └── redis           :6379  (internal only)
           │
    GCP (external)
    ├── Vertex AI VS    (vector search)
    ├── Embedding API   (text-embedding-005)
    ├── Gemini API      (RAG + NER)
    └── Cloud Storage   (PDF files)
```

### Docker Compose (`docker-compose.yml`)

```yaml
services:
  frontend:
    build: ./frontend
    restart: unless-stopped
    ports:
      - "127.0.0.1:3000:3000"
    environment:
      - NEXT_PUBLIC_API_BASE=https://api.jzis.org/sclib/v1
    depends_on:
      - api

  api:
    build: ./api
    restart: unless-stopped
    ports:
      - "127.0.0.1:8000:8000"
    env_file: .env
    volumes:
      - ./credentials/gcp-sa.json:/credentials/gcp-sa.json:ro
    depends_on:
      - postgres
      - redis

  postgres:
    image: postgres:16-alpine
    restart: unless-stopped
    environment:
      POSTGRES_DB: sclib
      POSTGRES_USER: sclib
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    # No external port — internal only

  redis:
    image: redis:7-alpine
    restart: unless-stopped
    command: redis-server --appendonly yes
    volumes:
      - redis_data:/data
    # No external port — internal only

volumes:
  postgres_data:
  redis_data:
```

### Nginx — New Server Blocks to Add

Add these blocks to `/etc/nginx/sites-available/jzis.org` (append, don't replace existing):

```nginx
# SCLib Frontend — jzis.org/sclib
# Add inside existing jzis.org server block:
location /sclib {
    proxy_pass http://127.0.0.1:3000;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection 'upgrade';
    proxy_cache_bypass $http_upgrade;
}

# SCLib API — api.jzis.org
server {
    server_name api.jzis.org;

    location /sclib/ {
        proxy_pass http://127.0.0.1:8000/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    listen 443 ssl;
    ssl_certificate /etc/letsencrypt/live/api.jzis.org/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.jzis.org/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;
}

server {
    listen 80;
    server_name api.jzis.org;
    return 301 https://$host$request_uri;
}
```

**To get SSL cert for api.jzis.org:**
```bash
certbot --nginx -d api.jzis.org
```

---

## 3. Repository Structure

```
SCLib_JZIS/
├── CLAUDE.md                        # ← Claude Code reads this first (auto)
├── README.md
├── CONTRIBUTING.md
├── LICENSE                          # Apache 2.0
├── docker-compose.yml               # All VPS2 app services
├── docker-compose.dev.yml           # Local dev overrides
├── .env.example                     # Environment variable template
├── nginx/
│   └── sclib.conf                   # Nginx config snippet (append to VPS2)
├── .github/
│   └── workflows/
│       ├── deploy.yml               # SSH deploy to VPS2 on main push
│       ├── test.yml                 # Run tests on PR
│       └── ingest-daily.yml        # Daily arXiv cron via SSH
├── api/                             # FastAPI backend
│   ├── pyproject.toml               # uv project file
│   ├── Dockerfile
│   ├── alembic/                     # DB migrations
│   │   ├── env.py
│   │   └── versions/
│   ├── main.py                      # FastAPI app entry
│   ├── routers/
│   │   ├── auth.py                  # POST /auth/register|verify|login|keys
│   │   ├── search.py                # POST /search
│   │   ├── ask.py                   # POST /ask
│   │   ├── materials.py             # GET /materials[/{formula}]
│   │   ├── papers.py                # GET /paper/{id}
│   │   ├── stats.py                 # GET /stats
│   │   ├── similar.py               # GET /similar/{id}
│   │   └── timeline.py              # GET /timeline
│   ├── services/
│   │   ├── vector_search.py         # Vertex AI VS client
│   │   ├── embedding.py             # text-embedding-005
│   │   ├── gemini.py                # RAG + NER
│   │   ├── storage.py               # GCS
│   │   ├── email.py                 # Resend
│   │   ├── rate_limit.py            # Redis rate limiting
│   │   └── auth_service.py          # API key, JWT, bcrypt
│   ├── models/
│   │   ├── db.py                    # SQLAlchemy ORM models
│   │   ├── paper.py                 # Pydantic schemas
│   │   ├── material.py
│   │   ├── user.py
│   │   ├── search.py
│   │   └── ask.py
│   └── tests/
│       ├── test_auth.py
│       ├── test_search.py
│       ├── test_ask.py
│       └── test_materials.py
├── ingestion/                       # Data pipeline
│   ├── pyproject.toml
│   ├── collect/
│   │   ├── arxiv_oai.py             # OAI-PMH bulk + incremental
│   │   └── semantic_scholar.py
│   ├── parse/
│   │   ├── latex_parser.py          # arXiv .tar.gz → structured JSON
│   │   └── pdf_parser.py            # opendataloader-pdf fallback
│   ├── chunk/
│   │   └── chunker.py               # Section-aware 512-token chunks
│   ├── embed/
│   │   └── embedder.py              # Batch embedding (Vertex AI)
│   ├── index/
│   │   └── indexer.py               # Upsert VS + insert PostgreSQL
│   ├── extract/
│   │   └── material_ner.py          # Gemini material extraction
│   └── pipeline.py                  # Orchestration entry point
├── frontend/                        # Next.js 14 app
│   ├── package.json
│   ├── next.config.ts
│   ├── Dockerfile
│   ├── app/
│   │   ├── layout.tsx
│   │   ├── page.tsx                 # Landing (public)
│   │   ├── search/page.tsx          # 3/day guest → unlimited registered
│   │   ├── ask/page.tsx
│   │   ├── materials/
│   │   │   ├── page.tsx
│   │   │   └── [formula]/page.tsx
│   │   ├── paper/[id]/page.tsx
│   │   ├── timeline/page.tsx        # Public
│   │   ├── stats/page.tsx           # Public
│   │   ├── api-docs/page.tsx        # Public (Swagger UI embed)
│   │   ├── about/page.tsx           # Public
│   │   └── auth/
│   │       ├── register/page.tsx
│   │       ├── verify/page.tsx
│   │       ├── login/page.tsx
│   │       └── dashboard/page.tsx   # API key management
│   └── components/
│       ├── ui/                      # shadcn/ui
│       ├── SearchBar.tsx
│       ├── PaperCard.tsx
│       ├── MaterialTable.tsx
│       ├── TcTimeline.tsx           # Plotly.js
│       ├── ChatInterface.tsx
│       ├── StatsCards.tsx
│       ├── GuestBanner.tsx          # Remaining free query counter
│       └── AuthGuard.tsx
├── scripts/
│   ├── setup_vps2.sh                # Initial VPS2 Docker setup
│   ├── deploy.sh                    # Manual deploy
│   ├── init_db.py                   # Create tables + indexes
│   ├── create_vertex_index.py       # Vertex AI VS index creation
│   └── import_nims.py               # NIMS SuperCon CSV import
└── docs/
    ├── API.md
    ├── DEPLOYMENT.md
    └── VPS_SETUP.md
```

---

## 4. Database Schema (PostgreSQL)

### Users

```sql
CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email           VARCHAR(255) UNIQUE NOT NULL,
    email_verified  BOOLEAN DEFAULT FALSE,
    name            VARCHAR(255) NOT NULL,
    institution     VARCHAR(500),
    country         VARCHAR(100),
    age             SMALLINT CHECK (age >= 13 AND age <= 120),
    research_area   VARCHAR(255),
    purpose         TEXT,
    password_hash   VARCHAR(255) NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    last_login      TIMESTAMPTZ,
    is_active       BOOLEAN DEFAULT FALSE,  -- False until email verified
    is_admin        BOOLEAN DEFAULT FALSE
);

CREATE TABLE email_verifications (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID REFERENCES users(id) ON DELETE CASCADE,
    token       VARCHAR(64) UNIQUE NOT NULL,
    expires_at  TIMESTAMPTZ NOT NULL,
    used        BOOLEAN DEFAULT FALSE,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE api_keys (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID REFERENCES users(id) ON DELETE CASCADE,
    key_hash    VARCHAR(64) UNIQUE NOT NULL,  -- SHA-256 of actual key
    key_prefix  VARCHAR(8) NOT NULL,          -- "scl_xxxx" for display
    name        VARCHAR(100),
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    last_used   TIMESTAMPTZ,
    revoked     BOOLEAN DEFAULT FALSE
);
```

### Papers

```sql
CREATE TABLE papers (
    id                  VARCHAR(100) PRIMARY KEY,   -- "arxiv:2306.07275"
    source              VARCHAR(20) NOT NULL,
    arxiv_id            VARCHAR(20),
    doi                 VARCHAR(200),
    title               TEXT NOT NULL,
    authors             JSONB NOT NULL,
    affiliations        JSONB,
    date_submitted      DATE,
    date_published      DATE,
    journal             VARCHAR(300),
    abstract            TEXT NOT NULL,
    categories          JSONB,
    material_family     VARCHAR(50),
    status              VARCHAR(20) DEFAULT 'published',
    retraction_date     DATE,
    retraction_reason   TEXT,
    citation_count      INTEGER DEFAULT 0,
    chunk_count         INTEGER DEFAULT 0,
    materials_extracted JSONB DEFAULT '[]',
    quality_flags       JSONB DEFAULT '[]',
    indexed_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_papers_family ON papers(material_family);
CREATE INDEX idx_papers_date ON papers(date_published DESC);
CREATE INDEX idx_papers_status ON papers(status);
CREATE INDEX idx_papers_arxiv ON papers(arxiv_id);
```

### Materials

```sql
CREATE TABLE materials (
    id                  VARCHAR(100) PRIMARY KEY,  -- "La3Ni2O7"
    formula             VARCHAR(200) NOT NULL,
    formula_normalized  VARCHAR(200) NOT NULL,
    formula_latex       VARCHAR(200),
    family              VARCHAR(50),
    subfamily           VARCHAR(100),
    crystal_structure   VARCHAR(100),
    tc_max              REAL,
    tc_max_conditions   VARCHAR(300),
    tc_ambient          REAL,
    pairing_symmetry    VARCHAR(100),
    discovery_year      SMALLINT,
    total_papers        INTEGER DEFAULT 0,
    status              VARCHAR(50) DEFAULT 'active_research',
    records             JSONB DEFAULT '[]',
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_materials_family ON materials(family);
CREATE INDEX idx_materials_tc ON materials(tc_max DESC NULLS LAST);
```

### Chunks (text payload, looked up after VS query)

```sql
CREATE TABLE chunks (
    id                  VARCHAR(200) PRIMARY KEY,  -- "arxiv:2306.07275_chunk_005"
    paper_id            VARCHAR(100) REFERENCES papers(id),
    title               TEXT,
    authors_short       VARCHAR(200),
    year                SMALLINT,
    section             VARCHAR(200),
    chunk_index         SMALLINT,
    text                TEXT NOT NULL,
    material_family     VARCHAR(50),
    materials_mentioned JSONB DEFAULT '[]',
    has_equation        BOOLEAN DEFAULT FALSE,
    has_table           BOOLEAN DEFAULT FALSE
);

CREATE INDEX idx_chunks_paper ON chunks(paper_id);
```

### Stats Cache

```sql
CREATE TABLE stats_cache (
    key         VARCHAR(100) PRIMARY KEY,
    value       JSONB NOT NULL,
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);
-- Rows: 'global', 'by_year', 'by_family', 'tc_records'
```

---

## 5. User Registration & Auth Flow

```
1. User fills register form → POST /auth/register
   Fields: email*, password*, name*, age*, institution, country, research_area, purpose
   → Validate → hash password (bcrypt cost 12) → create user (is_active=False)
   → Generate 64-char token (expires 24h) → send verification email

2. User clicks email link → GET /auth/verify?token=xxx
   → Validate token → is_active=True → generate API key (format: "scl_" + 40 random chars)
   → Send welcome email with API key → redirect to /auth/dashboard

3. Login → POST /auth/login → return JWT (24h)

4. API calls → X-API-Key: scl_xxx header
   → hash key → lookup in api_keys table → get user → allow if is_active
```

### Registration Form Fields

| Field | Required | Validation |
|-------|---------|-----------|
| Email | ✅ | Valid format, unique |
| Password | ✅ | Min 8 chars |
| Full Name | ✅ | Min 2 chars |
| Age | ✅ | Integer 13–120 |
| Institution | Optional | e.g. "MIT", "Independent Researcher" |
| Country | Optional | Dropdown |
| Research Area | Optional | e.g. "High-temperature superconductivity" |
| Purpose | Optional | Max 500 chars |

---

## 6. Access Control & Rate Limiting

```python
GUEST_DAILY_LIMIT = 3  # per IP per calendar day

# Redis key: "guest_quota:{YYYY-MM-DD}:{ip}"  TTL: 86400s

async def api_key_middleware(request):
    key = request.headers.get("X-API-Key")
    if key:
        # Registered user path
        user = await validate_api_key(key)
        return AuthenticatedUser(user)
    else:
        # Guest path
        ip = get_real_ip(request)
        remaining = await get_guest_remaining(ip)
        if remaining <= 0:
            raise HTTPException(429, "Guest limit reached. Register free at jzis.org/sclib/auth/register")
        await decrement_guest(ip)
        return GuestUser(ip, remaining - 1)
```

### Page Access

| Page | Guest | Registered |
|------|-------|-----------|
| Landing, Timeline, Stats, About, API Docs, Auth pages | ✅ Public | ✅ |
| Search, Ask, Materials, Paper detail, API endpoints | ⚠️ 3/day | ✅ Unlimited |

---

## 7. API Specification

**Base URL:** `https://api.jzis.org/sclib/v1`
**Auth:** `X-API-Key: scl_xxx` (registered) or no key (guest 3/day/IP)

### Auth Endpoints
```
POST /auth/register    → create account, send verification email
GET  /auth/verify      → verify email, return API key
POST /auth/login       → JWT token
GET  /auth/me          → current user info
POST /auth/keys        → generate new API key
DELETE /auth/keys/{id} → revoke key
```

### Search — POST /search
```json
// Request
{
  "query": "nickelate superconductor ambient pressure",
  "top_k": 20,
  "filters": {
    "year_min": 2020, "year_max": 2026,
    "material_family": ["nickelate"],
    "tc_min": 50, "pressure_max": 0,
    "exclude_retracted": true
  },
  "sort": "relevance"
}
// Response: {total, results: [{paper_id, title, authors, year, relevance_score, matched_chunk, materials, citation_count}], query_time_ms, guest_remaining?}
```

Implementation: embed query → Vertex AI VS → fetch chunks from PostgreSQL → fetch paper metadata → merge

### Ask — POST /ask
```json
// Request
{"question": "...", "max_sources": 10, "language": "auto"}
// Response: {answer (markdown with [1][2] citations), sources, tokens_used, guest_remaining?}
```

RAG System Prompt:
```
You are SCLib, an AI assistant for the superconductivity research community.
Answer ONLY based on the provided papers. Cite as [1], [2], etc.
Be precise about Tc values, pressures, and formulas.
Distinguish experimental measurements from theoretical predictions.
If the answer is not in the papers, say so clearly.
Language: {language}
```

### Other Endpoints
```
GET /materials                     → paginated list (filters: family, tc_min, pressure_max, sort)
GET /materials/{formula}           → full material detail + all TcRecords + timeline
GET /paper/{id}                    → full paper detail
GET /similar/{paper_id}?top_k=10  → similar papers via avg chunk vector
GET /stats                         → global stats (public, cached daily)
GET /timeline?family=all           → Tc records for Plotly visualization (public)
```

---

## 8. Ingestion Pipeline

### Chunking Strategy
```python
MAX_TOKENS = 512
OVERLAP_TOKENS = 64
MIN_CHUNK_TOKENS = 100
# Section-aware: split at \section{} boundaries first
# Preserve equations as atomic units
# Prepend "Title: {title}\nSection: {section}\n" for retrieval context
# Skip bibliography sections
```

### Vertex AI VS Upsert
```python
from google.cloud import aiplatform

def upsert_chunks(datapoints):
    index = aiplatform.MatchingEngineIndex(INDEX_NAME)
    index.upsert_datapoints(datapoints=datapoints)

# Each datapoint:
{
    "datapoint_id": "arxiv:2306.07275_chunk_005",
    "feature_vector": [...],  # 768-dim
    "restricts": [{"namespace": "material_family", "allow_list": ["nickelate"]}],
    "numeric_restricts": [{"namespace": "year", "value_int": 2023}],
    "crowding_tag": {"value": "arxiv:2306.07275"}  # 1 chunk per paper in results
}
```

### Material NER Prompt (Gemini)
```
Extract superconducting materials from this text. Return JSON array only.
For each material: {formula, tc_kelvin, tc_type, pressure_gpa, measurement, confidence}
Only extract materials explicitly measured for superconductivity.
Do not invent data not in the text. Flag Tc > 300K with confidence < 0.3.
```

### Daily Cron (GitHub Actions → SSH)
```yaml
- name: Run incremental ingestion
  uses: appleboy/ssh-action@v1
  with:
    host: 72.62.251.29
    script: |
      cd /opt/SCLib_JZIS
      docker compose run --rm api uv run ingestion/pipeline.py --mode incremental
```

---

## 9. Frontend Pages

| Page | Auth | Description |
|------|------|-------------|
| `/sclib` | Public | Landing: stats + search + timeline preview + register CTA |
| `/sclib/search` | Guest 3/day | Sidebar filters + result cards with snippets |
| `/sclib/ask` | Guest 3/day | Chat UI + citation source cards |
| `/sclib/materials` | Guest 3/day | Sortable table + export CSV (registered only) |
| `/sclib/materials/{formula}` | Guest 3/day | Full material detail + Tc timeline |
| `/sclib/paper/{id}` | Guest 3/day | Paper detail |
| `/sclib/timeline` | Public | Plotly.js Tc records interactive chart |
| `/sclib/stats` | Public | Full statistics dashboard |
| `/sclib/api-docs` | Public | Embedded Swagger UI |
| `/sclib/about` | Public | About + citation format |
| `/sclib/auth/register` | Public | Registration form |
| `/sclib/auth/verify` | Public | Email verification landing |
| `/sclib/auth/login` | Public | Login |
| `/sclib/auth/dashboard` | Auth | API key management + usage |

**GuestBanner component:** shown on all rate-limited pages for guests, displays remaining daily queries.

---

## 10. Email Service (Resend)

```python
# pip install resend
import resend

resend.api_key = RESEND_API_KEY  # free tier: 3,000 emails/month

async def send_verification(to, name, token):
    url = f"https://jzis.org/sclib/auth/verify?token={token}"
    await resend.Emails.send({
        "from": "SCLib <noreply@jzis.org>",
        "to": to,
        "subject": "Verify your SCLib_JZIS account",
        "html": f"""<p>Hi {name},</p>
<p>Click to verify your email: <a href="{url}">{url}</a></p>
<p>Link expires in 24 hours.</p>
<p>— JZIS Team</p>"""
    })

async def send_welcome(to, name, api_key):
    await resend.Emails.send({
        "from": "SCLib <noreply@jzis.org>",
        "to": to,
        "subject": "Your SCLib_JZIS API Key is ready",
        "html": f"""<p>Hi {name}, your account is verified!</p>
<p>Your API key: <code>{api_key}</code></p>
<p>Use header: <code>X-API-Key: {api_key}</code></p>
<p>API docs: <a href="https://jzis.org/sclib/api-docs">jzis.org/sclib/api-docs</a></p>
<p>— JZIS Team</p>"""
    })
```

---

## 11. Environment Variables (`.env` on VPS2)

```bash
# === Database ===
DB_PASSWORD=<strong-random-password>
DATABASE_URL=postgresql://sclib:${DB_PASSWORD}@postgres:5432/sclib

# === Redis ===
REDIS_URL=redis://redis:6379

# === GCP ===
GCP_PROJECT=jzis-sclib
GCP_REGION=us-central1
GOOGLE_APPLICATION_CREDENTIALS=/credentials/gcp-sa.json
VERTEX_AI_INDEX_ENDPOINT=projects/.../locations/.../indexEndpoints/...
VERTEX_AI_DEPLOYED_INDEX_ID=sclib_papers_v1
GCS_BUCKET=sclib-jzis

# === AI Models ===
GEMINI_MODEL=gemini-2.5-flash
EMBEDDING_MODEL=text-embedding-005

# === Auth ===
JWT_SECRET=<strong-random-64-char-secret>
JWT_EXPIRY_HOURS=24
API_KEY_PREFIX=scl_

# === Email ===
RESEND_API_KEY=re_xxxxxxxxxxxx

# === App ===
FRONTEND_URL=https://jzis.org/sclib
API_BASE_URL=https://api.jzis.org/sclib/v1
GUEST_DAILY_LIMIT=3
ENVIRONMENT=production
```

---

## 12. CI/CD: Auto Deploy

```yaml
# .github/workflows/deploy.yml
name: Deploy to VPS2
on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - name: Deploy via SSH
        uses: appleboy/ssh-action@v1
        with:
          host: 72.62.251.29
          username: root
          key: ${{ secrets.VPS2_SSH_KEY }}
          script: |
            cd /opt/SCLib_JZIS
            git pull origin main
            docker compose build --no-cache
            docker compose up -d
            docker compose exec api alembic upgrade head
            docker compose ps
```

---

## 13. VPS2 Initial Setup Script

```bash
#!/bin/bash
# scripts/setup_vps2.sh — run once on VPS2

set -e

# Install Docker (if not installed)
if ! command -v docker &> /dev/null; then
    curl -fsSL https://get.docker.com | sh
    usermod -aG docker root
fi

# Create app directory
mkdir -p /opt/SCLib_JZIS
cd /opt/SCLib_JZIS

# Clone repo
git clone https://github.com/JackZH26/SCLib_JZIS.git .

# Create env and credentials
cp .env.example .env
mkdir -p credentials
echo "⚠️  Edit .env and place GCP SA JSON at credentials/gcp-sa.json"

# Add SSH key for GitHub Actions auto-deploy
# (Run: cat ~/.ssh/id_rsa or generate new key, add pub to GitHub Deploy Keys)

# Get SSL cert for api.jzis.org
certbot --nginx -d api.jzis.org

# Update nginx (append sclib config)
cp nginx/sclib.conf /etc/nginx/conf.d/sclib.conf
nginx -t && systemctl reload nginx

echo "Setup complete!"
```

---

## 14. Monthly Cost

| Item | Cost |
|------|------|
| VPS2 (8 vCPU, 8GB RAM, upgraded) | ~$20/mo |
| Vertex AI Vector Search (1 node) | ~$65/mo |
| Vertex AI Embedding (daily 30 papers) | ~$0.01/mo |
| Gemini Flash (RAG ~1K/mo + NER daily) | ~$3/mo |
| Cloud Storage (~275 GB PDFs + text) | ~$6/mo |
| Resend (free tier 3K emails/mo) | $0 |
| Domain (already owned) | — |
| **Total** | **~$94/mo** |

---

## 15. Build Order for Claude Code

**Start:** Clone repo, read this spec, then build Phase 0 → 5 in order.

### Phase 0: VPS2 + Repo Setup (Day 1)
```
1. Set up repo structure exactly as Section 3
2. Create docker-compose.yml (Section 2)
3. Create nginx/sclib.conf snippet (Section 2)
4. Run scripts/setup_vps2.sh on VPS2 (72.62.251.29)
5. Verify all 4 containers start (frontend, api, postgres, redis)
6. Create Vertex AI VS index: scripts/create_vertex_index.py
7. Set GitHub Actions secrets (VPS2_SSH_KEY, GCP_SA_KEY, etc.)
8. Test deploy.yml on push to main
```

### Phase 1: Database + Auth (Days 2-3)
```
1. api/models/db.py — SQLAlchemy ORM for all tables (Section 4)
2. alembic/ setup + initial migration
3. api/services/email.py — Resend (Section 10)
4. api/services/auth_service.py — bcrypt, JWT, API key generation
5. api/services/rate_limit.py — Redis guest quota (Section 6)
6. api/routers/auth.py — all 6 auth endpoints (Section 7)
7. frontend/app/auth/* — register form, verify, login, dashboard pages
8. Test complete flow: register → email verification → API key received → login
```

### Phase 2: Ingestion Pipeline (Days 4-6)
```
1. ingestion/collect/arxiv_oai.py — OAI-PMH for cond-mat.supr-con
2. ingestion/parse/latex_parser.py + pdf_parser.py
3. ingestion/chunk/chunker.py (Section 8)
4. ingestion/embed/embedder.py — Vertex AI batch, 250/request
5. ingestion/index/indexer.py — VS upsert + PostgreSQL insert
6. ingestion/extract/material_ner.py — Gemini NER (Section 8)
7. scripts/import_nims.py — import NIMS SuperCon CSV (40,325 materials)
8. ingestion/pipeline.py — orchestrate all steps
9. Test with 100 papers → verify VS query returns results
10. Seed MVP data: run bulk ingestion for 2023-2026 papers
```

### Phase 3: API (Days 7-9)
```
1. api/services/vector_search.py — Vertex AI VS query with filters
2. api/services/gemini.py — RAG prompt builder + response parser
3. api/routers/search.py — embed → VS → PostgreSQL chunks → paper metadata → merge
4. api/routers/ask.py — embed → VS → PostgreSQL → Gemini → citation format
5. api/routers/materials.py — PostgreSQL query + pagination
6. api/routers/papers.py + similar.py + timeline.py + stats.py
7. api/main.py — CORS, auth middleware, all routers wired
8. api/Dockerfile
9. Deploy + test all endpoints with real API key AND guest quota
10. Write api/tests/*.py
```

### Phase 4: Frontend (Days 10-13)
```
1. frontend/app/layout.tsx + nav + footer
2. Install and configure shadcn/ui
3. components/StatsCards.tsx + components/TcTimeline.tsx (Plotly.js)
4. app/page.tsx — landing with hero, stats, timeline preview, register CTA
5. components/GuestBanner.tsx + components/AuthGuard.tsx
6. app/search/page.tsx — sidebar filters + result cards + guest banner
7. app/ask/page.tsx — chat UI + citation cards + guest banner
8. app/materials/page.tsx — sortable table + export CSV
9. app/materials/[formula]/page.tsx
10. app/paper/[id]/page.tsx
11. app/timeline/page.tsx — full Plotly chart (public)
12. app/stats/page.tsx — statistics (public)
13. app/api-docs/page.tsx — Swagger UI embed (public)
14. app/about/page.tsx
15. frontend/Dockerfile
16. Test at jzis.org/sclib end-to-end
```

### Phase 5: Polish + Production Data (Days 14-15)
```
1. .github/workflows/ingest-daily.yml — daily cron via SSH
2. Daily stats refresh job
3. Run full NIMS SuperCon import (materials table)
4. Run bulk ingestion for 2020-2026 papers (minimum for MVP)
5. README.md with quickstart + Claude Code workflow
6. docs/API.md + DEPLOYMENT.md + VPS_SETUP.md
7. Final end-to-end test: register → verify → search → ask → materials
```

---

## 16. Acceptance Criteria (MVP)

- [ ] `POST /auth/register` → verification email arrives within 30 seconds
- [ ] Email link verifies account, welcome email delivers API key
- [ ] `POST /search` with API key returns results < 500ms
- [ ] Guest gets exactly 3 searches/day; 4th returns 429 with register link
- [ ] `POST /ask` returns cited answer < 5 seconds
- [ ] `GET /materials?family=nickelate&sort=tc_desc` returns La₃Ni₂O₇ top
- [ ] `GET /stats` shows total_papers > 10,000
- [ ] Landing page jzis.org/sclib loads < 3 seconds
- [ ] All 4 Docker containers healthy: `docker compose ps`
- [ ] GitHub push auto-deploys to VPS2 within 2 minutes
- [ ] Existing jzis.org and asrp.jzis.org continue working (not broken)
- [ ] API docs at /sclib/api-docs shows all endpoints

---

## 17. References & Assets

| Resource | Location |
|----------|---------|
| GitHub repo | https://github.com/JackZH26/SCLib_JZIS |
| VPS2 SSH | root@72.62.251.29 |
| Frontend domain | jzis.org/sclib |
| API domain | api.jzis.org/sclib/v1 |
| GCP project | jzis-sclib (create in console.cloud.google.com) |
| arXiv OAI-PMH | http://export.arxiv.org/oai2 (set: cond-mat.supr-con) |
| Semantic Scholar | https://api.semanticscholar.org/graph/v1 |
| NIMS SuperCon | Already downloaded: local path `research/superconductor-databases/supercon2_v22.12.03.csv` |
| Resend | https://resend.com |
| Vertex AI VS docs | https://cloud.google.com/vertex-ai/docs/vector-search/overview |
| License | Apache 2.0 (code) + CC BY 4.0 (data) |

---

*SCLib_JZIS Project Specification v2.1 — VPS2 + Nginx — Confirmed by Jack 2026-04-14*
*Generated by 瓦力 (Wall-E) | JZIS*
