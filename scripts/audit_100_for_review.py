#!/usr/bin/env python3
"""Manual audit tool for the 100-paper validation set.

A self-contained FastAPI app (single file, no template files) that lets one
reviewer audit the LLM-extracted geography / formulas / families / Tc values /
theoretical-vs-experimental tags on a fixed 100-paper random sample.

CLI:
    audit_100_for_review.py init   --n 100 --seed 0.42   # sample from Postgres
    audit_100_for_review.py serve  --port 8765           # run review UI
    audit_100_for_review.py stats                        # print stats JSON
    audit_100_for_review.py export --out results.csv     # dump results CSV

Workflow:
    1) On VPS2 (where Postgres lives), once:
        ssh root@vps2 'cd /opt/SCLib_JZIS && docker compose run --rm \\
            -v $(pwd)/audit:/audit ingestion \\
            python /app/scripts/audit_100_for_review.py init \\
              --db /audit/audit_review.db --n 100'

    2) Pull the SQLite file back to your local machine:
        scp root@vps2:/opt/SCLib_JZIS/audit/audit_review.db ./audit/

    3) Locally, install runtime deps and serve:
        pip install fastapi uvicorn jinja2 sqlalchemy psycopg2-binary
        python scripts/audit_100_for_review.py serve --reviewer Jack

    4) Open http://127.0.0.1:8765, review each paper, click Save.

    5) When done:
        python scripts/audit_100_for_review.py stats
        python scripts/audit_100_for_review.py export --out audit/exports/results.csv

Storage layout (gitignored under /audit/):
    audit/audit_review.db       -- SQLite, the canonical store
    audit/exports/*.csv         -- CSV exports

Design notes:
    * SQLite (not Postgres) because the audit is local + one-shot.
    * FastAPI binds 127.0.0.1 only (single-user, no auth).
    * Single Python file with inline Jinja templates -- no template dir.
    * `init` needs SQLAlchemy + a Postgres driver (psycopg2-binary OK).
    * `serve` only needs fastapi/uvicorn/jinja2; SQLite is stdlib.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_DB_PATH = Path("audit/audit_review.db")
DEFAULT_PORT = 8765
DEFAULT_REVIEWER = os.environ.get("USER", "anonymous")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS audit_sample (
    paper_id            TEXT PRIMARY KEY,
    arxiv_id            TEXT NOT NULL,
    arxiv_abs_url       TEXT NOT NULL,
    title               TEXT,
    n_authors           INTEGER,
    sampled_at          TEXT,
    sample_seed         REAL,
    llm_geo_cities      TEXT,   -- JSON array
    llm_geo_countries   TEXT,   -- JSON array
    llm_geo_confidence  TEXT,
    llm_geo_source      TEXT,
    llm_affiliations    TEXT,   -- JSON array of objects
    llm_materials       TEXT,   -- JSON array of v2 records
    audit_status        TEXT DEFAULT 'pending'  -- pending | done
);

CREATE TABLE IF NOT EXISTS audit_response (
    paper_id            TEXT PRIMARY KEY REFERENCES audit_sample(paper_id),
    reviewer            TEXT,
    geography_status    TEXT,   -- correct | incorrect | partial
    geography_human     TEXT,
    geography_notes     TEXT,
    formula_status      TEXT,
    formula_human       TEXT,
    formula_notes       TEXT,
    family_status       TEXT,
    family_human        TEXT,
    family_notes        TEXT,
    tc_status           TEXT,
    tc_human            TEXT,
    tc_notes            TEXT,
    evidence_status     TEXT,   -- correctly_exp | correctly_theo |
                                -- should_be_exp | should_be_theo | mixed
    evidence_human      TEXT,
    evidence_notes      TEXT,
    overall_notes       TEXT,
    reviewed_at         TEXT
);

CREATE INDEX IF NOT EXISTS idx_sample_status ON audit_sample(audit_status);
"""


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def open_sqlite(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    conn.commit()


# ---------------------------------------------------------------------------
# Stats computation (shared by stats CLI + /stats page + index summary)
# ---------------------------------------------------------------------------

_FIELDS = ("geography", "formula", "family", "tc", "evidence")

# Mirrors api/routers/timeline.py::_is_theoretical and
# ingestion/extract/materials_aggregator.py::_record_is_theoretical so the
# reviewer sees the SAME effective classification the timeline endpoint
# would apply. The NER's bare `primary` evidence_type is ambiguous and
# falls back to measurement / paper_type signals.
_EXPERIMENTAL_MEASUREMENTS = frozenset({
    "resistivity", "susceptibility", "specific_heat",
    "arpes", "musr", "stm", "neutron", "nmr", "nqr",
    "magnetization", "thermal_conductivity",
    "raman scattering", "raman", "andreev reflection",
    "nernst", "tunneling", "esr", "torque magnetometry",
    "hall effect", "hall_effect", "transport",
})
_THEORETICAL_MEASUREMENTS = frozenset({
    "calculation", "dft", "first-principles", "first principles",
    "computational", "ab initio", "ab-initio",
    "allen-dynes", "eliashberg", "tight-binding",
})


def effective_classification(record: dict[str, Any]) -> str:
    """Return 'experimental' | 'theoretical' | 'cited' for a record.

    Mirrors the timeline endpoint's _is_theoretical precedence:
      1. explicit primary_theoretical -> theoretical
      2. explicit primary_experimental -> experimental
      3. explicit cited -> cited
      4. measurement is a known experimental technique -> experimental
      5. measurement is a known theoretical technique -> theoretical
      6. paper_type = theoretical|computational -> theoretical
      7. fall through -> experimental (most cond-mat.supr-con papers)
    """
    ev = (record.get("evidence_type") or "").strip().lower()
    if ev == "primary_theoretical":
        return "theoretical"
    if ev == "primary_experimental":
        return "experimental"
    if ev == "cited":
        return "cited"
    meas = (record.get("measurement") or "").strip().lower()
    if meas in _EXPERIMENTAL_MEASUREMENTS:
        return "experimental"
    if meas in _THEORETICAL_MEASUREMENTS:
        return "theoretical"
    pt = (record.get("paper_type") or "").strip().lower()
    if pt in ("theoretical", "computational"):
        return "theoretical"
    return "experimental"


def compute_summary(conn: sqlite3.Connection) -> dict[str, Any]:
    total = conn.execute("SELECT count(*) FROM audit_sample").fetchone()[0]
    done = conn.execute(
        "SELECT count(*) FROM audit_sample WHERE audit_status='done'"
    ).fetchone()[0]
    return {
        "total": total,
        "done": done,
        "pending": total - done,
        "pct_done": round(100 * done / total, 1) if total else 0.0,
    }


def compute_full_stats(conn: sqlite3.Connection) -> dict[str, Any]:
    s: dict[str, Any] = compute_summary(conn)
    s["by_field"] = {}
    for field in _FIELDS:
        rows = conn.execute(
            f"SELECT {field}_status AS st, count(*) AS n "
            f"FROM audit_response WHERE {field}_status IS NOT NULL GROUP BY st"
        ).fetchall()
        s["by_field"][field] = {r["st"]: r["n"] for r in rows}
    return s


# ---------------------------------------------------------------------------
# CLI: init -- sample N papers from Postgres into SQLite
# ---------------------------------------------------------------------------

_INIT_SQL = """
SELECT id AS paper_id,
       arxiv_id,
       title,
       jsonb_array_length(authors)              AS n_authors,
       paper_geo::text                          AS paper_geo,
       affiliations::text                       AS affiliations,
       materials_extracted::text                AS materials_extracted
FROM papers
WHERE source = 'arxiv'
  AND chunk_count > 0
  AND paper_geo IS NOT NULL
  AND paper_geo->>'status' = 'ok'
  AND jsonb_array_length(materials_extracted) > 0
ORDER BY random()
LIMIT :lim
"""


def cmd_init(args: argparse.Namespace) -> None:
    from sqlalchemy import create_engine, text

    db_url = args.database_url or os.environ.get("DATABASE_URL")
    if not db_url:
        sys.exit("ERROR: pass --database-url or set DATABASE_URL env")
    # Normalize to sync driver
    db_url = (
        db_url.replace("postgresql+asyncpg://", "postgresql://")
        .replace("postgresql+psycopg2://", "postgresql://")
        .replace("postgres://", "postgresql://")
    )

    print(f"connecting to Postgres ...")
    engine = create_engine(db_url)
    with engine.connect() as pg:
        pg.execute(text("SELECT setseed(:s)"), {"s": args.seed})
        rows = pg.execute(text(_INIT_SQL), {"lim": args.n}).all()

    if not rows:
        sys.exit("ERROR: query returned 0 rows -- check filter / data")
    print(f"sampled {len(rows)} papers (seed={args.seed})")

    db_path = Path(args.db)
    conn = open_sqlite(db_path)
    init_schema(conn)

    now = datetime.now(timezone.utc).isoformat()
    for r in rows:
        paper_id = r.paper_id
        arxiv_id = r.arxiv_id or paper_id.replace("arxiv:", "")
        arxiv_abs_url = f"https://arxiv.org/abs/{arxiv_id}"
        geo = json.loads(r.paper_geo) if r.paper_geo else {}

        conn.execute(
            """
            INSERT INTO audit_sample (
                paper_id, arxiv_id, arxiv_abs_url, title, n_authors,
                sampled_at, sample_seed,
                llm_geo_cities, llm_geo_countries,
                llm_geo_confidence, llm_geo_source,
                llm_affiliations, llm_materials, audit_status
            ) VALUES (?,?,?,?,?, ?,?, ?,?,?,?, ?,?, 'pending')
            ON CONFLICT(paper_id) DO UPDATE SET
                arxiv_id           = excluded.arxiv_id,
                arxiv_abs_url      = excluded.arxiv_abs_url,
                title              = excluded.title,
                n_authors          = excluded.n_authors,
                sampled_at         = excluded.sampled_at,
                sample_seed        = excluded.sample_seed,
                llm_geo_cities     = excluded.llm_geo_cities,
                llm_geo_countries  = excluded.llm_geo_countries,
                llm_geo_confidence = excluded.llm_geo_confidence,
                llm_geo_source     = excluded.llm_geo_source,
                llm_affiliations   = excluded.llm_affiliations,
                llm_materials      = excluded.llm_materials
            """,
            (
                paper_id, arxiv_id, arxiv_abs_url,
                (r.title or "")[:500], r.n_authors,
                now, args.seed,
                json.dumps(geo.get("cities", []), ensure_ascii=False),
                json.dumps(geo.get("countries", []), ensure_ascii=False),
                geo.get("confidence"),
                geo.get("source"),
                r.affiliations or "[]",
                r.materials_extracted or "[]",
            ),
        )
    conn.commit()
    conn.close()
    print(f"wrote {len(rows)} rows to {db_path}")
    print(f"next:  python {Path(__file__).name} serve --reviewer YOUR_NAME")


# ---------------------------------------------------------------------------
# CLI: stats / export -- offline
# ---------------------------------------------------------------------------

def cmd_stats(args: argparse.Namespace) -> None:
    conn = open_sqlite(Path(args.db))
    print(json.dumps(compute_full_stats(conn), indent=2, ensure_ascii=False))
    conn.close()


def cmd_export(args: argparse.Namespace) -> None:
    conn = open_sqlite(Path(args.db))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = conn.execute(
        """
        SELECT s.paper_id, s.arxiv_id, s.arxiv_abs_url, s.title, s.audit_status,
               s.llm_geo_cities, s.llm_geo_countries, s.llm_geo_confidence,
               r.reviewer, r.reviewed_at,
               r.geography_status, r.geography_human, r.geography_notes,
               r.formula_status,   r.formula_human,   r.formula_notes,
               r.family_status,    r.family_human,    r.family_notes,
               r.tc_status,        r.tc_human,        r.tc_notes,
               r.evidence_status,  r.evidence_human,  r.evidence_notes,
               r.overall_notes
        FROM audit_sample s
        LEFT JOIN audit_response r USING (paper_id)
        ORDER BY s.paper_id
        """
    ).fetchall()
    with out.open("w", newline="", encoding="utf-8") as f:
        if not rows:
            print("no rows to export")
            return
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        for r in rows:
            w.writerow(dict(r))
    conn.close()
    print(f"exported {len(rows)} rows -> {out}")


# ---------------------------------------------------------------------------
# CLI: serve -- FastAPI app
# ---------------------------------------------------------------------------

def cmd_serve(args: argparse.Namespace) -> None:
    from fastapi import FastAPI, Request, HTTPException
    from fastapi.responses import HTMLResponse, JSONResponse, Response
    from jinja2 import DictLoader, Environment, select_autoescape
    import uvicorn

    db_path = Path(args.db)
    if not db_path.exists():
        sys.exit(f"ERROR: {db_path} not found. Run `init` first.")

    jenv = Environment(
        loader=DictLoader({
            "index.html":  INDEX_TEMPLATE,
            "review.html": REVIEW_TEMPLATE,
            "stats.html":  STATS_TEMPLATE,
        }),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    jenv.globals["reviewer"] = args.reviewer

    app = FastAPI(title="SCLib Audit Review", docs_url=None, redoc_url=None)

    def _conn() -> sqlite3.Connection:
        c = sqlite3.connect(str(db_path), check_same_thread=False)
        c.row_factory = sqlite3.Row
        return c

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        c = _conn()
        rows = c.execute(
            """
            SELECT s.paper_id, s.arxiv_id, s.arxiv_abs_url, s.title,
                   s.n_authors, s.audit_status, r.reviewed_at
            FROM audit_sample s LEFT JOIN audit_response r USING (paper_id)
            ORDER BY s.paper_id
            """
        ).fetchall()
        summary = compute_summary(c)
        c.close()
        return jenv.get_template("index.html").render(
            rows=[dict(r) for r in rows], summary=summary,
        )

    @app.get("/review/{paper_id:path}", response_class=HTMLResponse)
    def review(paper_id: str) -> str:
        c = _conn()
        sample = c.execute(
            "SELECT * FROM audit_sample WHERE paper_id = ?", (paper_id,)
        ).fetchone()
        if not sample:
            c.close()
            raise HTTPException(404, f"paper not found: {paper_id}")
        response = c.execute(
            "SELECT * FROM audit_response WHERE paper_id = ?", (paper_id,)
        ).fetchone()
        all_ids = [
            r["paper_id"] for r in c.execute(
                "SELECT paper_id FROM audit_sample ORDER BY paper_id"
            ).fetchall()
        ]
        c.close()

        try:
            pos = all_ids.index(paper_id)
        except ValueError:
            pos = 0
        next_id = all_ids[pos + 1] if pos + 1 < len(all_ids) else None
        prev_id = all_ids[pos - 1] if pos > 0 else None

        # Parse the JSON-stringified LLM snapshot fields for display
        sample_d = dict(sample)
        try:
            sample_d["_cities"]       = json.loads(sample_d["llm_geo_cities"] or "[]")
            sample_d["_countries"]    = json.loads(sample_d["llm_geo_countries"] or "[]")
            sample_d["_affiliations"] = json.loads(sample_d["llm_affiliations"] or "[]")
            sample_d["_materials"]    = json.loads(sample_d["llm_materials"] or "[]")
        except json.JSONDecodeError:
            sample_d["_cities"] = sample_d["_countries"] = []
            sample_d["_affiliations"] = sample_d["_materials"] = []

        # Deduplicate displays so multiple records of the same compound do
        # not show as visually identical entries in the formula / family /
        # evidence sections. Per-record Tc detail stays in the Tc section,
        # where the per-record info (different tc_kelvin, pressure, ...)
        # is the relevant granularity.
        mats = sample_d["_materials"]
        seen_f: set[str] = set()
        unique_formulas: list[str] = []
        formula_counts: dict[str, int] = {}
        for m in mats:
            f = (m.get("formula") or "").strip()
            if not f:
                continue
            if f not in seen_f:
                seen_f.add(f)
                unique_formulas.append(f)
            formula_counts[f] = formula_counts.get(f, 0) + 1
        sample_d["_unique_formulas"] = unique_formulas
        sample_d["_formula_counts"] = formula_counts

        seen_ff: set[tuple[str, str]] = set()
        unique_family_pairs: list[tuple[str, str]] = []
        for m in mats:
            pair = ((m.get("formula") or "").strip(), (m.get("family") or "").strip())
            if pair[0] and pair not in seen_ff:
                seen_ff.add(pair)
                unique_family_pairs.append(pair)
        sample_d["_unique_family_pairs"] = unique_family_pairs

        # Evidence rows: per distinct (formula, evidence_type, measurement,
        # paper_type) tuple. Includes the effective classification the
        # timeline endpoint would apply -- the NER's bare `primary` value
        # is ambiguous and needs supporting signals to be actionable.
        seen_ev_key: set[tuple[str, str, str, str]] = set()
        evidence_rows: list[dict[str, str]] = []
        for m in mats:
            f = (m.get("formula") or "").strip()
            if not f:
                continue
            ev   = (m.get("evidence_type") or "").strip()
            meas = (m.get("measurement")   or "").strip()
            pt   = (m.get("paper_type")    or "").strip()
            key = (f, ev, meas, pt)
            if key in seen_ev_key:
                continue
            seen_ev_key.add(key)
            evidence_rows.append({
                "formula":       f,
                "evidence_type": ev   or "(none)",
                "measurement":   meas or "(none)",
                "paper_type":    pt   or "(none)",
                "effective":     effective_classification(m),
            })
        sample_d["_evidence_rows"] = evidence_rows

        response_d = dict(response) if response else {}
        # Pretty-print existing human-corrected values back as text in form
        for k in (
            "geography_human", "formula_human", "family_human",
            "tc_human", "evidence_human",
        ):
            v = response_d.get(k)
            if v:
                try:
                    response_d[k] = json.dumps(json.loads(v), indent=2, ensure_ascii=False)
                except (json.JSONDecodeError, TypeError):
                    pass

        return jenv.get_template("review.html").render(
            sample=sample_d, response=response_d,
            pos=pos + 1, total=len(all_ids),
            next_id=next_id, prev_id=prev_id,
        )

    @app.post("/api/save/{paper_id:path}")
    async def save(paper_id: str, request: Request) -> JSONResponse:
        payload = await request.json()
        c = _conn()
        exists = c.execute(
            "SELECT 1 FROM audit_sample WHERE paper_id = ?", (paper_id,)
        ).fetchone()
        if not exists:
            c.close()
            raise HTTPException(404, f"paper not found: {paper_id}")

        def _j(key: str) -> str | None:
            v = payload.get(key)
            if v is None or v == "":
                return None
            if isinstance(v, str):
                # Pass through; client sends JSON-or-plain strings
                return v
            return json.dumps(v, ensure_ascii=False)

        now = datetime.now(timezone.utc).isoformat()
        c.execute(
            """
            INSERT INTO audit_response (
                paper_id, reviewer,
                geography_status, geography_human, geography_notes,
                formula_status,   formula_human,   formula_notes,
                family_status,    family_human,    family_notes,
                tc_status,        tc_human,        tc_notes,
                evidence_status,  evidence_human,  evidence_notes,
                overall_notes, reviewed_at
            ) VALUES (?, ?, ?,?,?, ?,?,?, ?,?,?, ?,?,?, ?,?,?, ?,?)
            ON CONFLICT(paper_id) DO UPDATE SET
                reviewer         = excluded.reviewer,
                geography_status = excluded.geography_status,
                geography_human  = excluded.geography_human,
                geography_notes  = excluded.geography_notes,
                formula_status   = excluded.formula_status,
                formula_human    = excluded.formula_human,
                formula_notes    = excluded.formula_notes,
                family_status    = excluded.family_status,
                family_human     = excluded.family_human,
                family_notes     = excluded.family_notes,
                tc_status        = excluded.tc_status,
                tc_human         = excluded.tc_human,
                tc_notes         = excluded.tc_notes,
                evidence_status  = excluded.evidence_status,
                evidence_human   = excluded.evidence_human,
                evidence_notes   = excluded.evidence_notes,
                overall_notes    = excluded.overall_notes,
                reviewed_at      = excluded.reviewed_at
            """,
            (
                paper_id, args.reviewer,
                payload.get("geography_status"), _j("geography_human"), payload.get("geography_notes"),
                payload.get("formula_status"),   _j("formula_human"),   payload.get("formula_notes"),
                payload.get("family_status"),    _j("family_human"),    payload.get("family_notes"),
                payload.get("tc_status"),        _j("tc_human"),        payload.get("tc_notes"),
                payload.get("evidence_status"),  _j("evidence_human"),  payload.get("evidence_notes"),
                payload.get("overall_notes"),    now,
            ),
        )
        c.execute(
            "UPDATE audit_sample SET audit_status = 'done' WHERE paper_id = ?",
            (paper_id,),
        )
        c.commit()
        c.close()
        return JSONResponse({"ok": True, "paper_id": paper_id, "saved_at": now})

    @app.get("/api/stats")
    def api_stats() -> dict[str, Any]:
        c = _conn()
        s = compute_full_stats(c)
        c.close()
        return s

    @app.get("/stats", response_class=HTMLResponse)
    def stats_page() -> str:
        c = _conn()
        s = compute_full_stats(c)
        c.close()
        return jenv.get_template("stats.html").render(stats=s, fields=_FIELDS)

    @app.get("/export.csv")
    def export_csv() -> Response:
        c = _conn()
        rows = c.execute(
            """
            SELECT s.paper_id, s.arxiv_id, s.arxiv_abs_url, s.title, s.audit_status,
                   s.llm_geo_cities, s.llm_geo_countries, s.llm_geo_confidence,
                   r.reviewer, r.reviewed_at,
                   r.geography_status, r.geography_human, r.geography_notes,
                   r.formula_status,   r.formula_human,   r.formula_notes,
                   r.family_status,    r.family_human,    r.family_notes,
                   r.tc_status,        r.tc_human,        r.tc_notes,
                   r.evidence_status,  r.evidence_human,  r.evidence_notes,
                   r.overall_notes
            FROM audit_sample s LEFT JOIN audit_response r USING (paper_id)
            ORDER BY s.paper_id
            """
        ).fetchall()
        c.close()
        buf = io.StringIO()
        if rows:
            w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
            w.writeheader()
            for r in rows:
                w.writerow(dict(r))
        return Response(
            buf.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="audit_results.csv"'},
        )

    print(f"reviewer: {args.reviewer}")
    print(f"serving:  http://127.0.0.1:{args.port}")
    print(f"db:       {db_path}")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


# ---------------------------------------------------------------------------
# Templates -- inline Jinja2
# ---------------------------------------------------------------------------

_BASE_CSS = r"""
<style>
  :root { color-scheme: light; }
  body { font-family: -apple-system, system-ui, sans-serif; margin: 0; padding: 0;
         background: #f7faf7; color: #1a2b1a; line-height: 1.45; }
  header { background: #2d5a3d; color: white; padding: 14px 24px;
           display: flex; align-items: center; justify-content: space-between;
           position: sticky; top: 0; z-index: 10; box-shadow: 0 1px 4px rgba(0,0,0,.1); }
  header h1 { margin: 0; font-size: 18px; font-weight: 600; }
  header a { color: #c8e6c9; text-decoration: none; margin-left: 16px; }
  header a:hover { color: white; }
  main { max-width: 1100px; margin: 0 auto; padding: 20px 24px 80px; }
  table { width: 100%; border-collapse: collapse; background: white;
          box-shadow: 0 1px 3px rgba(0,0,0,.08); border-radius: 6px; overflow: hidden; }
  th, td { padding: 8px 12px; text-align: left; border-bottom: 1px solid #e8eee8; }
  th { background: #eef4ee; font-weight: 600; font-size: 13px; color: #2d5a3d; }
  tr:hover { background: #f5f9f5; }
  .btn { display: inline-block; padding: 6px 14px; border-radius: 4px;
         text-decoration: none; font-size: 13px; cursor: pointer; border: none; }
  .btn-primary { background: #2d5a3d; color: white; }
  .btn-primary:hover { background: #1f3f2a; }
  .btn-secondary { background: #e8eee8; color: #2d5a3d; border: 1px solid #cbd6cb; }
  .btn-secondary:hover { background: #d4e1d4; }
  .status-done { color: #2d5a3d; font-weight: 600; }
  .status-pending { color: #8a8a8a; }
  fieldset { border: 1px solid #d4e1d4; border-radius: 6px; padding: 14px 18px;
             margin-bottom: 16px; background: white; }
  fieldset legend { font-weight: 600; padding: 0 8px; color: #2d5a3d; }
  .llm-show { background: #f4f8f4; border-left: 3px solid #2d5a3d; padding: 8px 12px;
              margin: 6px 0 10px; font-family: ui-monospace, Menlo, monospace;
              font-size: 12px; max-height: 220px; overflow: auto; white-space: pre-wrap;
              word-break: break-word; }
  label { font-size: 13px; color: #3a4a3a; }
  input[type=text], textarea { width: 100%; padding: 6px 8px; font-size: 13px;
                                border: 1px solid #cbd6cb; border-radius: 4px;
                                box-sizing: border-box;
                                font-family: ui-monospace, Menlo, monospace; }
  textarea { min-height: 60px; resize: vertical; }
  .row { display: flex; gap: 18px; flex-wrap: wrap; }
  .row > label { white-space: nowrap; }
  .field-group { margin-top: 8px; }
  .save-bar { position: sticky; bottom: 0; background: #f7faf7;
              padding: 12px 0; border-top: 1px solid #cbd6cb; margin-top: 20px;
              display: flex; gap: 10px; justify-content: flex-end; }
  .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
                gap: 16px; }
  .stat-card { background: white; padding: 14px 18px; border-radius: 6px;
               box-shadow: 0 1px 3px rgba(0,0,0,.08); }
  .stat-card h3 { margin: 0 0 8px 0; color: #2d5a3d; font-size: 14px; }
  .ttip { color: #777; font-size: 11px; margin-top: 4px; }
  .breadcrumb { font-size: 13px; color: #555; margin-bottom: 12px; }
  .truncate { max-width: 480px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
"""

INDEX_TEMPLATE = (
    r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Audit Review</title>"""
    + _BASE_CSS
    + r"""</head><body>
<header>
  <h1>SCLib Audit Review</h1>
  <nav>
    <span>Reviewer: <b>{{ reviewer }}</b></span>
    <span>&nbsp;&middot;&nbsp; <b>{{ summary.done }}</b> / {{ summary.total }} done ({{ summary.pct_done }}%)</span>
    <a href="/stats">Stats</a>
    <a href="/export.csv">Export CSV</a>
  </nav>
</header>
<main>
  <table>
    <thead><tr>
      <th>#</th><th>paper_id</th><th>title</th><th>n_auth</th><th>status</th><th>last reviewed</th><th>action</th>
    </tr></thead>
    <tbody>
    {% for r in rows %}
      <tr>
        <td>{{ loop.index }}</td>
        <td><code>{{ r.paper_id }}</code></td>
        <td class="truncate" title="{{ r.title }}">{{ r.title or '' }}</td>
        <td>{{ r.n_authors or '' }}</td>
        <td>
          {% if r.audit_status == 'done' %}
            <span class="status-done">&#10003; done</span>
          {% else %}
            <span class="status-pending">&#9711; pending</span>
          {% endif %}
        </td>
        <td>{{ (r.reviewed_at or '')[:19] }}</td>
        <td><a class="btn btn-primary" href="/review/{{ r.paper_id }}">Review &rarr;</a></td>
      </tr>
    {% endfor %}
    </tbody>
  </table>
</main>
</body></html>
"""
)

REVIEW_TEMPLATE = (
    r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Review {{ sample.paper_id }}</title>"""
    + _BASE_CSS
    + r"""</head><body>
<header>
  <h1>Review &middot; {{ pos }} / {{ total }}</h1>
  <nav>
    <a href="/">&larr; Back to list</a>
    {% if prev_id %}<a href="/review/{{ prev_id }}">&larr; Prev</a>{% endif %}
    {% if next_id %}<a href="/review/{{ next_id }}">Next &rarr;</a>{% endif %}
  </nav>
</header>
<main>
  <div class="breadcrumb">
    <code>{{ sample.paper_id }}</code> &middot; {{ sample.n_authors or '?' }} authors
    &middot; geo source: <b>{{ sample.llm_geo_source or '-' }}</b>
    &middot; geo confidence: <b>{{ sample.llm_geo_confidence or '-' }}</b>
  </div>
  <h2 style="margin-top:0;font-size:17px">{{ sample.title or '(no title)' }}</h2>
  <p>
    <a class="btn btn-secondary" href="{{ sample.arxiv_abs_url }}" target="_blank" rel="noopener">Open arXiv abs &#8599;</a>
    <a class="btn btn-secondary" href="{{ sample.arxiv_abs_url.replace('/abs/', '/pdf/') }}" target="_blank" rel="noopener">Open PDF &#8599;</a>
  </p>

  <form id="auditForm" onsubmit="return saveAudit(event)">

    <fieldset>
      <legend>1. Author Geography</legend>
      <div>LLM extracted:</div>
      <pre class="llm-show">cities    = {{ sample._cities | tojson(indent=2) }}
countries = {{ sample._countries | tojson(indent=2) }}

raw affiliations:
{{ sample._affiliations | tojson(indent=2) }}</pre>
      <div class="row">
        <label><input type="radio" name="geography_status" value="correct"
          {% if response.geography_status == 'correct' %}checked{% endif %}> Correct</label>
        <label><input type="radio" name="geography_status" value="incorrect"
          {% if response.geography_status == 'incorrect' %}checked{% endif %}> Incorrect</label>
        <label><input type="radio" name="geography_status" value="partial"
          {% if response.geography_status == 'partial' %}checked{% endif %}> Partial</label>
      </div>
      <div class="field-group">
        <label>Corrected value (JSON: {"cities":[...], "countries":[...]}):</label>
        <textarea name="geography_human" placeholder='{"cities": ["Tokyo"], "countries": ["Japan"]}'>{{ response.geography_human or '' }}</textarea>
      </div>
      <div class="field-group">
        <label>Notes:</label>
        <textarea name="geography_notes">{{ response.geography_notes or '' }}</textarea>
      </div>
    </fieldset>

    <fieldset>
      <legend>2. Chemical Formula(s)</legend>
      <div>LLM extracted formulas ({{ sample._materials | length }} record{{ '' if sample._materials | length == 1 else 's' }}, {{ sample._unique_formulas | length }} distinct compound{{ '' if sample._unique_formulas | length == 1 else 's' }}):</div>
      <pre class="llm-show">{% for f in sample._unique_formulas %}{{ loop.index }}. {{ f }}{% if sample._formula_counts[f] > 1 %}  (×{{ sample._formula_counts[f] }} records — see Tc section){% endif %}
{% endfor %}</pre>
      <div class="row">
        <label><input type="radio" name="formula_status" value="correct"
          {% if response.formula_status == 'correct' %}checked{% endif %}> Correct</label>
        <label><input type="radio" name="formula_status" value="incorrect"
          {% if response.formula_status == 'incorrect' %}checked{% endif %}> Incorrect</label>
        <label><input type="radio" name="formula_status" value="partial"
          {% if response.formula_status == 'partial' %}checked{% endif %}> Partial</label>
      </div>
      <div class="field-group">
        <label>Corrected list (JSON array of strings):</label>
        <textarea name="formula_human" placeholder='["YBa2Cu3O7", "Bi2Sr2CaCu2O8"]'>{{ response.formula_human or '' }}</textarea>
      </div>
      <div class="field-group">
        <label>Notes:</label>
        <textarea name="formula_notes">{{ response.formula_notes or '' }}</textarea>
      </div>
    </fieldset>

    <fieldset>
      <legend>3. Material Family</legend>
      <div>LLM extracted family per distinct compound:</div>
      <pre class="llm-show">{% for f, fam in sample._unique_family_pairs %}{{ f }} -> {{ fam or '(none)' }}
{% endfor %}</pre>
      <div class="row">
        <label><input type="radio" name="family_status" value="correct"
          {% if response.family_status == 'correct' %}checked{% endif %}> Correct</label>
        <label><input type="radio" name="family_status" value="incorrect"
          {% if response.family_status == 'incorrect' %}checked{% endif %}> Incorrect</label>
        <label><input type="radio" name="family_status" value="partial"
          {% if response.family_status == 'partial' %}checked{% endif %}> Partial</label>
      </div>
      <div class="field-group">
        <label>Corrected family per formula (JSON: {"formula":"family"}):</label>
        <textarea name="family_human" placeholder='{"YBa2Cu3O7": "cuprate"}'>{{ response.family_human or '' }}</textarea>
      </div>
      <div class="field-group">
        <label>Notes:</label>
        <textarea name="family_notes">{{ response.family_notes or '' }}</textarea>
      </div>
    </fieldset>

    <fieldset>
      <legend>4. T<sub>c</sub> Records (CRITICAL)</legend>
      <div>LLM extracted T<sub>c</sub> records:</div>
      <pre class="llm-show">{% for m in sample._materials %}[{{ loop.index }}] formula={{ m.formula }}
    tc_kelvin     = {{ m.tc_kelvin }}
    pressure_gpa  = {{ m.pressure_gpa }}
    tc_regime     = {{ m.tc_regime }}
    measurement   = {{ m.measurement }}
    evidence_type = {{ m.evidence_type }}
    confidence    = {{ m.confidence }}
{% endfor %}</pre>
      <div class="row">
        <label><input type="radio" name="tc_status" value="correct"
          {% if response.tc_status == 'correct' %}checked{% endif %}> Correct</label>
        <label><input type="radio" name="tc_status" value="incorrect"
          {% if response.tc_status == 'incorrect' %}checked{% endif %}> Incorrect</label>
        <label><input type="radio" name="tc_status" value="partial"
          {% if response.tc_status == 'partial' %}checked{% endif %}> Partial</label>
      </div>
      <div class="field-group">
        <label>Corrected records (JSON array; include only what the paper actually reports):</label>
        <textarea name="tc_human" rows="6" placeholder='[{"formula":"YBa2Cu3O7","tc_kelvin":93.0,"pressure_gpa":0.0,"evidence_type":"primary_experimental","measurement":"resistivity"}]'>{{ response.tc_human or '' }}</textarea>
      </div>
      <div class="field-group">
        <label>Notes (extra / missing records, conditions, etc.):</label>
        <textarea name="tc_notes">{{ response.tc_notes or '' }}</textarea>
      </div>
    </fieldset>

    <fieldset>
      <legend>5. Theoretical vs Experimental</legend>
      <div>LLM evidence signals per distinct compound &middot;
        <span style="color:#777;font-size:12px">
          NER raw <code>evidence_type</code> + supporting signals + <b>effective classification</b> the timeline endpoint would apply
        </span>
      </div>
      <pre class="llm-show">{% for r in sample._evidence_rows %}{{ r.formula }}
  evidence_type = {{ r.evidence_type }}
  measurement   = {{ r.measurement }}
  paper_type    = {{ r.paper_type }}
  &#8594; effective: {{ r.effective | upper }}{% if r.evidence_type == 'primary' %}   (NER raw 'primary' is AMBIGUOUS -- derived from measurement/paper_type){% endif %}
{% endfor %}</pre>
      <div class="row">
        <label><input type="radio" name="evidence_status" value="correctly_exp"
          {% if response.evidence_status == 'correctly_exp' %}checked{% endif %}> Correctly experimental</label>
        <label><input type="radio" name="evidence_status" value="correctly_theo"
          {% if response.evidence_status == 'correctly_theo' %}checked{% endif %}> Correctly theoretical</label>
        <label><input type="radio" name="evidence_status" value="should_be_exp"
          {% if response.evidence_status == 'should_be_exp' %}checked{% endif %}> Should be experimental (mis-tagged)</label>
        <label><input type="radio" name="evidence_status" value="should_be_theo"
          {% if response.evidence_status == 'should_be_theo' %}checked{% endif %}> Should be theoretical (mis-tagged)</label>
        <label><input type="radio" name="evidence_status" value="mixed"
          {% if response.evidence_status == 'mixed' %}checked{% endif %}> Mixed per-record</label>
      </div>
      <div class="field-group">
        <label>Per-record corrected classification (JSON {"formula": "experimental|theoretical|cited"}):</label>
        <textarea name="evidence_human" placeholder='{"YBa2Cu3O7": "experimental"}'>{{ response.evidence_human or '' }}</textarea>
      </div>
      <div class="field-group">
        <label>Notes:</label>
        <textarea name="evidence_notes">{{ response.evidence_notes or '' }}</textarea>
      </div>
    </fieldset>

    <fieldset>
      <legend>Overall</legend>
      <div class="field-group">
        <label>Overall notes:</label>
        <textarea name="overall_notes">{{ response.overall_notes or '' }}</textarea>
      </div>
    </fieldset>

    <div class="save-bar">
      <span id="saveStatus" style="margin-right:auto; color:#555; font-size:13px"></span>
      <button class="btn btn-secondary" type="button" onclick="window.location='/'">&larr; Back</button>
      <button class="btn btn-primary" type="submit" name="action" value="save">&#128190; Save</button>
      {% if next_id %}
      <button class="btn btn-primary" type="submit" name="action" value="save_next">&#128190; Save &amp; Next &rarr;</button>
      {% endif %}
    </div>
  </form>

<script>
const PAPER_ID = """ + r"""{{ sample.paper_id | tojson }};""" + r"""
const NEXT_ID  = """ + r"""{{ next_id | tojson if next_id else "null" }};""" + r"""

async function saveAudit(ev) {
  ev.preventDefault();
  const form = document.getElementById('auditForm');
  const fd = new FormData(form);
  const payload = {};
  for (const [k, v] of fd.entries()) {
    if (k === 'action') continue;
    payload[k] = v;
  }
  const status = document.getElementById('saveStatus');
  status.textContent = 'Saving...';
  status.style.color = '#555';
  try {
    const r = await fetch('/api/save/' + encodeURIComponent(PAPER_ID).replace(/%2F/g, '/'), {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    });
    if (!r.ok) { throw new Error('HTTP ' + r.status); }
    const data = await r.json();
    status.textContent = '&#10003; saved ' + data.saved_at.slice(11,19);
    status.innerHTML = status.textContent;
    status.style.color = '#2d5a3d';
    const action = ev.submitter ? ev.submitter.value : 'save';
    if (action === 'save_next' && NEXT_ID) {
      window.location = '/review/' + NEXT_ID;
    }
  } catch (e) {
    status.textContent = 'Save failed: ' + e.message;
    status.style.color = '#c0392b';
  }
  return false;
}
</script>
</main>
</body></html>
"""
)

STATS_TEMPLATE = (
    r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Audit Stats</title>"""
    + _BASE_CSS
    + r"""</head><body>
<header>
  <h1>Audit Stats</h1>
  <nav><a href="/">&larr; Back</a> <a href="/export.csv">Export CSV</a></nav>
</header>
<main>
  <div class="stats-grid">
    <div class="stat-card">
      <h3>Coverage</h3>
      <div style="font-size:28px;font-weight:600;color:#2d5a3d">{{ stats.done }} / {{ stats.total }}</div>
      <div class="ttip">{{ stats.pct_done }}% complete &middot; {{ stats.pending }} pending</div>
    </div>
    {% for f in fields %}
    <div class="stat-card">
      <h3>{{ f|capitalize }}</h3>
      {% set d = stats.by_field[f] %}
      {% set tot = d.values() | sum %}
      {% if tot > 0 %}
      <table style="font-size:13px;box-shadow:none">
        {% for k, v in d.items() %}
          <tr>
            <td style="border:none;padding:2px 6px">{{ k }}</td>
            <td style="border:none;padding:2px 6px;text-align:right">{{ v }}</td>
            <td style="border:none;padding:2px 6px;text-align:right;color:#777">
              ({{ (100*v/tot) | round(0, 'floor') | int }}%)
            </td>
          </tr>
        {% endfor %}
      </table>
      {% else %}
      <div class="ttip">no responses yet</div>
      {% endif %}
    </div>
    {% endfor %}
  </div>
</main>
</body></html>
"""
)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="Sample N papers from Postgres into SQLite")
    p_init.add_argument("--db", default=str(DEFAULT_DB_PATH))
    p_init.add_argument("--n", type=int, default=100)
    p_init.add_argument("--seed", type=float, default=0.42)
    p_init.add_argument("--database-url",
                        help="Postgres URL (default: DATABASE_URL env)")
    p_init.set_defaults(func=cmd_init)

    p_serve = sub.add_parser("serve", help="Run the review UI on localhost")
    p_serve.add_argument("--db", default=str(DEFAULT_DB_PATH))
    p_serve.add_argument("--port", type=int, default=DEFAULT_PORT)
    p_serve.add_argument("--reviewer", default=DEFAULT_REVIEWER)
    p_serve.set_defaults(func=cmd_serve)

    p_stats = sub.add_parser("stats", help="Print stats JSON")
    p_stats.add_argument("--db", default=str(DEFAULT_DB_PATH))
    p_stats.set_defaults(func=cmd_stats)

    p_exp = sub.add_parser("export", help="Export results to CSV")
    p_exp.add_argument("--db", default=str(DEFAULT_DB_PATH))
    p_exp.add_argument("--out", default="audit/exports/audit_results.csv")
    p_exp.set_defaults(func=cmd_export)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
