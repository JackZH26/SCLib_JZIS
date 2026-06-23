"""Unit tests for ingestion.parse.aps_xml (JATS → ParsedPaper).

Pure parsing, no network/DB. A compact JATS fixture exercises section
splitting, title extraction, equation/table flagging, namespace
stripping, and the reference-list exclusion (refs live in <back>, never
in <body>).
"""
from __future__ import annotations

from ingestion.models import ApsArticleMeta
from ingestion.parse.aps_xml import (
    ApsParseError,
    UnsupportedApsFulltextError,
    parse_ocr,
    parse_jats,
)


def _meta() -> ApsArticleMeta:
    return ApsArticleMeta(
        doi="10.1103/PhysRevB.104.014501",
        title="Test article", authors=["A B"], abstract="abs",
    )


JATS = b"""<?xml version="1.0"?>
<article>
  <front><article-meta><title-group>
    <article-title>Test article</article-title>
  </title-group></article-meta></front>
  <body>
    <sec id="s1">
      <title>Introduction</title>
      <p>We study MgB2 with a critical temperature.</p>
    </sec>
    <sec id="s2">
      <title>Results</title>
      <p>The Tc reaches 39 K as shown.</p>
      <disp-formula><tex-math>T_c = 39</tex-math></disp-formula>
      <table-wrap><table><tr><td>x</td></tr></table></table-wrap>
    </sec>
  </body>
  <back>
    <ref-list><ref><mixed-citation>Should NOT appear in any section.</mixed-citation></ref></ref-list>
  </back>
</article>
"""


def test_parse_jats_sections():
    parsed = parse_jats(JATS, _meta())
    names = [s.name for s in parsed.sections]
    assert names == ["Introduction", "Results"]
    assert parsed.has_latex_source is False
    assert parsed.meta.paper_id == "aps:10.1103/PhysRevB.104.014501"


def test_parse_jats_text_and_flags():
    parsed = parse_jats(JATS, _meta())
    intro, results = parsed.sections
    assert "MgB2" in intro.text
    assert "critical temperature" in intro.text
    assert intro.has_equation is False
    assert intro.has_table is False
    # Results section carries the equation + table flags.
    assert "39 K" in results.text
    assert results.has_equation is True
    assert results.has_table is True
    # tex-math content is kept (Tc values often live in formulae).
    assert "T_c = 39" in results.text


def test_parse_jats_excludes_references():
    parsed = parse_jats(JATS, _meta())
    blob = " ".join(s.text for s in parsed.sections)
    assert "Should NOT appear" not in blob


def test_parse_jats_namespaced():
    ns = b"""<?xml version="1.0"?>
    <article xmlns="http://jats.nlm.nih.gov">
      <body><sec><title>Methods</title><p>Sample grown.</p></sec></body>
    </article>"""
    parsed = parse_jats(ns, _meta())
    assert [s.name for s in parsed.sections] == ["Methods"]
    assert "Sample grown." in parsed.sections[0].text


def test_parse_jats_no_sec_flattens_body():
    flat = b"""<?xml version="1.0"?>
    <article><body><p>Loose paragraph one.</p><p>Loose two.</p></body></article>"""
    parsed = parse_jats(flat, _meta())
    assert len(parsed.sections) == 1
    assert parsed.sections[0].name == "Body"
    assert "Loose paragraph one." in parsed.sections[0].text
    assert "Loose two." in parsed.sections[0].text


def test_parse_jats_html_entities():
    xml = b"""<?xml version="1.0"?>
    <article><body><sec><title>Results</title>
      <p>Quarter filling &frac14; and range 10&ndash;20 K.</p>
    </sec></body></article>"""
    parsed = parse_jats(xml, _meta())
    assert "Quarter filling \u00bc" in parsed.sections[0].text
    assert "10\u201320 K" in parsed.sections[0].text


def test_parse_ocr_sections_and_trims_references():
    ocr = b"""
PHYSICAL REVIEW B

I. INTRODUCTION

We measured MgB2 and observed superconductivity near 39 K.

II. RESULTS

The sample shows zero resistance at 38 K and a diamagnetic transition.
The temperature dependence was measured on multiple cooling cycles, and
the superconducting transition remained sharp within the experimental
resolution of the transport and susceptibility measurements.

REFERENCES

[1] This cited material should not be included.
"""
    parsed = parse_ocr(ocr, _meta())
    assert [s.name for s in parsed.sections] == ["Introduction", "Results"]
    blob = " ".join(s.text for s in parsed.sections)
    assert "MgB2" in blob
    assert "zero resistance" in blob
    assert "This cited material" not in blob


def test_parse_ocr_too_short_is_terminal():
    import pytest

    with pytest.raises(UnsupportedApsFulltextError) as exc:
        parse_ocr(b"too short", _meta())
    assert exc.value.status == "unsupported_no_text"


def test_parse_jats_bad_xml_raises():
    import pytest
    with pytest.raises(ApsParseError):
        parse_jats(b"<article><body><sec>unclosed", _meta())
