# SCLib_JZIS — Project Specification for Claude Code
> **Version:** 2.0 | **Date:** 2026-04-14 | **Author:** Jian Zhou / JZIS
> **Repo:** https://github.com/JackZH26/SCLib_JZIS
> **Domain:** jzis.org/sclib
> **Deployment:** Self-hosted VPS (all services)
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

## 1. Tech Stack (Authoritative — All on VPS)

| Layer | Technology | Hosting |
|-------|-----------|---------|
| **Frontend** | Next.js 14 (App Router) + Tailwind CSS + shadcn/ui | VPS container |
| **API** | FastAPI (Python 3.11) | VPS container |
| **Reverse Proxy** | Caddy (auto HTTPS via Let's Encrypt) | VPS container |
| **Database** | PostgreSQL 16 | VPS container |
| **Cache / Rate Limit** | Redis 7 | VPS container |
| **Email** | SMTP via Resend API (or SendGrid) | External service |
| **Vector DB** | **Vertex AI Vector Search** | GCP managed |
| **Embedding Model** | Vertex AI `text-embedding-005` (768d) | GCP managed |
| **LLM (RAG + NER)** | Gemini 2.5 Flash | GCP managed |
| **Object Storage** | Google Cloud Storage | GCP managed |
| **LaTeX Parser** | Custom Python + Pandoc | VPS (ingestion) |
| **PDF Fallback** | `opendataloader-pdf` v2.2.0 | VPS (ingestion) |
| **CI/CD** | GitHub Actions | Cloud |
| **Package Manager** | `uv` (Python) + `pnpm` (Node) | — |

### VPS Recommended Configuration
Current VPS may need upgrading. Recommended minimum for production:

| Spec | Minimum | Recommended |
|------|---------|-------------|
| **CPU** | 4 vCPU | 8 vCPU |
| **RAM** | 8 GB | 16 GB |
| **SSD** | 100 GB NVMe | 200 GB NVMe |
| **Bandwidth** | 4 TB/month | 8 TB/month |

**Reason:** Next.js SSR (~512MB) + FastAPI (~512MB) + PostgreSQL (~1GB) + Redis (~256MB) + ingestion pipeline (~2-4GB peak during embedding batches)

Hostinger equivalent: **KVM 4** (~$10/mo minimum) or **KVM 8** (~$20/mo recommended).

### GCP Services Required (data layer only, no servers)
```
Vertex AI (Vector Search + Embedding API + Gemini)
Cloud Storage (PDF files + parsed text)
```
Note: Firestore is **NOT used** — PostgreSQL on VPS handles all metadata.

---

## 2. VPS Deployment Architecture

```
Internet
    │
    ▼
┌─────────────────────────────────────────────────┐
│  Caddy (80/443)                                  │
│  jzis.org/sclib      → sclib-frontend:3000       │
│  api.jzis.org/sclib  → sclib-api:8000            │
│  Auto HTTPS (Let's Encrypt)                      │
└─────────┬──────────────────────┬────────────────┘
          │                      │
    ┌─────▼──────┐        ┌──────▼─────┐
    │  Next.js   │        │  FastAPI   │
    │  :3000     │        │  :8000     │
    └────────────┘        └──────┬─────┘
                                 │
              ┌──────────────────┼──────────────────┐
              │                  │                   │
        ┌─────▼──────┐   ┌───────▼───┐   ┌─────────▼────┐
        │ PostgreSQL │   │   Redis   │   │  GCP (ext.)  │
        │   :5432    │   │   :6379   │   │ Vertex AI VS │
        │ (internal) │   │ (internal)│   │ Gemini API   │
        └────────────┘   └───────────┘   │ Cloud Storage│
                                         └──────────────┘
```

### Docker Compose Structure
```yaml
# docker-compose.yml (single file manages all services)
services:
  caddy:
    image: caddy:2
    ports: ["80:80", "443:443"]
    volumes: ["./Caddyfile:/etc/caddy/Caddyfile", "caddy_data:/data"]
    depends_on: [frontend, api]

  frontend:
    build: ./frontend
    environment:
      - NEXT_PUBLIC_API_BASE=https://api.jzis.org/sclib/v1

  api:
    build: ./api
    environment:
      - DATABASE_URL=postgresql://sclib:${DB_PASSWORD}@postgres:5432/sclib
      - REDIS_URL=redis://redis:6379
      - GCP_PROJECT=${GCP_PROJECT}
    depends_on: [postgres, redis]
    volumes:
      - ./credentials/gcp-sa.json:/credentials/gcp-sa.json:ro

  postgres:
    image: postgres:16
    environment:
      POSTGRES_DB: sclib
      POSTGRES_USER: sclib
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes: ["postgres_data:/var/lib/postgresql/data"]

  redis:
    image: redis:7-alpine
    volumes: ["redis_data:/data"]

volumes:
  caddy_data:
  postgres_data:
  redis_data:
```

### Caddyfile
```
jzis.org/sclib {
    reverse_proxy frontend:3000
}

api.jzis.org {
    handle /sclib/* {
        reverse_proxy api:8000
    }
}
```

---

## 3. Repository Structure

```
SCLib_JZIS/
├── README.md
├── CONTRIBUTING.md
├── LICENSE                          # Apache 2.0
├── docker-compose.yml               # All VPS services
├── docker-compose.dev.yml           # Local dev overrides
├── Caddyfile                        # Reverse proxy config
├── .env.example                     # Environment variable template
├── .github/
│   └── workflows/
│       ├── deploy.yml               # SSH deploy to VPS on main push
│       ├── test.yml                 # Run tests on PR
│       └── ingest-daily.yml        # Daily arXiv update cron
├── api/                             # FastAPI backend
│   ├── pyproject.toml
│   ├── Dockerfile
│   ├── alembic/                     # Database migrations
│   │   ├── env.py
│   │   └── versions/
│   ├── main.py
│   ├── routers/
│   │   ├── search.py                # POST /search
│   │   ├── ask.py                   # POST /ask
│   │   ├── materials.py             # GET /materials
│   │   ├── papers.py                # GET /paper/{id}
│   │   ├── stats.py                 # GET /stats
│   │   ├── similar.py               # GET /similar/{id}
│   │   ├── timeline.py              # GET /timeline
│   │   └── auth.py                  # POST /register, /verify, /login, /keys
│   ├── services/
│   │   ├── vector_search.py         # Vertex AI Vector Search client
│   │   ├── embedding.py             # text-embedding-005 client
│   │   ├── gemini.py                # RAG + NER Gemini client
│   │   ├── storage.py               # GCS client
│   │   ├── email.py                 # Resend email service
│   │   ├── rate_limit.py            # Redis-based rate limiting
│   │   └── auth.py                  # API key management, JWT
│   ├── models/
│   │   ├── db.py                    # SQLAlchemy models (PostgreSQL)
│   │   ├── paper.py                 # Paper Pydantic models
│   │   ├── material.py              # Material Pydantic models
│   │   ├── user.py                  # User Pydantic models
│   │   ├── search.py
│   │   └── ask.py
│   └── tests/
│       ├── test_search.py
│       ├── test_ask.py
│       ├── test_auth.py
│       └── test_materials.py
├── ingestion/                       # Data pipeline (runs on VPS or local)
│   ├── pyproject.toml
│   ├── collect/
│   │   ├── arxiv_oai.py
│   │   └── semantic_scholar.py
│   ├── parse/
│   │   ├── latex_parser.py
│   │   └── pdf_parser.py
│   ├── chunk/
│   │   └── chunker.py
│   ├── embed/
│   │   └── embedder.py
│   ├── index/
│   │   └── indexer.py               # Vertex AI VS + PostgreSQL
│   ├── extract/
│   │   └── material_ner.py
│   └── pipeline.py
├── frontend/                        # Next.js app
│   ├── package.json
│   ├── next.config.ts
│   ├── Dockerfile
│   ├── app/
│   │   ├── layout.tsx
│   │   ├── page.tsx                 # Landing (guest accessible)
│   │   ├── search/page.tsx          # Requires auth (3 free/day guest)
│   │   ├── ask/page.tsx             # Requires auth (3 free/day guest)
│   │   ├── materials/
│   │   │   ├── page.tsx             # Requires auth
│   │   │   └── [formula]/page.tsx
│   │   ├── paper/[id]/page.tsx
│   │   ├── timeline/page.tsx        # Public
│   │   ├── stats/page.tsx           # Public
│   │   ├── api-docs/page.tsx        # Public
│   │   ├── about/page.tsx           # Public
│   │   └── auth/
│   │       ├── register/page.tsx    # Registration form
│   │       ├── verify/page.tsx      # Email verification landing
│   │       ├── login/page.tsx
│   │       └── dashboard/page.tsx   # API key management
│   └── components/
│       ├── ui/
│       ├── SearchBar.tsx
│       ├── PaperCard.tsx
│       ├── MaterialTable.tsx
│       ├── TcTimeline.tsx
│       ├── ChatInterface.tsx
│       ├── StatsCards.tsx
│       ├── GuestBanner.tsx          # Shows remaining free queries
│       └── AuthGuard.tsx            # Wraps protected pages
├── scripts/
│   ├── setup_vps.sh                 # Initial VPS setup script
│   ├── deploy.sh                    # Manual deploy script
│   ├── init_db.py                   # Create tables + indexes
│   ├── create_vector_index.py       # Vertex AI VS index creation
│   └── import_nims.py               # NIMS SuperCon CSV import
└── docs/
    ├── API.md
    ├── DEPLOYMENT.md
    └── VPS_SETUP.md
```

---

## 4. Database Schema (PostgreSQL)

### 4.1 Users Table

```sql
CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email           VARCHAR(255) UNIQUE NOT NULL,
    email_verified  BOOLEAN DEFAULT FALSE,
    name            VARCHAR(255) NOT NULL,
    institution     VARCHAR(500),
    country         VARCHAR(100),
    age             SMALLINT CHECK (age >= 13 AND age <= 120),
    research_area   VARCHAR(255),    -- e.g. "High-temperature superconductivity"
    purpose         TEXT,            -- Why they want access (free text)
    password_hash   VARCHAR(255) NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    last_login      TIMESTAMPTZ,
    is_active       BOOLEAN DEFAULT FALSE,   -- False until email verified
    is_admin        BOOLEAN DEFAULT FALSE
);

-- Email verification tokens
CREATE TABLE email_verifications (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID REFERENCES users(id) ON DELETE CASCADE,
    token       VARCHAR(64) UNIQUE NOT NULL,
    expires_at  TIMESTAMPTZ NOT NULL,
    used        BOOLEAN DEFAULT FALSE,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- API Keys (registered users get one key by default, can rotate)
CREATE TABLE api_keys (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID REFERENCES users(id) ON DELETE CASCADE,
    key_hash    VARCHAR(64) UNIQUE NOT NULL,  -- SHA-256 of actual key
    key_prefix  VARCHAR(8) NOT NULL,          -- First 8 chars for display: "scl_xxxx"
    name        VARCHAR(100),                 -- User-assigned label
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    last_used   TIMESTAMPTZ,
    revoked     BOOLEAN DEFAULT FALSE
);
```

### 4.2 Papers Table

```sql
CREATE TABLE papers (
    id                  VARCHAR(100) PRIMARY KEY,   -- "arxiv:2306.07275"
    source              VARCHAR(20) NOT NULL,        -- "arxiv"|"semantic_scholar"
    arxiv_id            VARCHAR(20),
    doi                 VARCHAR(200),
    title               TEXT NOT NULL,
    authors             JSONB NOT NULL,              -- ["Author A", "Author B"]
    affiliations        JSONB,
    date_submitted      DATE,
    date_published      DATE,
    journal             VARCHAR(300),
    abstract            TEXT NOT NULL,
    categories          JSONB,                       -- ["cond-mat.supr-con"]
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

### 4.3 Materials Table

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
    records             JSONB DEFAULT '[]',        -- Array of TcRecord objects
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_materials_family ON materials(family);
CREATE INDEX idx_materials_tc ON materials(tc_max DESC NULLS LAST);
CREATE INDEX idx_materials_year ON materials(discovery_year);
```

### 4.4 Chunks Table (text payload for VS results)

```sql
CREATE TABLE chunks (
    id              VARCHAR(200) PRIMARY KEY,  -- "arxiv:2306.07275_chunk_005"
    paper_id        VARCHAR(100) REFERENCES papers(id),
    title           TEXT,
    authors_short   VARCHAR(200),
    year            SMALLINT,
    section         VARCHAR(200),
    chunk_index     SMALLINT,
    text            TEXT NOT NULL,
    material_family VARCHAR(50),
    materials_mentioned JSONB DEFAULT '[]',
    has_equation    BOOLEAN DEFAULT FALSE,
    has_table       BOOLEAN DEFAULT FALSE
);

CREATE INDEX idx_chunks_paper ON chunks(paper_id);
```

### 4.5 Stats Cache Table

```sql
CREATE TABLE stats_cache (
    key         VARCHAR(100) PRIMARY KEY,
    value       JSONB NOT NULL,
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);
-- Rows: 'global', 'by_year', 'by_family', 'tc_records'
-- Refreshed by daily cron
```

---

## 5. User Registration & Authentication

### 5.1 Registration Flow

```
User fills form → POST /auth/register
    → Validate fields (email format, age 13+, required fields)
    → Check email not already registered
    → Hash password (bcrypt, cost 12)
    → Create user (is_active=False)
    → Generate 64-char verification token (expires 24h)
    → Send verification email
    → Return: "Check your email to verify your account"

User clicks link → GET /auth/verify?token=xxxx
    → Validate token (exists, not expired, not used)
    → Set user.is_active = True
    → Mark token as used
    → Generate API key (format: "scl_" + 40 random chars)
    → Send welcome email with API key
    → Redirect to /auth/dashboard

User logs in → POST /auth/login
    → Validate email/password
    → Check is_active (if False: "Please verify your email")
    → Return JWT (24h expiry) + user info
```

### 5.2 Registration Form Fields

```python
class RegisterRequest(BaseModel):
    # Required
    email: EmailStr
    password: str               # min 8 chars, validated
    name: str                   # Full name, min 2 chars
    age: int                    # Must be 13-120
    
    # Optional but encouraged
    institution: Optional[str]  # University/company/independent
    country: Optional[str]      # Country of residence
    research_area: Optional[str] # e.g. "High-Tc superconductivity"
    purpose: Optional[str]      # How they plan to use SCLib (max 500 chars)
```

### 5.3 Verification Email Template

```
Subject: Verify your SCLib_JZIS account

Dear {name},

Thank you for registering with SCLib_JZIS, the JZIS Superconductivity Library.

Please verify your email address by clicking the link below:
https://jzis.org/sclib/auth/verify?token={token}

This link expires in 24 hours.

Once verified, you will receive your API key to access the full SCLib database.

Best regards,
JZIS Team | jzis.org
```

### 5.4 Welcome Email (post-verification)

```
Subject: Your SCLib_JZIS API Key

Dear {name},

Your account has been verified! Here is your API key:

  {api_key}

Keep this key secure. Use it in requests as:
  X-API-Key: {api_key}

API Base URL: https://api.jzis.org/sclib/v1
Documentation: https://jzis.org/sclib/api-docs

You can manage your keys at: https://jzis.org/sclib/auth/dashboard

Best regards,
JZIS Team
```

### 5.5 API Key Format & Authentication

```python
# Key format: "scl_" + 40 random URL-safe chars
# Example: "scl_aB3kL9mN2pQ7rS4tU1vW8xY5zA6bC0dE"

# In requests:
# Header: X-API-Key: scl_xxxxxxxxxxxxxxxxxxxx

# Validation middleware:
async def verify_api_key(x_api_key: str = Header(None), request: Request = None):
    if not x_api_key:
        # Check guest allowance
        ip = get_client_ip(request)
        remaining = await check_guest_quota(ip)
        if remaining <= 0:
            raise HTTPException(429, "Guest quota exceeded. Register for free access.")
        await decrement_guest_quota(ip)
        return GuestUser(ip=ip, remaining=remaining-1)
    
    # Hash and look up in DB
    key_hash = sha256(x_api_key.encode()).hexdigest()
    api_key = await db.fetch("SELECT * FROM api_keys WHERE key_hash=$1 AND revoked=FALSE", key_hash)
    if not api_key:
        raise HTTPException(401, "Invalid API key")
    
    user = await db.fetch("SELECT * FROM users WHERE id=$1 AND is_active=TRUE", api_key.user_id)
    if not user:
        raise HTTPException(401, "Account inactive")
    
    # Update last_used
    await db.execute("UPDATE api_keys SET last_used=NOW() WHERE id=$1", api_key.id)
    return AuthenticatedUser(user=user, key=api_key)
```

---

## 6. Access Control & Rate Limiting

### 6.1 Guest Access (no API key)

```python
# Redis key: "guest_quota:{date}:{ip}"
# TTL: 86400 seconds (resets at midnight)

GUEST_DAILY_LIMIT = 3  # per IP per day

async def check_guest_quota(ip: str) -> int:
    """Returns remaining queries for this IP today"""
    redis_key = f"guest_quota:{date.today()}:{ip}"
    used = await redis.get(redis_key) or 0
    return max(0, GUEST_DAILY_LIMIT - int(used))

async def decrement_guest_quota(ip: str):
    redis_key = f"guest_quota:{date.today()}:{ip}"
    await redis.incr(redis_key)
    await redis.expire(redis_key, 86400)
```

### 6.2 Page Access Matrix

| Page | Guest | Registered |
|------|-------|-----------|
| `/sclib` (landing) | ✅ Full | ✅ Full |
| `/sclib/timeline` | ✅ Full | ✅ Full |
| `/sclib/stats` | ✅ Full | ✅ Full |
| `/sclib/about` | ✅ Full | ✅ Full |
| `/sclib/api-docs` | ✅ Full | ✅ Full |
| `/sclib/auth/*` | ✅ Full | ✅ Full |
| `/sclib/search` | ⚠️ 3/day | ✅ Unlimited |
| `/sclib/ask` | ⚠️ 3/day | ✅ Unlimited |
| `/sclib/materials` | ⚠️ 3/day | ✅ Unlimited |
| `/sclib/paper/{id}` | ⚠️ 3/day | ✅ Unlimited |
| API endpoints | ⚠️ 3/day | ✅ Unlimited |

### 6.3 Guest Banner Component

```tsx
// components/GuestBanner.tsx
// Shows on all rate-limited pages for guests
export function GuestBanner({ remaining }: { remaining: number }) {
  return (
    <div className="bg-amber-50 border border-amber-200 rounded-lg p-4 mb-6">
      <p className="text-amber-800">
        You have <strong>{remaining} free queries</strong> remaining today.{" "}
        <Link href="/sclib/auth/register" className="underline font-semibold">
          Register for free
        </Link>{" "}
        to get unlimited access.
      </p>
    </div>
  );
}
```

---

## 7. API Specification (FastAPI)

**Base URL:** `https://api.jzis.org/sclib/v1`
**Auth:** `X-API-Key: scl_xxxx` (registered) or no key (guest, 3/day/IP)

### 7.1 Auth Endpoints

```
POST /auth/register          — Create account (triggers verification email)
GET  /auth/verify?token=xxx  — Verify email (redirect to dashboard)
POST /auth/login             — Login → JWT
POST /auth/logout            — Invalidate JWT
GET  /auth/me                — Get current user info
POST /auth/keys              — Generate new API key
DELETE /auth/keys/{key_id}   — Revoke API key
```

### 7.2 POST /auth/register

```python
# Request: RegisterRequest (see Section 5.2)
# Response:
{
    "message": "Registration successful. Please check your email to verify your account.",
    "email": "user@example.com"
}
# Errors: 400 (invalid fields), 409 (email already registered)
```

### 7.3 POST /search

```python
class SearchRequest(BaseModel):
    query: str
    top_k: int = 20                    # max 100
    filters: Optional[SearchFilters]
    sort: str = "relevance"            # "relevance"|"date_desc"|"citations_desc"
    include_chunks: bool = True

class SearchFilters(BaseModel):
    year_min: Optional[int]
    year_max: Optional[int]
    material_family: Optional[List[str]]
    tc_min: Optional[float]
    pressure_max: Optional[float]
    exclude_retracted: bool = True

class SearchResponse(BaseModel):
    total: int
    results: List[SearchResult]
    query_time_ms: int
    guest_remaining: Optional[int]     # Included for guest users
```

### 7.4 POST /ask

```python
class AskRequest(BaseModel):
    question: str
    max_sources: int = 10
    filters: Optional[SearchFilters]
    language: str = "auto"             # "auto"|"en"|"zh"

class AskResponse(BaseModel):
    answer: str                        # Markdown with [1][2] citations
    sources: List[AskSource]
    tokens_used: int
    guest_remaining: Optional[int]
```

**RAG System Prompt:**
```
You are SCLib, an AI research assistant for the superconductivity community.
Answer ONLY based on the provided papers. Cite as [1], [2], etc.
Be precise about Tc values, pressures, and chemical formulas.
Distinguish experimental measurements from theoretical predictions.
If the answer is not in the papers, say so clearly.
Language: {language}
```

### 7.5 GET /materials

```
GET /materials?family=nickelate&tc_min=50&pressure_max=0&sort=tc_desc&limit=50&offset=0
```
Returns paginated list of Material objects.

### 7.6 GET /materials/{formula}

Full Material object with all TcRecords, timeline, related materials.

### 7.7 GET /paper/{id}

`/paper/arxiv:2306.07275` — Full Paper object.

### 7.8 GET /similar/{paper_id}

```
GET /similar/arxiv:2306.07275?top_k=10
```

### 7.9 GET /stats

Returns global stats. Refreshed by daily cron. Publicly accessible.

### 7.10 GET /timeline

```
GET /timeline?family=all&ambient_only=false
```
Returns Tc record history for Plotly visualization.

---

## 8. Frontend Pages Specification

### 8.1 Landing Page (`/sclib`) — Public

- Hero: "The Superconductivity Library" + tagline + search bar
- Stats cards: total papers, materials, coverage dates
- Tc Timeline preview (interactive Plotly chart)
- Material family grid (8 families with paper counts)
- "Register Free" CTA prominently featured
- Latest 5 papers indexed

### 8.2 Registration Page (`/sclib/auth/register`)

Form fields:
```
Email *
Password * (min 8 chars, strength indicator)
Confirm Password *
Full Name *
Age * (number input, 13+)
Institution (text, e.g. "MIT", "Independent Researcher")
Country (dropdown)
Research Area (text, e.g. "High-temperature superconductivity")
Purpose (textarea, "How do you plan to use SCLib?", max 500 chars)

[ ] I agree to the Terms of Use and Privacy Policy *

[Register for Free]
```

### 8.3 Email Verification Page (`/sclib/auth/verify`)

- Shows success/failure of verification
- On success: show API key + link to dashboard
- On failure (expired/invalid): offer to resend verification

### 8.4 Dashboard (`/sclib/auth/dashboard`) — Auth required

- User profile (institution, research area)
- API Key management (show/hide, copy, rotate, revoke)
- Usage stats (queries this month)

### 8.5 Search Page (`/sclib/search`) — 3/day guest, unlimited registered

- Guest banner (remaining queries)
- Sidebar filters + main results
- Login prompt if guest quota exhausted

### 8.6 Ask Page (`/sclib/ask`) — 3/day guest, unlimited registered

- Chat interface with citation cards
- Guest banner
- Login prompt if exhausted

### 8.7 Materials Page (`/sclib/materials`) — 3/day guest

- Sortable, filterable table
- Export CSV (registered only)

### 8.8 Timeline Page (`/sclib/timeline`) — Public

- Full interactive Plotly chart, no auth required

### 8.9 Stats Page (`/sclib/stats`) — Public

- All statistics, public access

---

## 9. Email Service (Resend)

```python
# api/services/email.py
import resend

resend.api_key = RESEND_API_KEY

async def send_verification_email(to: str, name: str, token: str):
    verify_url = f"https://jzis.org/sclib/auth/verify?token={token}"
    resend.Emails.send({
        "from": "SCLib <noreply@jzis.org>",
        "to": to,
        "subject": "Verify your SCLib_JZIS account",
        "html": render_template("verify.html", name=name, url=verify_url)
    })

async def send_welcome_email(to: str, name: str, api_key: str):
    resend.Emails.send({
        "from": "SCLib <noreply@jzis.org>",
        "to": to,
        "subject": "Your SCLib_JZIS API Key",
        "html": render_template("welcome.html", name=name, api_key=api_key)
    })
```

---

## 10. Ingestion Pipeline

### 10.1 Chunking Strategy (same as v1.0)

```python
MAX_TOKENS = 512
OVERLAP_TOKENS = 64
MIN_CHUNK_TOKENS = 100

def chunk_paper(parsed: dict) -> List[dict]:
    # Section-aware chunking
    # Preserve equations as atomic units
    # Prepend "Title: {title}\nSection: {section}\n" to each chunk
    # Skip reference list sections
```

### 10.2 Vertex AI Vector Search

```python
# Upsert to VS index
# Store text in PostgreSQL chunks table (not Firestore)

from google.cloud import aiplatform

def upsert_vectors(datapoints: List[dict]):
    """Batch upsert to Vertex AI VS"""
    index = aiplatform.MatchingEngineIndex(INDEX_NAME)
    index.upsert_datapoints(datapoints=datapoints)
```

### 10.3 Daily Update Cron

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
      - name: SSH to VPS and run ingestion
        uses: appleboy/ssh-action@v1
        with:
          host: ${{ secrets.VPS_HOST }}
          username: ${{ secrets.VPS_USER }}
          key: ${{ secrets.VPS_SSH_KEY }}
          script: |
            cd /opt/SCLib_JZIS
            docker compose run --rm api python ingestion/pipeline.py --mode incremental
```

---

## 11. Environment Variables

### `.env` on VPS (single file)

```bash
# Database
DB_PASSWORD=<strong-random-password>
DATABASE_URL=postgresql://sclib:${DB_PASSWORD}@postgres:5432/sclib

# Redis
REDIS_URL=redis://redis:6379

# GCP
GCP_PROJECT=jzis-sclib
GCP_REGION=us-central1
GOOGLE_APPLICATION_CREDENTIALS=/credentials/gcp-sa.json
VERTEX_AI_INDEX_ENDPOINT=projects/.../locations/.../indexEndpoints/...
VERTEX_AI_DEPLOYED_INDEX_ID=sclib_papers_v1
GCS_BUCKET=sclib-jzis

# AI Models
GEMINI_MODEL=gemini-2.5-flash
EMBEDDING_MODEL=text-embedding-005

# Auth
JWT_SECRET=<strong-random-secret>
JWT_EXPIRY_HOURS=24

# Email (Resend)
RESEND_API_KEY=re_xxxxxxxxxxxx

# App
FRONTEND_URL=https://jzis.org/sclib
API_BASE_URL=https://api.jzis.org/sclib/v1
GUEST_DAILY_LIMIT=3
```

### Vercel / Frontend (NOT USED — all on VPS)

All environment is in `.env` on VPS. Frontend container reads from same compose env.

---

## 12. VPS Setup Script

```bash
#!/bin/bash
# scripts/setup_vps.sh
# Run once on fresh VPS

set -e

# Install Docker
curl -fsSL https://get.docker.com | sh
usermod -aG docker $USER

# Install Docker Compose v2
apt-get install -y docker-compose-plugin

# Open ports
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 22/tcp
ufw enable

# Create app directory
mkdir -p /opt/SCLib_JZIS
cd /opt/SCLib_JZIS

# Clone repo
git clone https://github.com/JackZH26/SCLib_JZIS.git .

# Create env file (fill in manually)
cp .env.example .env
echo "⚠️  Edit /opt/SCLib_JZIS/.env before starting!"

# Create credentials directory
mkdir -p credentials
echo "⚠️  Place GCP service account JSON at credentials/gcp-sa.json"

echo "Setup complete. Edit .env and credentials/, then run: docker compose up -d"
```

---

## 13. CI/CD: Auto Deploy on Push

```yaml
# .github/workflows/deploy.yml
name: Deploy to VPS
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
          host: ${{ secrets.VPS_HOST }}
          username: ${{ secrets.VPS_USER }}
          key: ${{ secrets.VPS_SSH_KEY }}
          script: |
            cd /opt/SCLib_JZIS
            git pull origin main
            docker compose build
            docker compose up -d
            docker compose exec api alembic upgrade head
            echo "Deployed successfully"
```

---

## 14. Cost Estimates (Updated — All VPS)

### 14.1 Monthly Operations

| Item | Cost/month |
|------|-----------|
| **VPS (8 vCPU, 16GB RAM)** | ~$20 (Hostinger KVM 8) |
| Vertex AI Vector Search (1 node) | ~$65 |
| Vertex AI Embedding (daily updates) | ~$0.01 |
| Gemini Flash (RAG + NER) | ~$3 |
| Cloud Storage (PDFs + parsed text) | ~$6 |
| Resend Email (free tier: 3,000/month) | $0 |
| Domain renewal (jzis.org) | ~$1 |
| **Monthly total** | **~$95** |

### 14.2 vs Original Plan (Vercel + Cloud Run)

| Item | Old Plan | New Plan (VPS) |
|------|---------|---------------|
| Frontend | Vercel ($0) | VPS (included) |
| API | Cloud Run (~$5) | VPS (included) |
| Database | Firestore (~$5) | PostgreSQL on VPS (included) |
| VPS | ~$10 (existing) | ~$20 (upgraded) |
| Vector Search | VS ($65) | VS ($65) — same |
| **Total** | ~$85 | **~$95** |

Slight cost increase (~$10/mo) but full control, no vendor dependency, easier maintenance.

---

## 15. Build Order for Claude Code

Build in this exact order. Each phase must be functional before proceeding.

### Phase 0: VPS + Repo Setup (Day 1)
```
1. Clone repo, set up structure per Section 3
2. Create docker-compose.yml with all 5 services
3. Create Caddyfile
4. Run scripts/setup_vps.sh on VPS
5. Verify all containers start: caddy, api, frontend, postgres, redis
6. Create Vertex AI VS index (scripts/create_vector_index.py)
7. Set up GitHub Actions secrets (VPS_HOST, VPS_USER, VPS_SSH_KEY, GCP_*)
8. Verify deploy.yml works on push to main
```

### Phase 1: Database + Auth (Days 2-3)
```
1. api/models/db.py — SQLAlchemy models for all tables
2. alembic/ setup + initial migration
3. api/services/email.py — Resend integration
4. api/services/auth.py — bcrypt, JWT, API key generation
5. api/services/rate_limit.py — Redis guest quota
6. api/routers/auth.py — all auth endpoints
7. Test full flow: register → email → verify → get API key → login
8. frontend/app/auth/* pages — register form, verify page, dashboard, login
9. Test email delivery to real inbox
```

### Phase 2: Ingestion Pipeline (Days 4-6)
```
1. ingestion/collect/arxiv_oai.py — OAI-PMH bulk + incremental
2. ingestion/parse/latex_parser.py + pdf_parser.py
3. ingestion/chunk/chunker.py
4. ingestion/embed/embedder.py — Vertex AI batch
5. ingestion/index/indexer.py — VS upsert + PostgreSQL chunks insert
6. ingestion/extract/material_ner.py — Gemini NER
7. scripts/import_nims.py — import NIMS CSV to materials table
8. ingestion/pipeline.py — orchestrate
9. Test with 100 papers → verify VS query works
10. Run bulk ingestion for 2023-2026 papers (MVP seed)
```

### Phase 3: API (Days 7-9)
```
1. api/services/vector_search.py — Vertex AI VS query client
2. api/services/gemini.py — RAG + NER
3. api/services/storage.py — GCS client
4. api/routers/search.py — embed → VS → PostgreSQL → merge
5. api/routers/ask.py — embed → VS → PostgreSQL → Gemini → citations
6. api/routers/materials.py — PostgreSQL query + pagination
7. api/routers/papers.py + similar.py + timeline.py + stats.py
8. api/main.py — wire routers, CORS, auth middleware
9. Deploy + test all endpoints with real API key + guest quota
10. Write tests
```

### Phase 4: Frontend (Days 10-13)
```
1. Layout, navigation, footer
2. Install shadcn/ui components
3. Landing page with stats + search preview
4. Search page with guest banner + filters
5. Ask page (chat UI)
6. Materials table + detail page
7. Paper detail page
8. Timeline page (Plotly.js)
9. Stats page
10. API docs (Swagger UI embed)
11. About page + citation format
12. AuthGuard component (wrap protected pages)
13. Responsive mobile layout
14. Deploy + verify jzis.org/sclib works end-to-end
```

### Phase 5: Polish + Automation (Days 14-15)
```
1. .github/workflows/ingest-daily.yml — daily cron via SSH
2. scripts/init_db.py — create all indexes
3. Daily stats refresh cron
4. README.md with quickstart
5. CONTRIBUTING.md
6. docs/API.md, DEPLOYMENT.md, VPS_SETUP.md
7. Import full NIMS SuperCon dataset
8. Run full bulk ingestion (2020-2026 papers minimum)
```

---

## 16. Acceptance Criteria (MVP)

- [ ] `POST /auth/register` → email arrives in inbox within 30 seconds
- [ ] Email verification link works, API key delivered in welcome email
- [ ] `POST /search` with API key returns relevant papers < 500ms
- [ ] Guest gets exactly 3 searches/day, 4th returns 429 with register prompt
- [ ] `POST /ask` returns cited answer < 5 seconds
- [ ] `GET /materials?family=nickelate&sort=tc_desc` returns La₃Ni₂O₇ top
- [ ] `GET /stats` shows total_papers > 10,000
- [ ] Landing page loads at jzis.org/sclib < 3 seconds
- [ ] Registration form validates all required fields
- [ ] API docs accessible at /sclib/api-docs
- [ ] GitHub push auto-deploys to VPS within 2 minutes
- [ ] All 5 Docker containers healthy: `docker compose ps`

---

## 17. References & Assets

- **Repo:** https://github.com/JackZH26/SCLib_JZIS
- **Domain:** jzis.org/sclib (DNS → VPS IP 76.13.191.130, configure in Cloudflare)
- **GCP Project:** jzis-sclib (create in GCP Console)
- **arXiv OAI-PMH:** http://export.arxiv.org/oai2 (set: cond-mat.supr-con)
- **Semantic Scholar API:** https://api.semanticscholar.org/graph/v1
- **NIMS SuperCon data:** local at `research/superconductor-databases/supercon2_v22.12.03.csv` (40,325 records)
- **Resend:** https://resend.com (email service, free tier 3K/month)
- **Vertex AI VS docs:** https://cloud.google.com/vertex-ai/docs/vector-search/overview
- **License:** Apache 2.0 (code) + CC BY 4.0 (data)

---

*SCLib_JZIS Project Specification v2.0 — All on VPS — Confirmed by Jack 2026-04-14*
*Generated by 瓦力 (Wall-E) | JZIS*
