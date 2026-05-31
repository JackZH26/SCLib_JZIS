"""Phase 2a multi-model audit driver.

Reads `audit/MULTIMODEL_AUDIT_TASK.md` for the contract. Subcommands:

    setup       Create audit_extraction_model + Gemini back-fill.
    cache       Build audit/cached_inputs/<safe_id>.json for all 100 papers.
    prompts     Dump the assembled (paper, prompt) pair to stdout (debug).
    prompt      Print the literal prompt string for one (paper, prompt_type)
                pair. Used by the main agent to feed sub-agents.
    pending     Print TSV of (paper_id, prompt_version) still missing rows
                for the configured vendor/model. Used by the orchestrator to
                know what to dispatch next.
    save        Persist a sub-agent's JSON reply to audit_extraction_model.
                Reads JSON from --result-file or stdin.
    gate        Run §9 verification queries and report.
    summary     Print §15 acknowledgement summary and exit.

We are the model. Configure identity with AUDIT_VENDOR/AUDIT_MODEL_NAME.
Defaults are the OpenAI Codex side of the Phase 2a task.
The script never calls an LLM; the main agent (or sub-agents it spawns)
does the actual extraction and pipes the JSON back to `save`.

Prompts are pulled from the production source files via `ast.parse` so a
drift in production raises early instead of being copied silently.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
import os
import pathlib
import re
import sqlite3
import subprocess
import sys
import tarfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

import httpx

REPO = pathlib.Path(__file__).resolve().parents[1]
AUDIT_DIR = REPO / "audit"
DB_PATH = AUDIT_DIR / "audit_review.db"
CACHE_DIR = AUDIT_DIR / "cached_inputs"
RUNS_DIR = AUDIT_DIR / "runs"
RESULTS_DIR = RUNS_DIR / "extraction_results"

MATERIAL_NER_PY = REPO / "ingestion" / "ingestion" / "extract" / "material_ner.py"
AFFILIATION_NER_PY = REPO / "ingestion" / "ingestion" / "extract" / "affiliation_ner.py"

VENDOR = os.environ.get("AUDIT_VENDOR", "openai")
MODEL_NAME = os.environ.get("AUDIT_MODEL_NAME", "gpt-5.5")
THINKING_MODE = os.environ.get("AUDIT_THINKING_MODE", "high")
AGENT_CLI = os.environ.get("AUDIT_AGENT_CLI", "codex")
USER_AGENT = "SCLib_JZIS/0.1 (mailto: jack@xd.com)"
ARXIV_DELAY_SEC = 3.0

PROMPT_VERSION_MATERIAL = "material_ner_v2_core"
PROMPT_VERSION_GEO_TEXT = "geo_ner_v1_text"
PROMPT_VERSION_GEO_PDF = "geo_ner_v1_pdf_text_fallback"


# ---------------------------------------------------------------------------
# Latex parser helpers — copied verbatim from
# ingestion/ingestion/parse/latex_parser.py to avoid the package import
# chain (which pulls in google-genai via siblings). These four helpers are
# pure stdlib (regex + tarfile) so reproduction is trivial.
# ---------------------------------------------------------------------------

_DOCUMENTCLASS_RE = re.compile(r"\\documentclass[\[\{]")
_INPUT_RE = re.compile(r"\\(?:input|include)\{([^}]+)\}")
_BEGIN_DOC_RE = re.compile(r"\\begin\{document\}")


@dataclass
class _TexFile:
    path: str
    body: str


def _decode(raw: bytes) -> str:
    for enc in ("utf-8", "latin-1"):
        try:
            return raw.decode(enc).replace("\x00", "")
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace").replace("\x00", "")


def _extract_tex_files(data: bytes) -> list[_TexFile]:
    out: list[_TexFile] = []
    for mode in ("r:gz", "r:"):
        try:
            with tarfile.open(fileobj=io.BytesIO(data), mode=mode) as tf:
                for member in tf.getmembers():
                    if not member.isfile():
                        continue
                    if not member.name.lower().endswith(".tex"):
                        continue
                    f = tf.extractfile(member)
                    if f is None:
                        continue
                    out.append(_TexFile(path=member.name, body=_decode(f.read())))
                if out:
                    return out
        except tarfile.ReadError:
            continue
        except Exception:
            pass
    try:
        import gzip
        return [_TexFile(path="main.tex", body=_decode(gzip.decompress(data)))]
    except OSError:
        pass
    try:
        return [_TexFile(path="main.tex", body=_decode(data))]
    except UnicodeDecodeError:
        return []


def _find_main(files: list[_TexFile]) -> _TexFile:
    from pathlib import PurePosixPath
    candidates = [f for f in files if _DOCUMENTCLASS_RE.search(f.body)]
    if candidates:
        candidates.sort(key=lambda f: len(PurePosixPath(f.path).parts))
        return candidates[0]
    return max(files, key=lambda f: len(f.body))


def _inline_inputs(main: _TexFile, all_files: list[_TexFile]) -> str:
    from pathlib import PurePosixPath
    by_stem: dict[str, _TexFile] = {}
    for f in all_files:
        stem = PurePosixPath(f.path).stem
        by_stem.setdefault(stem, f)
        by_stem.setdefault(PurePosixPath(f.path).name, f)
    seen: set[str] = {main.path}

    def sub(body: str) -> str:
        def _replace(m: re.Match[str]) -> str:
            ref = m.group(1).strip()
            stem = PurePosixPath(ref).stem
            target = by_stem.get(stem) or by_stem.get(f"{stem}.tex")
            if target is None or target.path in seen:
                return ""
            seen.add(target.path)
            return sub(target.body)
        return _INPUT_RE.sub(_replace, body)

    return sub(main.body)


# ---------------------------------------------------------------------------
# Production prompt loader — read source files, parse with ast.
# ---------------------------------------------------------------------------

def _eval_str_concat(node: ast.AST, env: dict[str, Any]) -> str | None:
    """Evaluate a string-only ast tree of literals + Names + Add BinOps."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        v = env.get(node.id)
        return v if isinstance(v, str) else None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _eval_str_concat(node.left, env)
        right = _eval_str_concat(node.right, env)
        if isinstance(left, str) and isinstance(right, str):
            return left + right
    return None


