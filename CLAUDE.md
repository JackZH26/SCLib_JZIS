# SCLib_JZIS — Claude Code Guide

## Quick Start

You are building **SCLib_JZIS**, the JZIS Superconductivity Library.

**Read first:** `PROJECT_SPEC.md` — this is the complete specification.

## What to Build

A full-stack web application with:
- **Next.js 14** frontend at `jzis.org/sclib`
- **FastAPI** backend at `api.jzis.org/sclib/v1`
- **PostgreSQL** for all data (papers, materials, users, chunks)
- **Redis** for rate limiting and caching
- **Vertex AI Vector Search** for semantic search
- **Gemini 2.5 Flash** for RAG Q&A

All services run in **Docker Compose** on VPS2 (72.62.251.29), behind the existing **Nginx** reverse proxy.

## Build Order

Follow Section 15 of PROJECT_SPEC.md **exactly**:

```
Phase 0: VPS2 + Docker + Nginx setup (Day 1)
Phase 1: PostgreSQL schema + User auth + Email verification (Days 2-3)
Phase 2: Ingestion pipeline (arXiv → parse → embed → VS + PostgreSQL) (Days 4-6)
Phase 3: FastAPI endpoints (Days 7-9)
Phase 4: Next.js frontend (Days 10-13)
Phase 5: Production data + automation (Days 14-15)
```

## Key Constraints

1. **Do NOT break existing sites:** `jzis.org` and `asrp.jzis.org` must keep working
2. **Nginx, not Caddy** — VPS2 already uses Nginx + Let's Encrypt
3. **PostgreSQL, not Firestore** — all metadata on VPS2 in PostgreSQL
4. **Vertex AI VS** for vectors — don't substitute with other solutions
5. **uv** for Python packages, **pnpm** for Node packages
6. All Docker containers bind to `127.0.0.1` only (Nginx is the public gateway)

## Access Control Summary

- **Guest:** 3 API queries/day/IP (Redis counter), can view public pages
- **Registered:** Full access via `X-API-Key: scl_xxx` header
- Email must be verified before account is active and API key is issued

## Important Paths

```
PROJECT_SPEC.md          ← Full specification (read this)
docker-compose.yml       ← All 4 services (frontend, api, postgres, redis)
nginx/sclib.conf         ← Nginx config snippet for VPS2
.env.example             ← All required environment variables
api/                     ← FastAPI app
frontend/                ← Next.js app
ingestion/               ← Data ingestion pipeline
scripts/setup_vps2.sh    ← VPS2 initial setup
```

## When in Doubt

Check `PROJECT_SPEC.md` — every API endpoint, database schema, and component is specified there.
