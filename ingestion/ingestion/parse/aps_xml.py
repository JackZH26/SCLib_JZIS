"""APS BagIt → full text → structured ParsedPaper.

The APS counterpart of ``parse/latex_parser.py``. APS distributes each
article's full text inside a BagIt package; modern payloads usually contain
a JATS XML rendering plus a PDF and OCR, while older payloads can contain
only PDF + OCR. We parse JATS first, then fall back to transient OCR text
when no ``fulltext.xml`` is present, so the downstream material-NER path
can cover older APS years without storing licensed prose.

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

from dataclasses import dataclass
import html.entities
import logging
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from ingestion.models import ApsArticleMeta, ParsedPaper, Section

log = logging.getLogger(__name__)


class ApsParseError(RuntimeError):
    """Raised when no parsable JATS article XML is found in a BagIt dir."""


class UnsupportedApsFulltextError(ApsParseError):
    """Raised for terminal BagIt payload shapes the parser cannot use."""

    def __init__(self, message: str, *, status: str) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True, slots=True)
class ApsParsedFullText:
    parsed: ParsedPaper
    parser_mode: str  # "jats" | "ocr"
    source_path: Path


# JATS tags that signal an equation / table inside a section subtree.
_EQUATION_TAGS = {"disp-formula", "inline-formula", "tex-math", "math", "mml:math"}
_TABLE_TAGS = {"table-wrap", "table", "array"}
# Tags whose textual content is metadata / non-prose and should not be
# pulled into a section's NER text.
_SKIP_TEXT_TAGS = {"label", "xref", "fn", "table-wrap-foot"}
_OCR_HEADING_RE = re.compile(
    r"^(?:(?:[IVX]+|\d+)\.\s+)?"
    r"(INTRODUCTION|BACKGROUND|EXPERIMENTAL|EXPERIMENT|METHODS?|"
    r"RESULTS?|DISCUSSION|THEORY|MODEL|CALCULATION|CONCLUSIONS?|SUMMARY)"
    r"\b.*$",
    re.I,
)
_OCR_BACK_MATTER_RE = re.compile(
    r"^(ACKNOWLEDGMENTS?|REFERENCES|BIBLIOGRAPHY)\b", re.I,
)
_OCR_MIN_CHARS = 200


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


def find_fulltext_ocr(bagit_root: Path) -> Path | None:
    """Return the OCR text payload inside an extracted BagIt dir, if any."""
    preferred = sorted(bagit_root.rglob("fulltext.ocr"))
    if preferred:
        return preferred[0]
    candidates = sorted(bagit_root.rglob("*.ocr"))
    return candidates[0] if candidates else None


def parse_bagit_payload(bagit_root: Path, meta: ApsArticleMeta) -> ApsParsedFullText:
    """Parse the best available APS full-text payload.

    JATS XML is preferred. Older APS BagIt packages often lack XML but
    include ``fulltext.ocr``; use that as a transient fallback. If neither
    source exists, raise a terminal unsupported error rather than a generic
    retryable parser failure.
    """
    xml_path = find_fulltext_xml(bagit_root)
    if xml_path is not None:
        return ApsParsedFullText(
            parsed=parse_jats(xml_path.read_bytes(), meta),
            parser_mode="jats",
            source_path=xml_path,
        )

    ocr_path = find_fulltext_ocr(bagit_root)
    if ocr_path is not None:
        return ApsParsedFullText(
            parsed=parse_ocr(ocr_path.read_bytes(), meta),
            parser_mode="ocr",
            source_path=ocr_path,
        )

    raise UnsupportedApsFulltextError(
        f"no JATS <article> XML or fulltext OCR under {bagit_root}",
        status="unsupported_no_jats",
    )


def parse_bagit_dir(bagit_root: Path, meta: ApsArticleMeta) -> ParsedPaper:
    """Find + parse full text in an extracted BagIt dir.

    Kept as the historical API for tests and callers that only need the
    ``ParsedPaper``. New APS ingestion code uses ``parse_bagit_payload`` so
    it can record parser provenance.
    """
    return parse_bagit_payload(bagit_root, meta).parsed


def parse_jats(xml_data: bytes, meta: ApsArticleMeta) -> ParsedPaper:
    """Parse JATS XML bytes into a ParsedPaper (body → Section list)."""
    xml_data = _replace_html_entities(xml_data)
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


def parse_ocr(ocr_data: bytes, meta: ApsArticleMeta) -> ParsedPaper:
    """Parse APS ``fulltext.ocr`` bytes into a transient ParsedPaper.

    OCR quality varies across older APS scans. The goal here is not perfect
    layout reconstruction; it is to give NER clean enough prose while
    trimming obvious back matter and keeping the raw OCR out of persistent
    storage.
    """
    text = _clean_ocr_text(ocr_data)
    if len(text) < _OCR_MIN_CHARS:
        raise UnsupportedApsFulltextError(
            "fulltext OCR is missing or too short to parse",
            status="unsupported_no_text",
        )
    sections = _split_ocr_sections(text)
    if not sections:
        sections = [Section(name="OCR Full Text", text=text)]
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


def _clean_ocr_text(ocr_data: bytes) -> str:
    text = ocr_data.decode("utf-8", errors="replace")
    text = text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\f", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    raw_lines = [line.strip() for line in text.splitlines()]

    lines: list[str] = []
    blank = False
    for line in raw_lines:
        if _OCR_BACK_MATTER_RE.match(line):
            break
        if not line:
            if not blank:
                lines.append("")
            blank = True
            continue
        blank = False
        # Common scan/footer noise: standalone page numbers or APS copyright.
        if re.fullmatch(r"\d{1,4}", line):
            continue
        if "©" in line and "American Physical Society" in line:
            continue
        lines.append(line)

    paragraphs: list[str] = []
    current: list[str] = []
    for line in lines:
        if not line:
            if current:
                paragraphs.append(_join_ocr_lines(current))
                current = []
            continue
        if _looks_like_ocr_heading(line):
            if current:
                paragraphs.append(_join_ocr_lines(current))
                current = []
            paragraphs.append(line)
            continue
        current.append(line)
    if current:
        paragraphs.append(_join_ocr_lines(current))

    return "\n\n".join(p for p in paragraphs if p.strip()).strip()


def _join_ocr_lines(lines: list[str]) -> str:
    out = ""
    for line in lines:
        if not out:
            out = line
            continue
        if out.endswith("-") and line[:1].islower():
            out = out[:-1] + line
        else:
            out += " " + line
    return _collapse_ws(out)


def _looks_like_ocr_heading(line: str) -> bool:
    if len(line) > 90:
        return False
    if _OCR_HEADING_RE.match(line):
        return True
    letters = [ch for ch in line if ch.isalpha()]
    return bool(letters) and len(letters) >= 4 and sum(ch.isupper() for ch in letters) / len(letters) > 0.8


def _split_ocr_sections(text: str) -> list[Section]:
    sections: list[Section] = []
    current_name = "OCR Full Text"
    current_parts: list[str] = []

    def flush() -> None:
        nonlocal current_parts
        body = _collapse_ws("\n".join(current_parts))
        if body:
            sections.append(Section(name=current_name, text=body))
        current_parts = []

    for block in re.split(r"\n{2,}", text):
        block = block.strip()
        if not block:
            continue
        if _looks_like_ocr_heading(block):
            flush()
            current_name = _normalise_ocr_heading(block)
            continue
        current_parts.append(block)
    flush()
    return sections


def _normalise_ocr_heading(line: str) -> str:
    line = re.sub(r"^(?:[IVX]+|\d+)\.\s+", "", line.strip(), flags=re.I)
    line = _collapse_ws(line)
    return line.title() if line.isupper() else line


def _replace_html_entities(xml_data: bytes) -> bytes:
    """Convert non-XML HTML entities in APS JATS into numeric refs.

    APS JATS occasionally contains named HTML entities such as ``&ndash;`` or
    ``&frac14;`` that stdlib ElementTree rejects because only XML's five
    predefined entities are known. Keep unknown/custom entities untouched so
    genuine malformed XML still raises a parse error.
    """
    text = xml_data.decode("utf-8", errors="replace")
    xml_predefined = {"amp", "lt", "gt", "quot", "apos"}

    def repl(match: re.Match[str]) -> str:
        name = match.group(1)
        if name in xml_predefined or name.startswith("#"):
            return match.group(0)
        value = html.entities.html5.get(f"{name};")
        if not value:
            return match.group(0)
        return "".join(f"&#{ord(ch)};" for ch in value)

    return re.sub(r"&([A-Za-z][A-Za-z0-9]+|#[0-9]+|#x[0-9A-Fa-f]+);", repl, text).encode("utf-8")