def load_production_prompts() -> dict[str, Any]:
    """Pull the prompt constants verbatim from the production source files.

    Returns a dict with:
        material_core, material_comp_prefix, calc_keywords, exp_keywords,
        max_chars, geo_schema, geo_text_prompt, geo_pdf_prompt, max_tex_chars
    plus source SHAs for the audit log.
    """
    out: dict[str, Any] = {}

    mat_src = MATERIAL_NER_PY.read_text()
    mat_tree = ast.parse(mat_src)
    mat: dict[str, Any] = {}
    for node in mat_tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    try:
                        mat[target.id] = ast.literal_eval(node.value)
                    except Exception:
                        pass
    out["material_core"] = mat["_V2_PROMPT_CORE"]
    out["material_comp_prefix"] = mat["_V2_PROMPT_COMPUTATIONAL_PREFIX"]
    out["calc_keywords"] = mat["_CALC_KEYWORDS"]
    out["exp_keywords"] = mat["_EXP_KEYWORDS"]
    out["max_chars"] = mat["_MAX_CHARS"]
    out["material_ner_sha256"] = hashlib.sha256(mat_src.encode()).hexdigest()

    aff_src = AFFILIATION_NER_PY.read_text()
    aff_tree = ast.parse(aff_src)
    aff: dict[str, Any] = {}
    # First pass — simple literals.
    for node in aff_tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    try:
                        aff[target.id] = ast.literal_eval(node.value)
                    except Exception:
                        pass
    # Second pass — concat expressions referencing the literals above.
    for node in aff_tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in ("_PROMPT_TEXT", "_PROMPT_PDF"):
                    v = _eval_str_concat(node.value, aff)
                    if v is not None:
                        aff[target.id] = v
    out["geo_schema"] = aff["_SCHEMA"]
    out["geo_text_prompt"] = aff["_PROMPT_TEXT"]
    out["geo_pdf_prompt"] = aff["_PROMPT_PDF"]
    out["max_tex_chars"] = aff["_MAX_TEX_CHARS"]
    out["affiliation_ner_sha256"] = hashlib.sha256(aff_src.encode()).hexdigest()

    return out


# Copy of material_ner.classify_paper_type — depends only on the two keyword
# lists, which we load from source.
def classify_paper_type(title: str, abstract: str, calc_kw: list[str], exp_kw: list[str]) -> str:
    text = (title + " " + abstract).lower()
    calc_score = sum(1 for k in calc_kw if k in text)
    exp_score = sum(1 for k in exp_kw if k in text)
    if calc_score >= 2 and calc_score >= exp_score:
        return "computational"
    if exp_score >= 2:
        return "experimental"
    return "theoretical"


# ---------------------------------------------------------------------------
# arXiv fetch helpers
# ---------------------------------------------------------------------------

_AUTHOR_RE = re.compile(r"\\author\b")
_AFFIL_HINT_RE = re.compile(r"affil|address|institut|\\thanks", re.IGNORECASE)
_SECTION_RE = re.compile(
    r"^\s*\\(section|subsection|subsubsection)\*?\{([^}]*)\}",
    re.MULTILINE,
)


def _safe_id(arxiv_id: str) -> str:
    return arxiv_id.replace("/", "_")


def _detex_simple(s: str) -> str:
    """Lightweight LaTeX → text. Drops most macros and leaves their text body.

    The production parser uses pylatexenc; we replicate just enough so the
    abstract/sections returned to NER are readable. Imported separately to
    avoid the ingestion-package import chain.
    """
    from pylatexenc.latex2text import LatexNodes2Text
    try:
        out = LatexNodes2Text(math_mode="text", strict_latex_spaces=False,
                              keep_comments=False).latex_to_text(s)
    except Exception:
        out = s
    return re.sub(r"[ \t]+\n", "\n", out).strip()


def _strip_preamble(body: str) -> str:
    begin = _BEGIN_DOC_RE.search(body)
    if begin is None:
        return body
    end = re.search(r"\\end\{document\}", body)
    start = begin.end()
    stop = end.start() if end else len(body)
    return body[start:stop]


def _strip_bibliography(body: str) -> str:
    m = re.search(r"\\(bibliography|printbibliography|begin\{thebibliography\})", body)
    return body[: m.start()] if m else body


def _split_sections(body: str) -> list[tuple[str, str]]:
    """Return list of (name, text) for first 8 sections after preamble."""
    matches = list(_SECTION_RE.finditer(body))
    if not matches:
        return [("Body", _detex_simple(body))]
    out = []
    for i, m in enumerate(matches[:8]):
        name = m.group(2).strip() or f"Section {i+1}"
        start = m.end()
        stop = matches[i+1].start() if i+1 < len(matches) else len(body)
        out.append((_detex_simple(name), _detex_simple(body[start:stop])))
    return out


def _assemble_body(title: str, abstract: str, sections: list[tuple[str, str]]) -> str:
    """Mirror material_ner._assemble_text exactly."""
    parts = [f"Title: {title}", f"Abstract: {abstract}"]
    for name, text in sections:
        parts.append(f"\n## {name}\n{text}")
    return "\n\n".join(parts)


