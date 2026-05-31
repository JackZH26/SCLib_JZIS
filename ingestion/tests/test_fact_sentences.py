"""Unit tests for ingestion.extract.fact_sentences.

Pure rendering — no network/DB. Verifies the NER-record → sentence
mapping, the noise filter, primary-before-cited ordering, the chunk cap,
and that build_authorized_chunks combines abstract + fact chunks (and
never the body).
"""
from __future__ import annotations

from ingestion.extract.fact_sentences import (
    _MAX_FACT_CHUNKS,
    build_authorized_chunks,
    build_fact_chunks,
    fact_sentence,
)
from ingestion.models import ApsArticleMeta


def _meta() -> ApsArticleMeta:
    return ApsArticleMeta(
        doi="10.1103/PhysRevB.104.014501",
        title="Test", authors=["A B"],
        abstract="We report superconductivity near 14 K.",
    )


def test_fact_sentence_full():
    s = fact_sentence({
        "formula": "MgB2", "tc_kelvin": 39, "method": "experimental",
        "measurement": "resistivity", "family": "iron-based",
        "pressure_condition_normalized": "ambient",
    })
    assert s == ("MgB2 has a critical temperature Tc = 39 K "
                 "(experimental, resistivity) at ambient pressure. [iron-based]")


def test_fact_sentence_trims_trailing_zero():
    s = fact_sentence({"formula": "FeSe", "tc_kelvin": 8.0})
    assert "Tc = 8 K" in s  # not "8.0 K"


def test_fact_sentence_pressure_gpa():
    s = fact_sentence({"formula": "H3S", "tc_kelvin": 203, "pressure_gpa": 155})
    assert "at 155 GPa" in s


def test_fact_sentence_no_tc_but_has_context():
    s = fact_sentence({"formula": "LaH10", "family": "hydride",
                       "crystal_structure": "Fm-3m"})
    assert s is not None
    assert "LaH10 is reported" in s
    assert "hydride" in s and "Fm-3m" in s


def test_fact_sentence_doping_type_and_level():
    s = fact_sentence({"formula": "LSCO", "tc_kelvin": 38,
                       "doping_type": "hole", "doping_level": 0.15})
    assert "doping: hole x=0.15" in s


def test_fact_sentence_regime_colours_but_is_not_sole_signal():
    # Regime alone (no Tc, no other context) is still noise.
    assert fact_sentence({"formula": "X", "tc_regime": "bulk_equilibrium"}) is None
    # But with a Tc, high_pressure regime colours the sentence.
    s = fact_sentence({"formula": "H3S", "tc_kelvin": 203,
                       "tc_regime": "high_pressure"})
    assert "under high pressure" in s


def test_fact_sentence_bare_formula_is_noise():
    # Just a formula, nothing else → skipped (abstract already mentions it).
    assert fact_sentence({"formula": "Cu"}) is None
    assert fact_sentence({"formula": ""}) is None
    assert fact_sentence({}) is None


def test_fact_sentence_comment_appended():
    s = fact_sentence({"formula": "YBCO", "tc_kelvin": 92, "comment": "onset Tc"})
    assert s.endswith("Note: onset Tc.")


def test_build_fact_chunks_ids_and_metadata():
    mats = [
        {"formula": "MgB2", "tc_kelvin": 39},
        {"formula": "FeSe", "tc_kelvin": 8},
    ]
    chunks = build_fact_chunks(_meta(), mats, start_index=1)
    assert [c.chunk_index for c in chunks] == [1, 2]
    assert chunks[0].id == "aps:10.1103/PhysRevB.104.014501_fact_001"
    assert chunks[0].section == "Facts"
    assert chunks[0].materials_mentioned == [mats[0]]
    assert "Section: Facts" in chunks[0].text


def test_build_fact_chunks_primary_before_cited():
    mats = [
        {"formula": "CITED", "tc_kelvin": 1, "evidence_type": "cited"},
        {"formula": "PRIMARY", "tc_kelvin": 2, "evidence_type": "primary"},
    ]
    chunks = build_fact_chunks(_meta(), mats, start_index=0)
    assert "PRIMARY" in chunks[0].text
    assert "CITED" in chunks[1].text


def test_build_fact_chunks_respects_cap():
    mats = [{"formula": f"M{i}", "tc_kelvin": i} for i in range(_MAX_FACT_CHUNKS + 10)]
    chunks = build_fact_chunks(_meta(), mats, start_index=0)
    assert len(chunks) == _MAX_FACT_CHUNKS


def test_build_authorized_chunks_combines_abstract_and_facts():
    mats = [{"formula": "MgB2", "tc_kelvin": 39}]
    chunks = build_authorized_chunks(_meta(), mats)
    sections = [c.section for c in chunks]
    assert "Abstract" in sections
    assert "Facts" in sections
    # ids are unique.
    assert len({c.id for c in chunks}) == len(chunks)
    blob = " ".join(c.text for c in chunks)
    assert "14 K" in blob          # abstract
    assert "Tc = 39 K" in blob     # fact sentence
