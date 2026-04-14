"""arXiv LaTeX source → structured ParsedPaper.

arXiv distributes papers as gzipped tar archives containing one or more
``.tex`` files plus figures. The main file is usually obvious — it holds
``\\documentclass`` — but some papers use ``\\input`` to split the body
across includes, so we inline them recursively before detexing.

Section splitting is regex-based (looking for ``\\section`` /
``\\subsection`` at column 0). For robustness we fall back to a single
"Body" section when no explicit headings are found.

Equations and tables are detected heuristically (``\\begin{equation}``,
``\\begin{table}``) and flagged on the section they appear in so chunks
can propagate ``has_equation`` / ``has_table`` metadata.

This parser aims for "good enough for RAG" — it is NOT a faithful LaTeX
renderer. The pylatexenc LatexNodes2Text pass strips commands we don't
recognize and discards bibliographies.
"""
from __future__ import annotations

import io
import logging
import re
import tarfile
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Iterable

from pylatexenc.latex2text import LatexNodes2Text

from ingestion.models import ParsedPaper, PaperMetadata, Section

log = logging.getLogger(__name__)

_DOCUMENTCLASS_RE = re.compile(r"\\documentclass[\[\{]")
_INPUT_RE = re.compile(r"\\(?:input|include)\{([^}]+)\}")
_SECTION_RE = re.compile(
    r"^\s*\\(section|subsection|subsubsection)\*?\{([^}]*)\}",
    re.MULTILINE,
)
_BEGIN_DOC_RE = re.compile(r"\\begin\{document\}")
_END_DOC_RE = re.compile(r"\\end\{document\}")
_BIB_RE = re.compile(r"\\(bibliography|printbibliography|begin\{thebibliography\})")
_EQUATION_RE = re.compile(
    r"\\begin\{(equation|eqnarray|align|gather|multline|displaymath)\*?\}",
    re.IGNORECASE,
)
_TABLE_RE = re.compile(r"\\begin\{(table|tabular|longtable)\*?\}", re.IGNORECASE)


@dataclass
class _TexFile:
    path: str
    body: str


class LatexParseError(RuntimeError):
    """Raised when the archive does not look like an arXiv LaTeX paper."""


def parse_source_tarball(data: bytes, meta: PaperMetadata) -> ParsedPaper:
    """Unpack a ``.tar.gz`` (or bare .tex) and return a ``ParsedPaper``."""
    # Defend against already-polluted GCS blobs: earlier ingestion runs
    # may have uploaded PDF bytes under src/ before the arxiv client
    # learned to reject PDF responses from /src/. Treat PDF bytes as a
    # "no source" signal so the pipeline falls through to the PDF path.
    if data[:5] == b"%PDF-":
        raise LatexParseError("archive is actually a PDF")

    tex_files = _extract_tex_files(data)
    if not tex_files:
        raise LatexParseError("no .tex files in archive")

    main = _find_main(tex_files)
    body = _inline_inputs(main, tex_files)
    body = _strip_preamble(body)
    body = _strip_bibliography(body)

    sections = list(_split_sections(body))
    if not sections:
        sections = [Section(name="Body", text=_detex(body))]

    return ParsedPaper(meta=meta, sections=sections, has_latex_source=True)


# ---------------------------------------------------------------------------
# internal helpers
# ---------------------------------------------------------------------------

def _extract_tex_files(data: bytes) -> list[_TexFile]:
    """Read every .tex file in the archive into memory.

    arXiv sometimes distributes a bare .tex (no tar), sometimes a .tar with
    a single .gz, sometimes a proper .tar.gz. Try each in turn.
    """
    out: list[_TexFile] = []

    # Case 1: gzipped tar (most common)
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
                    raw = f.read()
                    out.append(_TexFile(
                        path=member.name,
                        body=_decode(raw),
                    ))
                if out:
                    return out
        except tarfile.ReadError:
            continue
        except Exception as e:
            log.debug("tar read failed mode=%s: %s", mode, e)

    # Case 2: bare .tex (maybe gzipped)
    try:
        import gzip
        decoded = gzip.decompress(data)
        return [_TexFile(path="main.tex", body=_decode(decoded))]
    except OSError:
        pass

    # Case 3: bare .tex uncompressed
    try:
        return [_TexFile(path="main.tex", body=_decode(data))]
    except UnicodeDecodeError:
        return []


def _decode(raw: bytes) -> str:
    for enc in ("utf-8", "latin-1"):
        try:
            decoded = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        decoded = raw.decode("utf-8", errors="replace")
    # Postgres TEXT cannot store NUL (0x00), and asyncpg rejects them
    # outright. Scrub them here so a weird .tex with a stray NUL can't
    # kill the whole paper's chunk insert.
    return decoded.replace("\x00", "")


def _find_main(files: list[_TexFile]) -> _TexFile:
    """Pick the .tex file that contains ``\\documentclass``."""
    candidates = [f for f in files if _DOCUMENTCLASS_RE.search(f.body)]
    if candidates:
        # Prefer files at the archive root (shortest path).
        candidates.sort(key=lambda f: len(PurePosixPath(f.path).parts))
        return candidates[0]
    # No \documentclass — fall back to the longest .tex file
    return max(files, key=lambda f: len(f.body))


def _inline_inputs(main: _TexFile, all_files: list[_TexFile]) -> str:
    """Recursively inline ``\\input{foo}`` and ``\\include{foo}``.

    LaTeX lets you omit the .tex extension and reference files by any
    relative path inside the archive; we resolve them by basename.
    """
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


def _strip_preamble(body: str) -> str:
    """Keep only content between ``\\begin{document}`` and ``\\end{document}``."""
    begin = _BEGIN_DOC_RE.search(body)
    end = _END_DOC_RE.search(body)
    if begin is None:
        return body
    start = begin.end()
    stop = end.start() if end else len(body)
    return body[start:stop]


def _strip_bibliography(body: str) -> str:
    match = _BIB_RE.search(body)
    if match is None:
        return body
    return body[: match.start()]


def _split_sections(body: str) -> Iterable[Section]:
    matches = list(_SECTION_RE.finditer(body))
    if not matches:
        return
    for i, m in enumerate(matches):
        name = m.group(2).strip() or f"Section {i + 1}"
        start = m.end()
        stop = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        raw = body[start:stop]
        has_eq = bool(_EQUATION_RE.search(raw))
        has_tbl = bool(_TABLE_RE.search(raw))
        yield Section(
            name=_detex(name),
            text=_detex(raw),
            has_equation=has_eq,
            has_table=has_tbl,
        )


_DETEX = LatexNodes2Text(
    math_mode="text",
    strict_latex_spaces=False,
    keep_comments=False,
)


def _detex(s: str) -> str:
    try:
        out = _DETEX.latex_to_text(s)
    except Exception:  # pylatexenc can crash on exotic macros
        out = s
    return re.sub(r"[ \t]+\n", "\n", out).strip()