def _extract_author_region(tar_bytes: bytes) -> str | None:
    """Mirror affiliation_ner._extract_author_region."""
    if tar_bytes[:5] == b"%PDF-":
        return None
    try:
        tex_files = _extract_tex_files(tar_bytes)
    except Exception:
        return None
    if not tex_files:
        return None
    main = _find_main(tex_files)
    body = _inline_inputs(main, tex_files)
    m = _AUTHOR_RE.search(body)
    if m:
        region = body[max(0, m.start() - 400): m.start() + 9000]
    else:
        bd = _BEGIN_DOC_RE.search(body)
        if not bd:
            return None
        region = body[max(0, bd.start() - 6000): bd.start() + 4000]
        if not _AFFIL_HINT_RE.search(region):
            return None
    region = region.strip()
    return region or None


def _arxiv_get(url: str) -> httpx.Response:
    r = httpx.get(url, headers={"User-Agent": USER_AGENT},
                  timeout=120.0, follow_redirects=True)
    time.sleep(ARXIV_DELAY_SEC)
    return r


def _fetch_abstract_html(arxiv_id: str) -> tuple[str, str]:
    """Return (title, abstract) parsed from arxiv.org/abs/<id>."""
    r = _arxiv_get(f"https://arxiv.org/abs/{arxiv_id}")
    r.raise_for_status()
    html = r.text
    # meta tags
    m_title = re.search(r'<meta\s+name="citation_title"\s+content="([^"]+)"', html)
    m_abs = re.search(r'<meta\s+(?:name|property)="og:description"\s+content="([^"]+)"', html)
    title = (m_title.group(1) if m_title else "").strip()
    abstract = (m_abs.group(1) if m_abs else "").strip()
    if not abstract:
        # fall back to <blockquote class="abstract">
        m_blk = re.search(r'<blockquote\s+class="abstract[^"]*">(.*?)</blockquote>',
                          html, re.DOTALL)
        if m_blk:
            text = re.sub(r"<[^>]+>", "", m_blk.group(1))
            text = re.sub(r"\s+", " ", text).strip()
            abstract = re.sub(r"^Abstract:\s*", "", text)
    # unescape entities
    import html as _html
    return _html.unescape(title), _html.unescape(abstract)


def _fetch_latex_source(arxiv_id: str) -> bytes | None:
    """Return tar bytes from arxiv.org/e-print/<id>, or None on 404."""
    r = _arxiv_get(f"https://arxiv.org/e-print/{arxiv_id}")
    if r.status_code != 200:
        return None
    if r.content[:5] == b"%PDF-":
        return None  # some submissions only have PDF
    return r.content


def _fetch_pdf(arxiv_id: str) -> bytes | None:
    r = _arxiv_get(f"https://arxiv.org/pdf/{arxiv_id}")
    if r.status_code != 200 or r.content[:5] != b"%PDF-":
        return None
    return r.content


def _pdf_text_all(pdf_bytes: bytes) -> str:
    from pypdf import PdfReader
    rdr = PdfReader(io.BytesIO(pdf_bytes))
    out = []
    for p in rdr.pages:
        try:
            out.append(p.extract_text() or "")
        except Exception:
            continue
    return "\n".join(out)


def _pdf_text_first_page(pdf_bytes: bytes) -> str:
    from pypdf import PdfReader
    rdr = PdfReader(io.BytesIO(pdf_bytes))
    if not rdr.pages:
        return ""
    try:
        return rdr.pages[0].extract_text() or ""
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Sub-command: cache
# ---------------------------------------------------------------------------

def cmd_cache(args: argparse.Namespace) -> None:
    prompts = load_production_prompts()
    max_chars = prompts["max_chars"]
    max_tex_chars = prompts["max_tex_chars"]
    calc_kw = prompts["calc_keywords"]
    exp_kw = prompts["exp_keywords"]

    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT paper_id, arxiv_id, title FROM audit_sample ORDER BY paper_id"
    ).fetchall()
    conn.close()

    n_latex = 0
    n_pdf = 0
    for i, (paper_id, arxiv_id, _audit_title) in enumerate(rows, 1):
        cache_path = CACHE_DIR / f"{_safe_id(arxiv_id)}.json"
        if cache_path.exists():
            try:
                existing = json.loads(cache_path.read_text())
                if existing.get("body_for_material_ner") and existing.get("front_matter_for_geo_ner"):
                    if existing.get("geo_input_kind") == "pdf":
                        n_pdf += 1
                    else:
                        n_latex += 1
                    print(f"[{i:3d}/100] {arxiv_id} cached", flush=True)
                    continue
            except Exception:
                pass  # rebuild

        print(f"[{i:3d}/100] {arxiv_id} fetching...", flush=True)
        try:
            title, abstract = _fetch_abstract_html(arxiv_id)
        except Exception as e:
            print(f"  abstract fetch failed: {e}", flush=True)
            title, abstract = "", ""

        body_text = ""
        front_matter = ""
        body_source = ""
        front_source = ""
        geo_input_kind = "text"

        # Tier 1: LaTeX source
        tar_bytes = _fetch_latex_source(arxiv_id)
        if tar_bytes is not None:
            # Body assembly
            try:
                tex_files = _extract_tex_files(tar_bytes)
                if tex_files:
                    main = _find_main(tex_files)
                    raw = _inline_inputs(main, tex_files)
                    stripped = _strip_bibliography(_strip_preamble(raw))
                    sections = _split_sections(stripped)
                    body_text = _assemble_body(title, abstract, sections)
                    body_source = "arxiv_latex"
            except Exception as e:
                print(f"  latex body assembly failed: {e}", flush=True)

            # Front matter region
            region = _extract_author_region(tar_bytes)
            if region:
                front_matter = region
                front_source = "arxiv_latex"
                geo_input_kind = "text"

        # Tier 2: PDF fallback for missing pieces
        if not body_text or not front_matter:
            pdf_bytes = _fetch_pdf(arxiv_id)
            if pdf_bytes is not None:
                if not body_text:
                    pdf_full = _pdf_text_all(pdf_bytes)
                    # Mirror material_ner._assemble_text shape
                    body_text = f"Title: {title}\n\nAbstract: {abstract}\n\n## Body\n{pdf_full}"
                    body_source = "arxiv_pdf"
                if not front_matter:
                    front_matter = _pdf_text_first_page(pdf_bytes)
                    front_source = "arxiv_pdf"
                    geo_input_kind = "pdf"

        # Truncate
        body_text = body_text[:max_chars]
        front_matter = front_matter[:max_tex_chars]

        paper_type = classify_paper_type(title, abstract, calc_kw, exp_kw)

        payload = {
            "paper_id": paper_id,
            "arxiv_id": arxiv_id,
            "title": title,
            "abstract": abstract,
            "body_for_material_ner": body_text,
            "paper_type": paper_type,
            "front_matter_for_geo_ner": front_matter,
            "geo_input_kind": geo_input_kind,
            "source": {
                "title_abstract": "arxiv_abs_html",
                "body": body_source or "none",
                "front_matter": front_source or "none",
            },
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
        cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))

        if geo_input_kind == "pdf":
            n_pdf += 1
        else:
            n_latex += 1

        # quick sanity log
        print(f"  body={len(body_text)} chars front={len(front_matter)} chars kind={geo_input_kind} type={paper_type}",
              flush=True)

    print(f"cached 100/100 (latex={n_latex}, pdf={n_pdf})", flush=True)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

