# SCLib_JZIS — JZIS Superconductivity Library

**The Mathlib of superconductivity research.**

Semantic search + materials database + AI-powered Q&A for 200,000+ superconductivity papers (1986–present).

- 🔍 **Search:** Vector semantic search over full-text papers
- 🧪 **Materials:** Structured Tc/pressure database with provenance
- 🤖 **Ask:** RAG-powered Q&A citing specific papers
- 🔓 **Open:** Apache 2.0, REST API, daily updates

**Live:** [jzis.org/sclib](https://jzis.org/sclib) | **API:** [api.jzis.org/sclib/v1](https://api.jzis.org/sclib/v1)

## Quick Start for Developers

Spin up the full stack locally:

```bash
cp .env.example .env        # fill in DB_PASSWORD, JWT_SECRET, INTERNAL_API_KEY, …
docker compose up -d        # postgres + redis + api + frontend
docker compose exec api alembic upgrade head
docker compose run --rm ingestion sclib-ingest --mode smoke --limit 30
```

Then hit `http://localhost:3100` for the Next.js frontend and
`http://localhost:8000/v1/stats` for the FastAPI backend.

## Docs

- [`PROJECT_SPEC.md`](./PROJECT_SPEC.md) — full technical specification
- [`docs/API.md`](./docs/API.md) — HTTP API reference
- [`docs/DEPLOYMENT.md`](./docs/DEPLOYMENT.md) — VPS2 deployment guide
- [`CLAUDE.md`](./CLAUDE.md) — project rules for automated contributors

## Architecture

```
Next.js 14 (frontend)  ──►  FastAPI (api)  ──►  PostgreSQL 16
        │                         │                   │
        │                         ├──► Redis (rate limit / cache)
        │                         ├──► Vertex AI Matching Engine
        │                         └──► Gemini 2.5 Flash (RAG)
        │
        └── Nginx reverse proxy at jzis.org/sclib
```

Data ingestion runs as a one-shot `sclib-ingest` container (profile
`tools`) driven by the nightly cron wrapper in
[`scripts/cron_daily_ingest.sh`](./scripts/cron_daily_ingest.sh).

## Citation

```bibtex
@misc{sclib2026,
  author = {Zhou, Jian},
  title = {SCLib\_JZIS: JZIS Superconductivity Library},
  year = {2026},
  publisher = {GitHub},
  url = {https://github.com/JackZH26/SCLib_JZIS}
}
```

## License

Code: Apache 2.0 | Data: CC BY 4.0 | © 2026 Jian Zhou / JZIS
