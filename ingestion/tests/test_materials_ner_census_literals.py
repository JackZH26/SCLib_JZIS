"""Original-coordinate literal addressing, including the retained 1.2 failure."""
import pytest

from ingestion.materials_ner.census.literals import resolve_literal
from ingestion.materials_ner.paper_coverage import literal_value_in_quote


@pytest.mark.parametrize('text,raw,original', [
    (r'$\Delta C/C_N\approx 1.2$ at $T_c$ at $P=1.21$~GPa', '1.2', '1.2'),
    ('Value 1.21, then 1.2.', '1.2', '1.2'),
    ('Value -1.2, then +1.2.', '-1.2', '-1.2'),
    ('Value −1.2, then −1.21.', '−1.2', '−1.2'),
    ('Value 1.2e-3, then 1.2e-30.', '1.2e-3', '1.2e-3'),
    ('Range 12–35 K.', '12–35 K', '12–35 K'),
    ('Ratio 2/3; value 2.3.', '2/3', '2/3'),
    (r'Fit $T^{1/4}$; not $T^{1/3}$.', r'$T^{1/4}$', r'$T^{1/4}$'),
    ('Before 5\r\n\t K after 15 K.', '5 K', '5\r\n\t K'),
    ('At zero\n temperature; 0 K elsewhere.', 'zero temperature', 'zero\n temperature'),
    ('Grains 5 μm; field 5 mT.', '5 μm', '5 μm'),
])
def test_whole_literal_maps_back_to_original_coordinates(text, raw, original):
    assert literal_value_in_quote(raw, text)
    a, z = resolve_literal(text, raw)
    assert text[a:z] == original


@pytest.mark.parametrize('text,raw', [
    ('Only 1.21.', '1.2'), ('Only 15 K.', '5 K'), ('Only -1.2.', '1.2'),
    ('Only −1.2.', '1.2'), ('Only +1.2.', '1.2'), ('Only 1.2e-3.', '1.2'),
    ('A preset value.', 'set'), ('Only 5mT.', '5'), ('Only 5 μm.', '5 um'),
    (r'Only $\frac{1}{4}$.', '1/4'), ('Only 1.2.', ''),
])
def test_clipping_or_normalization_does_not_create_a_literal(text, raw):
    assert not literal_value_in_quote(raw, text)
    with pytest.raises(ValueError, match='literal_not_in_locked_source'):
        resolve_literal(text, raw)


@pytest.mark.parametrize('text,raw', [('1.2 and 1.2 at 1.21.', '1.2'),
    ('5 K and 5\nK.', '5 K'), ('2/3 and 2/3.', '2/3'),
    ('1 1 1', '1 1'), ('0 K 0 K 0 K', '0 K 0 K')])
def test_repeated_complete_literals_remain_ambiguous(text, raw):
    with pytest.raises(ValueError, match='ambiguous_literal_locator'):
        resolve_literal(text, raw)
