"""APS BagIt → JATS full-text XML → structured ParsedPaper.

The APS counterpart of ``parse/latex_parser.py``. APS distributes each
article's full text inside a BagIt package; the payload (under ``data/``)
contains a JATS XML rendering of the article plus a PDF and OCR. We parse
the JATS ``<body>`` into the same ``Section`` list the LaTeX parser
produces, so the downstream chunker / material-NER run unchanged.

The JATS ``<body>`` deliberately excludes the reference list (JATS keeps
that in ``<back>``), which matches the LaTeX parser dropping the
bibliography — only the authors' own prose feeds NER.

Compliance note: every byte parsed here is transient Licensed Material.
This module reads from an already-extracted temp dir (managed +
force-deleted by ``aps_storage``) and returns only the derived
``ParsedPaper``; it never copies the XML anywhere persistent. The
``ParsedPaper.meta`` is an ``ApsArticleMeta`` (duck-typed in place of
``PaperMetadata``) so ``meta.paper_id`` is ``aps:{doi}`` and the
extractor/chunker — which only touch ``.title`` / ``.abstract`` /
``.paper_id`` / ``.sections`` — work without modification.

Parsing uses stdlib ``xml.etree.ElementTree`` (like ``collect/arxiv_oai``)
so no lxml dependency is added. JATS core elements are conventionally
un-namespaced, but we strip any namespace defensively via ``_local``.
"""
from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from ingestion.models import ApsArticleMeta, ParsedPaper, Section

log = logging.getLogger(__name__)


class ApsParseError(RuntimeError):
    """Raised when no parsable JATS article XML is found in a BagIt dir."""


# JATS tags that signal an equation / table inside a section subtree.
_EQUATION_TAGS = {"disp-formula", "inline-formula", "tex-math", "math", "mml:math"}
_TABLE_TAGS = {"table-wrap", "table", "array"}
# Tags whose textual content is metadata / non-prose and should not be
# pulled into a section's NER text.
_SKIP_TEXT_TAGS = {"label", "xref", "fn", "table-wrap-foot"}


def _local(tag: str) -> str:
    """Strip an XML namespace: ``{http://...}sec`` → ``sec``."""
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


# ---------------------------------------------------------------------------
# Locate + parse
# ---------------------------------------------------------------------------

def find_fulltext_xml(bagit_root: Path) -> Path | None:
    """Return the JATS article XML inside an extracted BagIt dir.

    Scans every ``*.xml`` under the tree (BagIt payload lives under
    ``data/``) and picks the first whose root element is a JATS
    ``<article>``. Returns None if there is none.
    """
    candidates = sorted(bagit_root.rglob("*.xml"))
    for path in candidates:
        try:
            # Peek at the root element only — cheap, avoids full parse of
            # non-article XML (e.g. a BagIt manifest).
            for _evt, el in ET.iterparse(path, events=("start",)):
                return path if _local(el.tag) == "article" else None
        except ET.ParseError:
            continue
    return None


def parse_bagit_dir(bagit_root: Path, meta: ApsArticleMeta) -> ParsedPaper:
    """Find + parse the JATS article in an extracted BagIt dir."""
    xml_path = find_fulltext_xml(bagit_root)
    if xml_path is None:
        raise ApsParseError(f"no JATS <article> XML under {bagit_root}")
    data = xml_path.read_bytes()
    return parse_jats(data, meta)


def parse_jats(xml_data: bytes, meta: ApsArticleMeta) -> ParsedPaper:
    """Parse JATS XML bytes into a ParsedPaper (body → Section list)."""
    try:
        root = ET.fromstring(xml_data)
    except ET.ParseError as e:
        raise ApsParseError(f"JATS parse error: {e}") from e

    # Find <body> regardless of namespace / nesting under <article>.
    body = None
    for el in root.iter():
        if _local(el.tag) == "body":
            body = el
            break

    sections: list[Section] = []
    if body is not None:
        sections = list(_split_sections(body))

    # Fallback: no <sec> structure — flatten the whole body to one Section.
    if not sections and body is not None:
        text = _gather_text(body)
        if text.strip():
            sections = [Section(
                name="Body",
                text=text,
                has_equation=_has_descendant(body, _EQUATION_TAGS),
                has_table=_has_descendant(body, _TABLE_TAGS),
            )]

    return ParsedPaper(meta=meta, sections=sections, has_latex_source=False)


# ---------------------------------------------------------------------------
# Section extraction
# ---------------------------------------------------------------------------

def _split_sections(body: ET.Element) -> list[Section]:
    """One Section per top-level ``<sec>``; body-level loose ``<p>`` (text
    before the first sec) becomes a leading "Body" section."""
    sections: list[Section] = []

    # Loose paragraphs that sit directly under <body> before any <sec>.
    lead_parts: list[str] = []
    for child in list(body):
        if _local(child.tag) == "sec":
            break
        if _local(child.tag) == "p":
            lead_parts.append(_gather_text(child))
    lead_text = _collapse_ws("\n".join(p for p in lead_parts if p.strip()))
    if lead_text:
        sections.append(Section(name="Body", text=lead_text))

    for sec in body:
        if _local(sec.tag) != "sec":
            continue
        name = _section_title(sec)
        text = _gather_text(sec)
        if not text.strip():
            continue
        sections.append(Section(
            name=name,
            text=text,
            has_equation=_has_descendant(sec, _EQUATION_TAGS),
            has_table=_has_descendant(sec, _TABLE_TAGS),
        ))
    return sections


def _section_title(sec: ET.Element) -> str:
    for child in sec:
        if _local(child.tag) == "title":
            t = _collapse_ws("".join(child.itertext()))
            if t:
                return t
    return "Section"


def _gather_text(el: ET.Element) -> str:
    """Collect human-readable prose under ``el``.

    Skips the section's own ``<title>`` (captured separately) and
    metadata-ish tags, but keeps formula tex-math and table cell text —
    Tc values and compositions frequently live in equations and tables.
    NUL bytes are scrubbed (asyncpg rejects them, mirroring the LaTeX
    parser's ``_decode``).
    """
    parts: list[str] = []

    def walk(node: ET.Element, *, is_section_root: bool) -> None:
        for child in node:
            lname = _local(child.tag)
            if is_section_root and lname == "title":
                continue  # section heading handled by _section_title
            if lname in _SKIP_TEXT_TAGS:
                # Keep the tail text that follows the skipped element.
                if child.tail:
                    parts.append(child.tail)
                continue
            if lname == "sec":
                # Inline a subsection's title so context isn't lost.
                sub_title = _section_title(child)
                if sub_title and sub_title != "Section":
                    parts.append(sub_title + ":")
                walk(child, is_section_root=True)
            else:
                if child.text:
                    parts.append(child.text)
                walk(child, is_section_root=False)
            if child.tail:
                parts.append(child.tail)

    if el.text:
        parts.append(el.text)
    walk(el, is_section_root=True)
    return _collapse_ws("".join(parts)).replace("\x00", "")


def _has_descendant(el: ET.Element, tags: set[str]) -> bool:
    for d in el.iter():
        if _local(d.tag) in tags:
            return True
    return False


def _collapse_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()