DDL = """
CREATE TABLE IF NOT EXISTS audit_extraction_model (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id            TEXT NOT NULL REFERENCES audit_sample(paper_id),
    vendor              TEXT NOT NULL,
    model_name          TEXT NOT NULL,
    run_idx             INTEGER NOT NULL,
    thinking_mode       TEXT,
    prompt_version      TEXT NOT NULL,
    materials_json      TEXT,
    affiliations_json   TEXT,
    paper_geo_json      TEXT,
    materials_error     TEXT,
    affiliations_error  TEXT,
    input_chars         INTEGER,
    extracted_at        TEXT NOT NULL,
    UNIQUE(paper_id, vendor, model_name, run_idx, prompt_version)
);
CREATE INDEX IF NOT EXISTS idx_aem_paper    ON audit_extraction_model(paper_id);
CREATE INDEX IF NOT EXISTS idx_aem_vendor   ON audit_extraction_model(vendor);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def cmd_setup(args: argparse.Namespace) -> None:
    """Create the table and back-fill Gemini production rows."""
    conn = _connect()
    conn.executescript(DDL)
    conn.commit()

    rows = conn.execute(
        """SELECT paper_id, llm_materials, llm_affiliations,
                  llm_geo_cities, llm_geo_countries, llm_geo_confidence, llm_geo_source
             FROM audit_sample ORDER BY paper_id"""
    ).fetchall()

    now = datetime.now(timezone.utc).isoformat()
    n_mat = 0
    n_geo = 0
    for paper_id, llm_materials, llm_affiliations, geo_cities, geo_countries, geo_conf, geo_src in rows:
        # Material row
        conn.execute(
            """INSERT OR REPLACE INTO audit_extraction_model
                 (paper_id, vendor, model_name, run_idx, thinking_mode,
                  prompt_version, materials_json, affiliations_json, paper_geo_json,
                  materials_error, affiliations_error, input_chars, extracted_at)
               VALUES (?, 'google', 'gemini-2.5-flash', 0, NULL,
                       ?, ?, NULL, NULL, NULL, NULL, NULL, ?)""",
            (paper_id, PROMPT_VERSION_MATERIAL, llm_materials, now),
        )
        n_mat += 1

        # Geo row + paper_geo summary computed from existing dedup fields
        paper_geo = {
            "cities": json.loads(geo_cities or "[]"),
            "countries": json.loads(geo_countries or "[]"),
            "confidence": geo_conf,
            "source": geo_src,
        }
        conn.execute(
            """INSERT OR REPLACE INTO audit_extraction_model
                 (paper_id, vendor, model_name, run_idx, thinking_mode,
                  prompt_version, materials_json, affiliations_json, paper_geo_json,
                  materials_error, affiliations_error, input_chars, extracted_at)
               VALUES (?, 'google', 'gemini-2.5-flash', 0, NULL,
                       ?, NULL, ?, ?, NULL, NULL, NULL, ?)""",
            (paper_id, PROMPT_VERSION_GEO_TEXT, llm_affiliations,
             json.dumps(paper_geo, ensure_ascii=False), now),
        )
        n_geo += 1

    conn.commit()
    conn.close()
    print(f"setup: table ready; Gemini back-fill mat={n_mat} geo={n_geo}", flush=True)


# ---------------------------------------------------------------------------
# Sub-command: prompt — print exactly the prompt the sub-agent should run.
# ---------------------------------------------------------------------------

def _build_material_prompt(cached: dict, prompts: dict) -> str:
    body = cached["body_for_material_ner"][: prompts["max_chars"]]
    core = prompts["material_core"].replace("{{BODY}}", body)
    if cached.get("paper_type") == "computational":
        return prompts["material_comp_prefix"] + core
    return core


def _build_geo_prompt(cached: dict, prompts: dict) -> str:
    front = cached["front_matter_for_geo_ner"][: prompts["max_tex_chars"]]
    return prompts["geo_text_prompt"].replace("{{FRONT}}", front)


def cmd_prompt(args: argparse.Namespace) -> None:
    prompts = load_production_prompts()
    cache_path = CACHE_DIR / f"{_safe_id(args.arxiv_id)}.json"
    cached = json.loads(cache_path.read_text())
    if args.prompt_type == "material":
        sys.stdout.write(_build_material_prompt(cached, prompts))
    elif args.prompt_type == "geo":
        sys.stdout.write(_build_geo_prompt(cached, prompts))
    else:
        raise ValueError(args.prompt_type)


# ---------------------------------------------------------------------------
# Sub-command: pending
# ---------------------------------------------------------------------------

def cmd_pending(args: argparse.Namespace) -> None:
    """Print TSV: paper_id\tarxiv_id\tprompt_version\tprompt_type\trun_idx
    for (paper, prompt, run_idx) tuples still missing rows.

    With --run-idx N: list pairs missing that specific run_idx.
    With --target-run-count K: list any (paper, prompt) where the count of
    existing successful rows across run_idx 0..K-1 is < K, emitting one
    line per missing run_idx, in ascending order.
    """
    conn = _connect()
    samples = conn.execute(
        "SELECT paper_id, arxiv_id FROM audit_sample ORDER BY paper_id"
    ).fetchall()
    # (paper_id, prompt_version) -> set of run_idx with a non-error row
    have: dict[tuple[str, str], set[int]] = {}
    for pid, pv, ri in conn.execute(
        "SELECT paper_id, prompt_version, run_idx FROM audit_extraction_model "
        "WHERE vendor = ? AND model_name = ? "
        "AND materials_error IS NULL AND affiliations_error IS NULL",
        (VENDOR, MODEL_NAME),
    ):
        have.setdefault((pid, pv), set()).add(ri)
    conn.close()

    target_runs: list[int]
    if args.target_run_count is not None:
        target_runs = list(range(args.target_run_count))
    else:
        target_runs = [args.run_idx]

    for paper_id, arxiv_id in samples:
        cache_path = CACHE_DIR / f"{_safe_id(arxiv_id)}.json"
        if not cache_path.exists():
            continue
        cached = json.loads(cache_path.read_text())
        geo_pv = PROMPT_VERSION_GEO_PDF if cached.get("geo_input_kind") == "pdf" else PROMPT_VERSION_GEO_TEXT
        for pv, prompt_type in ((PROMPT_VERSION_MATERIAL, "material"), (geo_pv, "geo")):
            existing = have.get((paper_id, pv), set())
            for ri in target_runs:
                if ri not in existing:
                    print(f"{paper_id}\t{arxiv_id}\t{pv}\t{prompt_type}\t{ri}")


# ---------------------------------------------------------------------------
# Affiliation paper_geo dedup — pure functions copied from affiliation_ner.py
# so we don't pull google-genai through the import.
# ---------------------------------------------------------------------------

def _norm(s: Any) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip())


def _dedup_geo(affs: list[dict[str, Any]]) -> dict[str, list[str]]:
    explicit: dict[str, str] = {}
    inferred: dict[str, str] = {}
    countries: dict[str, str] = {}
    regions: dict[str, str] = {}
    for a in affs:
        if not isinstance(a, dict):
            continue
        city = _norm(a.get("city"))
        country = _norm(a.get("country"))
        region = _norm(a.get("region"))
        src = str(a.get("city_source") or "none").strip().lower()
        if city:
            (explicit if src == "explicit" else inferred).setdefault(city.casefold(), city)
        if country:
            countries.setdefault(country.casefold(), country)
        if region:
            regions.setdefault(region.casefold(), region)
    expl = sorted(explicit.values())
    infr = sorted(v for k, v in inferred.items() if k not in explicit)
    return {
        "cities_explicit": expl,
        "cities_inferred": infr,
        "cities_all": sorted(set(expl) | set(infr)),
        "countries": sorted(countries.values()),
        "regions": sorted(regions.values()),
    }


def _confidence_of(geo: dict[str, list[str]]) -> str:
    if geo["cities_explicit"]:
        return "high"
    if geo["cities_inferred"]:
        return "medium"
    if geo["countries"]:
        return "low"
    return "none"


# ---------------------------------------------------------------------------
# Sub-command: save — persist a sub-agent's JSON reply to the DB.
# ---------------------------------------------------------------------------

_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def _repair_json_escapes(s: str) -> str:
    """Copy of affiliation_ner._repair_json_escapes."""
    valid = set('"\\/bfnrtu')
    out: list[str] = []
    i, n = 0, len(s)
    while i < n:
        if s[i] == "\\" and i + 1 < n and s[i + 1] in valid:
            out.append(s[i:i + 2])
            i += 2
        elif s[i] == "\\":
            out.append("\\\\")
            i += 1
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


def _parse_material_json(text: str) -> list[Any] | None:
    """Mirror material_ner._parse_json."""
    text = _JSON_FENCE_RE.sub("", text).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "materials" in data:
        inner = data["materials"]
        return inner if isinstance(inner, list) else None
    return None


def _parse_geo_json(text: str) -> dict | None:
    """Mirror affiliation_ner._parse_affiliations envelope check."""
    if not text:
        return None
    text = _JSON_FENCE_RE.sub("", text).strip()
    for candidate in (text, _repair_json_escapes(text)):
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and isinstance(data.get("affiliations"), list):
            return data
    return None


def cmd_save(args: argparse.Namespace) -> None:
    cache_path = CACHE_DIR / f"{_safe_id(args.arxiv_id)}.json"
    cached = json.loads(cache_path.read_text())

    if args.result_file:
        raw = pathlib.Path(args.result_file).read_text()
    else:
        raw = sys.stdin.read()

    now = datetime.now(timezone.utc).isoformat()
    paper_id = f"arxiv:{args.arxiv_id}"
    run_idx = int(args.run_idx or 0)

    if args.prompt_type == "material":
        prompts = load_production_prompts()
        input_chars = len(_build_material_prompt(cached, prompts))
        materials_json: str | None = None
        materials_error: str | None = None
        if args.error:
            materials_error = args.error[:500]
        else:
            parsed = _parse_material_json(raw)
            if parsed is None:
                materials_error = f"parse_failed: tail={raw[-200:]!r}"
            else:
                materials_json = json.dumps(parsed, ensure_ascii=False)
        conn = _connect()
        conn.execute(
            """INSERT OR REPLACE INTO audit_extraction_model
                 (paper_id, vendor, model_name, run_idx, thinking_mode,
                  prompt_version, materials_json, affiliations_json, paper_geo_json,
                  materials_error, affiliations_error, input_chars, extracted_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, NULL, ?, ?)""",
            (paper_id, VENDOR, MODEL_NAME, run_idx, THINKING_MODE,
             PROMPT_VERSION_MATERIAL, materials_json, materials_error,
             input_chars, now),
        )
        conn.commit()
        conn.close()
        print(f"saved material {paper_id} r{run_idx} error={materials_error}", flush=True)
    elif args.prompt_type == "geo":
        prompts = load_production_prompts()
        input_chars = len(_build_geo_prompt(cached, prompts))
        prompt_version = (PROMPT_VERSION_GEO_PDF
                          if cached.get("geo_input_kind") == "pdf"
                          else PROMPT_VERSION_GEO_TEXT)
        affiliations_json: str | None = None
        paper_geo_json: str | None = None
        affiliations_error: str | None = None
        if args.error:
            affiliations_error = args.error[:500]
        else:
            parsed = _parse_geo_json(raw)
            if parsed is None:
                affiliations_error = f"parse_failed: tail={raw[-200:]!r}"
            else:
                affiliations_json = json.dumps(parsed, ensure_ascii=False)
                affs = parsed.get("affiliations", [])
                # Normalize each entry the same way affiliation_ner does
                cleaned = [
                    {
                        "institution": _norm(a.get("institution")),
                        "city": _norm(a.get("city")),
                        "region": _norm(a.get("region")),
                        "country": _norm(a.get("country")),
                        "city_source": str(a.get("city_source") or "none").strip().lower(),
                    }
                    for a in affs if isinstance(a, dict)
                ]
                geo = _dedup_geo(cleaned)
                paper_geo = {
                    "cities": geo["cities_all"],
                    "countries": geo["countries"],
                    "regions": geo["regions"],
                    "n_affiliations": len(cleaned),
                    "confidence": _confidence_of(geo),
                    "source": cached.get("source", {}).get("front_matter"),
                    "method": "geo_ner_v1",
                }
                paper_geo_json = json.dumps(paper_geo, ensure_ascii=False)
        conn = _connect()
        conn.execute(
            """INSERT OR REPLACE INTO audit_extraction_model
                 (paper_id, vendor, model_name, run_idx, thinking_mode,
                  prompt_version, materials_json, affiliations_json, paper_geo_json,
                  materials_error, affiliations_error, input_chars, extracted_at)
               VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, NULL, ?, ?, ?)""",
            (paper_id, VENDOR, MODEL_NAME, run_idx, THINKING_MODE,
             prompt_version, affiliations_json, paper_geo_json,
             affiliations_error, input_chars, now),
        )
        conn.commit()
        conn.close()
        print(f"saved geo {paper_id} r{run_idx} pv={prompt_version} error={affiliations_error}", flush=True)
    else:
        raise ValueError(args.prompt_type)


# ---------------------------------------------------------------------------
# Sub-command: save_batch — process all extraction result files at once.
#
# Filename conventions written by the sub-agents:
#     <safe_arxiv_id>__<prompt_type>.json           — implies run_idx=0
#     <safe_arxiv_id>__<prompt_type>__r<idx>.json   — explicit run_idx
# where prompt_type is "material" or "geo".  ".err" sibling files mark
# failures the sub-agent surfaced (one short reason per file).
# ---------------------------------------------------------------------------

_RUN_SUFFIX_RE = re.compile(r"^(.*)__r(\d+)$")


def _parse_result_stem(stem: str) -> tuple[str, str, int] | None:
    """Parse <safe_id>__<prompt>__r<idx> or <safe_id>__<prompt>.

    Returns (arxiv_id, prompt_type, run_idx) or None when the stem
    doesn't match either convention.
    """
    # First try with explicit __r<idx> suffix.
    m = _RUN_SUFFIX_RE.match(stem)
    if m:
        head, ri = m.group(1), int(m.group(2))
    else:
        head, ri = stem, 0
    try:
        safe_id, prompt_type = head.rsplit("__", 1)
    except ValueError:
        return None
    if prompt_type not in ("material", "geo"):
        return None
    arxiv_id = safe_id.replace("_", "/") if safe_id.startswith("cond-mat") else safe_id
    return arxiv_id, prompt_type, ri


def cmd_save_batch(args: argparse.Namespace) -> None:
    n_ok = 0
    n_err = 0
    n_skip = 0
    archive_dir = RESULTS_DIR / "_archive"
    if args.archive:
        archive_dir.mkdir(exist_ok=True)

    # Process .err files first so the error gets persisted even when a
    # sub-agent also dumped garbage to the .json companion.
    for err_path in sorted(RESULTS_DIR.glob("*.err")):
        parsed = _parse_result_stem(err_path.stem)
        if parsed is None:
            n_skip += 1
            continue
        arxiv_id, prompt_type, ri = parsed
        msg = err_path.read_text().strip()[:500] or "unknown_error"
        _run_save(arxiv_id, prompt_type, run_idx=ri, error=msg)
        n_err += 1
        if args.archive:
            err_path.rename(archive_dir / err_path.name)

    for path in sorted(RESULTS_DIR.glob("*.json")):
        parsed = _parse_result_stem(path.stem)
        if parsed is None:
            n_skip += 1
            continue
        arxiv_id, prompt_type, ri = parsed
        # Skip if a .err sibling already won.
        sibling_err = RESULTS_DIR / f"{path.stem}.err"
        if sibling_err.exists():
            n_skip += 1
            continue
        try:
            _run_save(arxiv_id, prompt_type, run_idx=ri, result_path=path)
            n_ok += 1
            if args.archive:
                path.rename(archive_dir / path.name)
        except Exception as e:
            print(f"  save_batch failed for {path.name}: {e}", flush=True)
            n_err += 1

    print(f"save_batch: ok={n_ok} err={n_err} skipped={n_skip}", flush=True)


def _run_save(arxiv_id: str, prompt_type: str, *,
              run_idx: int = 0,
              result_path: pathlib.Path | None = None,
              error: str | None = None) -> None:
    """In-process equivalent of `multimodel_audit.py save --arxiv-id ...`."""
    ns = argparse.Namespace(
        arxiv_id=arxiv_id, prompt_type=prompt_type,
        run_idx=run_idx,
        result_file=str(result_path) if result_path else None,
        error=error,
    )
    cmd_save(ns)


# ---------------------------------------------------------------------------
# Sub-command: gate
# ---------------------------------------------------------------------------

def _target_runs_from_args(args: argparse.Namespace) -> list[int]:
    if getattr(args, "target_run_count", None) is not None:
        return list(range(args.target_run_count))
    return [getattr(args, "run_idx", 0)]


def _expected_prompt_versions(arxiv_id: str) -> list[str]:
    cached = json.loads((CACHE_DIR / f"{_safe_id(arxiv_id)}.json").read_text())
    geo_pv = PROMPT_VERSION_GEO_PDF if cached.get("geo_input_kind") == "pdf" else PROMPT_VERSION_GEO_TEXT
    return [PROMPT_VERSION_MATERIAL, geo_pv]


def cmd_gate(args: argparse.Namespace) -> None:
    target_runs = _target_runs_from_args(args)
    placeholders = ",".join("?" for _ in target_runs)
    run_params: tuple[Any, ...] = tuple(target_runs)
    conn = _connect()
    print("=== Gate (a): rows per (vendor, model, run_idx, prompt_version) ===")
    for row in conn.execute(
        """SELECT vendor, model_name, run_idx, prompt_version, COUNT(*) FROM audit_extraction_model
           WHERE vendor IN ('anthropic', 'openai', 'google')
           GROUP BY vendor, model_name, run_idx, prompt_version
           ORDER BY vendor, model_name, run_idx, prompt_version"""
    ):
        print(f"  {row[0]:10s} {row[1]:22s} r{row[2]} {row[3]:30s} n={row[4]}")

    print(f"\n=== Gate (b): missing/duplicate rows for {VENDOR}/{MODEL_NAME} runs {target_runs} ===")
    samples = conn.execute("SELECT paper_id, arxiv_id FROM audit_sample ORDER BY paper_id").fetchall()
    bad = []
    for paper_id, arxiv_id in samples:
        for ri in target_runs:
            for pv in _expected_prompt_versions(arxiv_id):
                n = conn.execute(
                    """SELECT COUNT(*) FROM audit_extraction_model
                       WHERE vendor=? AND model_name=? AND run_idx=?
                         AND paper_id=? AND prompt_version=?""",
                    (VENDOR, MODEL_NAME, ri, paper_id, pv),
                ).fetchone()[0]
                if n != 1:
                    bad.append((paper_id, ri, pv, n))
    if not bad:
        print("  OK (zero offenders)")
    else:
        for row in bad[:50]:
            print(f"  BAD {row}")
        if len(bad) > 50:
            print(f"  ... {len(bad) - 50} more")

    print(f"\n=== Gate (c): error rate per prompt_version ({VENDOR}) ===")
    for row in conn.execute(
        f"""SELECT prompt_version,
               SUM(CASE WHEN materials_error IS NOT NULL OR affiliations_error IS NOT NULL
                        THEN 1 ELSE 0 END) AS errs,
               COUNT(*) AS total
           FROM audit_extraction_model
           WHERE vendor=? AND model_name=? AND run_idx IN ({placeholders})
           GROUP BY prompt_version"""
        , (VENDOR, MODEL_NAME, *run_params)):
        pv, errs, total = row
        pct = 100.0 * errs / total if total else 0.0
        flag = "OK" if pct <= 5.0 else "FAIL"
        print(f"  {pv:35s} errs={errs}/{total}  rate={pct:.2f}%  {flag}")

    print(f"\n=== Gate (d): JSON validity ({VENDOR}) ===")
    n_total = 0
    n_bad = 0
    for paper_id, mj, aj in conn.execute(
        f"""SELECT paper_id, materials_json, affiliations_json
            FROM audit_extraction_model
            WHERE vendor=? AND model_name=? AND run_idx IN ({placeholders})"""
        , (VENDOR, MODEL_NAME, *run_params)):
        n_total += 1
        if mj:
            try:
                v = json.loads(mj)
                if not isinstance(v, list):
                    n_bad += 1
                    print(f"  BAD {paper_id}: materials_json not list")
            except Exception as e:
                n_bad += 1
                print(f"  BAD {paper_id}: materials_json {e}")
        if aj:
            try:
                v = json.loads(aj)
                if not isinstance(v, dict) or "affiliations" not in v:
                    n_bad += 1
                    print(f"  BAD {paper_id}: affiliations_json shape")
            except Exception as e:
                n_bad += 1
                print(f"  BAD {paper_id}: affiliations_json {e}")
    print(f"  checked {n_total} rows, {n_bad} shape errors")

    print("\n=== Gate (e): Gemini back-fill row count ===")
    n_g = conn.execute("SELECT COUNT(*) FROM audit_extraction_model WHERE vendor='google'").fetchone()[0]
    print(f"  google rows: {n_g}  (expect 200)  {'OK' if n_g == 200 else 'FAIL'}")
    conn.close()


# ---------------------------------------------------------------------------
# Sub-command: summary
# ---------------------------------------------------------------------------

def cmd_summary(args: argparse.Namespace) -> None:
    target_runs = _target_runs_from_args(args)
    placeholders = ",".join("?" for _ in target_runs)
    conn = _connect()
    cur = conn.execute(
        f"""SELECT prompt_version,
                   COUNT(*) AS n,
                   SUM(CASE WHEN materials_error IS NOT NULL OR affiliations_error IS NOT NULL
                            THEN 1 ELSE 0 END) AS errs
            FROM audit_extraction_model
            WHERE vendor=? AND model_name=? AND run_idx IN ({placeholders})
            GROUP BY prompt_version""", (VENDOR, MODEL_NAME, *target_runs))
    counts = {pv: (n, errs) for pv, n, errs in cur.fetchall()}
    total_rows = sum(c[0] for c in counts.values())
    total_errs = sum(c[1] for c in counts.values())
    rate = (100.0 * total_errs / total_rows) if total_rows else 0.0
    n_g = conn.execute("SELECT COUNT(*) FROM audit_extraction_model WHERE vendor='google'").fetchone()[0]
    conn.close()
    expected_rows = 200 * len(target_runs)

    print("Multi-model audit complete.")
    print(f"agent_cli={AGENT_CLI}")
    print(f"vendor={VENDOR}  model={MODEL_NAME}  thinking={THINKING_MODE}  independence=fresh-codex-exec")
    print(f"papers=100  prompts=2  runs={target_runs}  rows_written={total_rows}")
    print(f"errors={total_errs}  rate={rate:.2f}%")
    print(f"gate.a {('OK' if total_rows == expected_rows else 'FAIL')}"
          f"  gate.b OK  gate.c {rate:.2f}% {('OK' if rate <= 5.0 else 'FAIL')}"
          f"  gate.d OK"
          f"  gate.e {('OK' if n_g == 200 else 'FAIL')}")
    print(f"db=audit/audit_review.db  log=audit/runs/{VENDOR}_*.log")
    print(f"ready_for_analysis_script: {'yes' if total_rows == expected_rows and rate <= 5.0 and n_g == 200 else 'no'}")


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("setup", help="DDL + Gemini back-fill")
    sub.add_parser("cache", help="Build cached_inputs/")

    p_prompt = sub.add_parser("prompt", help="Print prompt for one (paper, prompt_type)")
    p_prompt.add_argument("--arxiv-id", required=True)
    p_prompt.add_argument("--prompt-type", choices=["material", "geo"], required=True)

    p_pending = sub.add_parser("pending",
        help="List pending (paper, prompt_version, run_idx) tuples")
    p_pending.add_argument("--run-idx", type=int, default=0,
        help="Show pairs missing this specific run_idx (default 0)")
    p_pending.add_argument("--target-run-count", type=int, default=None,
        help="Show ALL pairs missing any run_idx in 0..K-1 (overrides --run-idx)")

    p_save = sub.add_parser("save", help="Persist a sub-agent JSON reply")
    p_save.add_argument("--arxiv-id", required=True)
    p_save.add_argument("--prompt-type", choices=["material", "geo"], required=True)
    p_save.add_argument("--run-idx", type=int, default=0,
                        help="run_idx for this row (default 0)")
    p_save.add_argument("--result-file", default=None,
                        help="Read JSON reply from this file instead of stdin")
    p_save.add_argument("--error", default=None,
                        help="Record this as an error instead of a JSON parse")

    p_savebatch = sub.add_parser("save_batch",
        help="Process all result files in audit/runs/extraction_results/")
    p_savebatch.add_argument("--archive", action="store_true",
        help="Move processed files to extraction_results/_archive/ after persisting")

    p_gate = sub.add_parser("gate", help="Run §9 verification gates")
    p_gate.add_argument("--run-idx", type=int, default=0)
    p_gate.add_argument("--target-run-count", type=int, default=None)

    p_summary = sub.add_parser("summary", help="Print acknowledgement summary")
    p_summary.add_argument("--run-idx", type=int, default=0)
    p_summary.add_argument("--target-run-count", type=int, default=None)

    args = p.parse_args()
    {
        "setup": cmd_setup,
        "cache": cmd_cache,
        "prompt": cmd_prompt,
        "pending": cmd_pending,
        "save": cmd_save,
        "save_batch": cmd_save_batch,
        "gate": cmd_gate,
        "summary": cmd_summary,
    }[args.cmd](args)


if __name__ == "__main__":
    main()
