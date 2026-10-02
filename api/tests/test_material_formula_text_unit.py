"""Connection-free query and SQL compiler checks; --noconftest is safe here."""
from __future__ import annotations

import pytest
from sqlalchemy import column, select
from sqlalchemy.dialects import postgresql

from services import material_formula_text as formula_text


@pytest.mark.parametrize("query", [None, "", "   ", "\u00a0\u3000"])
def test_blank_formula_query_has_no_prefilter(query):
    assert formula_text.formula_text_pattern(query) is None
    assert formula_text.formula_text_contains(column("formula"), query) is None


def test_pasted_subscripts_and_compatibility_symbols_are_literal_normalized_text():
    assert formula_text.formula_text_pattern("  CrB₂  ") == "%CrB2%"
    assert formula_text.formula_text_pattern("ＦｅＳｅ") == "%FeSe%"
    # No chemical equivalence, element-order rewrite, alias or phase expansion.
    assert formula_text.formula_text_pattern("B2Cr") == "%B2Cr%"
    assert formula_text.formula_text_pattern("FeSe (phase II)") == "%FeSe (phase II)%"


def test_wildcards_backslash_and_sql_syntax_remain_only_bound_literal_data():
    query = "Cr%_\\B2' OR TRUE --"
    pattern = formula_text.formula_text_pattern(query)
    assert pattern == "%Cr\\%\\_\\\\B2' OR TRUE --%"
    stmt = select(column("formula")).where(formula_text.formula_text_contains(column("formula"), query))
    compiled = stmt.compile(dialect=postgresql.dialect())
    assert "normalize(formula, NFKC) ILIKE" in str(compiled)
    assert "ESCAPE" in str(compiled)
    assert "OR TRUE" not in str(compiled)
    assert list(compiled.params.values()) == [pattern]


@pytest.mark.parametrize("codepoint", [*range(32), *range(127, 160)])
def test_c0_and_c1_controls_rejected_even_when_whitespace_or_inside_text(codepoint):
    with pytest.raises(formula_text.FormulaTextQueryError, match="control"):
        formula_text.formula_text_pattern("Nb"+chr(codepoint))


def test_raw_and_normalized_lengths_are_both_bounded():
    assert formula_text.formula_text_pattern("A"*200) == "%"+"A"*200+"%"
    with pytest.raises(formula_text.FormulaTextQueryError, match="200"):
        formula_text.formula_text_pattern(" "*201)
    with pytest.raises(formula_text.FormulaTextQueryError, match="200"):
        formula_text.formula_text_pattern("ﬃ"*67)  # 67 raw, 201 after NFKC.


def test_normalized_text_is_independently_checked_for_controls(monkeypatch):
    monkeypatch.setattr(formula_text.unicodedata, "normalize", lambda form, value: "Nb\x85")
    with pytest.raises(formula_text.FormulaTextQueryError, match="control"):
        formula_text.formula_text_pattern("Nb")
