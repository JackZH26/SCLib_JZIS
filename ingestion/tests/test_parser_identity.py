"""Producer identity follows the actual indexed representation, not paper genre."""
from ingestion.chunk.chunker import chunk_paper
from ingestion.extract.fact_sentences import build_authorized_chunks
from ingestion.models import ApsArticleMeta, PaperMetadata, ParsedPaper, Section
from ingestion.parse.aps_xml import parse_jats, parse_ocr
from ingestion.parse.latex_parser import PARSER_VERSION, parse_source_tarball


def arxiv_meta():
    return PaperMetadata(arxiv_id="2609.99620", title="Synthetic", authors=[], abstract="",
                         date_submitted=None, categories=[], primary_category=None)


def aps_meta():
    return ApsArticleMeta(doi="10.0000/ParserFixture", title="Synthetic", authors=[], abstract="Metadata abstract.")


def test_real_latex_parser_version_flows_into_chunks():
    parsed = parse_source_tarball(rb"\documentclass{article}\begin{document}\section{Results}Complete text.\end{document}", arxiv_meta())
    assert parsed.parser_version == PARSER_VERSION
    assert all(chunk.parser_version == PARSER_VERSION for chunk in chunk_paper(parsed))


def test_jats_and_ocr_have_distinct_explicit_producers():
    jats = parse_jats(b"<article><body><sec><title>Results</title><p>Exact body.</p></sec></body></article>", aps_meta())
    ocr = parse_ocr(("Synthetic research text about superconductivity and measurements. " * 50).encode(), aps_meta())
    assert jats.parser_version == "sclib-aps-jats-parser/1.0.0"
    assert ocr.parser_version == "sclib-aps-ocr-parser/1.0.0"
    assert all(chunk.parser_version == jats.parser_version for chunk in chunk_paper(jats))
    assert all(chunk.parser_version == ocr.parser_version for chunk in chunk_paper(ocr))


def test_unknown_parser_is_not_invented_from_a_source_flag():
    parsed = ParsedPaper(arxiv_meta(), [Section("Results", "Original text.")], has_latex_source=True)
    assert all(chunk.parser_version is None for chunk in chunk_paper(parsed))


def test_aps_authorized_outputs_are_metadata_and_structured_projection_not_fulltext_parser():
    chunks = build_authorized_chunks(aps_meta(), [{"formula": "Nb", "tc_kelvin": "9.2 K"}])
    assert len(chunks) == 2
    assert chunks[0].parser_version == "sclib-metadata-abstract/1.0.0"
    assert chunks[1].parser_version == "sclib-structured-fact-projection/1.0.0"


def test_metadata_fallback_does_not_claim_the_abandoned_body_parser():
    meta = arxiv_meta()
    meta.abstract = "Metadata abstract."
    parsed = ParsedPaper(meta, [], parser_version="abandoned-body-parser/1")
    assert chunk_paper(parsed)[0].parser_version == "sclib-metadata-abstract/1.0.0"
