import pytest

from ingestion.materials_ner import field_candidates as fields
from ingestion.materials_ner.field_candidates import active_ranges, active_span_ranges, text_candidates, select_name


def test_comments_split_contiguous_original_clauses_and_keep_crlf():
    text = '%Rejected electric-field conclusion.\r\n\r\nKnight shift has no significant change.\r\n'
    values = text_candidates(text, 0, len(text))
    assert values and all('Rejected' not in x['quote'] for x in values)
    assert any(x['quote'] == 'Knight shift has no significant change.' for x in values)
    assert all(text[x['start_char']:x['end_char']] == x['quote'] for x in values)


def test_span_starting_inside_comment_does_not_reactivate_it():
    text = '% ' + 'old result ' * 100 + '\nActive result.'
    a = 400
    values = text_candidates(text, a, len(text))
    assert [x['quote'] for x in values] == ['Active result.']


def test_no_bridge_across_inline_comment():
    text = 'Bound 50 % discarded text\r\nK is printed later.'
    pieces = [text[a:b] for a, b in active_ranges(text)]
    assert pieces == ['Bound 50 ', '\r\nK is printed later.']
    assert not any('50' in c['quote'] and 'K' in c['quote'] for c in text_candidates(text, 0, len(text)))


def test_percent_escape_parity():
    text = 'Value 14.5\\% retained.\\\\% removed\nNext.'
    pieces = [text[a:b] for a, b in active_ranges(text)]
    assert pieces == ['Value 14.5\\% retained.\\\\', '\nNext.']


def test_plain_text_percent_is_not_a_comment():
    text = 'Value 14.5% of the comparison.'
    assert active_ranges(text, tex=False) == [(0, len(text))]


def test_range_bounds_are_checked():
    with pytest.raises(ValueError, match='out_of_bounds'):
        active_span_ranges('x', -1, 1)


def test_math_cannot_cross_comment_boundary():
    text = '$K % old expression\n(T)$ and $K_0$.'
    values = text_candidates(text, 0, len(text))
    assert [x['quote'] for x in values if x['kind'] == 'math'] == ['$K_0$']


@pytest.mark.parametrize('name,unit', [(r'$\%$', '%'), ('MHz', 'MHz'), ('K', 'K'), ('percent', None)])
def test_unit_only_name_rejected(name, unit):
    with pytest.raises(ValueError, match='unit_only_quantity_name'):
        select_name(dict(quote='The ' + name + ' value.', start_char=100, end_char=200), name, unit=unit)


def test_literal_prose_name_has_exact_original_coordinates():
    quote = 'This gives a structural collapse around 80 K.'
    chosen = select_name(dict(quote=quote, start_char=100, end_char=100 + len(quote)), 'structural collapse', unit='K')
    assert chosen['quote'] == 'structural collapse'
    assert chosen['start_char'] == 113 and chosen['end_char'] == 132
    assert chosen['context']['quote'] == quote


def test_symbol_ambiguous_with_unit_allowed_when_different_from_actual_unit():
    chosen = select_name(dict(quote='$K$ is measured in percent.', start_char=0, end_char=27), '$K$', unit='%')
    assert chosen['quote'] == '$K$'


@pytest.mark.parametrize('literal', ['Tc', 'invented name', ''])
def test_name_must_be_nonempty_exact_and_unique(literal):
    with pytest.raises(ValueError):
        select_name(dict(quote='Tc and Tc are distinct here.', start_char=0, end_char=28), literal, unit='K')


def test_repeated_source_scans_do_not_share_mutable_ranges_or_reactivate_comments():
    text = 'Tc=4 K % abandoned Tc=90 K\nnext value 5 K'
    original = active_ranges(text)
    altered = active_ranges(text)
    altered.clear()
    assert active_ranges(text) == original
    assert 'abandoned' not in ''.join(text[a:b] for a,b in active_ranges(text))
    # The same bytes in non-TeX mode retain the percent text; changing the
    # actual source to an escaped percent also requires distinct coordinates.
    assert active_ranges(text, tex=False) == [(0,len(text))]
    changed = text.replace('%',r'\%')
    assert active_ranges(changed) == [(0,len(changed))]
    assert active_ranges(text) == original


@pytest.fixture
def empty_lexical_cache():
    fields._cached_active_ranges.cache_clear()
    with fields._math_lock:
        fields._math_cache.clear()
    yield
    fields._cached_active_ranges.cache_clear()
    with fields._math_lock:
        fields._math_cache.clear()


@pytest.mark.parametrize('parity', [False, True])
@pytest.mark.parametrize('tex', [False, True])
def test_indexed_math_returns_only_complete_original_tokens(parity, tex, empty_lexical_cache):
    text = 'Before $λ_ab$ then $T_c$ after.'
    first = text.index('$λ_ab$'); last = first + len('$λ_ab$')
    def math(start, end):
        return [v for v in text_candidates(text, start, end, tex=tex, dollar_escape_parity=parity)
                if v['kind'] == 'math']
    assert math(first, last) == [dict(kind='math', start_char=first, end_char=last, quote='$λ_ab$')]
    assert math(first+1, last) == []
    assert math(first, last-1) == []
    assert math(last, last) == []
    assert math(last, len(text))[0]['quote'] == '$T_c$'


def test_math_index_does_not_share_mutable_candidates_or_mode_keys(empty_lexical_cache):
    text = r'\\$λ$ % $discarded$' + '\r\n$T_c$'
    legacy = text_candidates(text, 0, len(text))
    parity = text_candidates(text, 0, len(text), dollar_escape_parity=True)
    assert [v['quote'] for v in legacy if v['kind'] == 'math'] == []
    assert [v['quote'] for v in parity if v['kind'] == 'math'] == ['$λ$', '$T_c$']
    assert any(v['quote'] == '$discarded$' for v in text_candidates(
        text, 0, len(text), tex=False, dollar_escape_parity=True))
    corrupted = text_candidates(text, 0, len(text), dollar_escape_parity=True)
    corrupted[-1]['quote'] = 'not source text'; corrupted.clear()
    assert text_candidates(text, 0, len(text), dollar_escape_parity=True) == parity
    changed = text.replace('λ', 'αβ')
    values = text_candidates(changed, 0, len(changed), dollar_escape_parity=True)
    assert [v['quote'] for v in values if v['kind'] == 'math'] == ['$αβ$', '$T_c$']
    assert all(changed[v['start_char']:v['end_char']] == v['quote'] for v in values)


@pytest.mark.parametrize('limit,value', [('_MAX_SOURCE_CHARS', 4), ('_MAX_MATH_RANGES', 1)])
def test_cache_bypass_keeps_all_source_candidates(limit, value, monkeypatch, empty_lexical_cache):
    text = '$a$ and $b$ and $c$'
    expected = text_candidates(text, 0, len(text))
    fields._math_cache.clear()
    monkeypatch.setattr(fields, limit, value)
    assert text_candidates(text, 0, len(text)) == expected
    assert not fields._math_cache


def test_lru_eviction_and_empty_index_are_bounded_without_changing_results(monkeypatch, empty_lexical_cache):
    monkeypatch.setattr(fields, '_MAX_MATH_ENTRIES', 2)
    first = '$λ$'
    expected = text_candidates(first, 0, len(first))
    for text in ['No math here.', '$T_c$']:
        text_candidates(text, 0, len(text))
    assert len(fields._math_cache) == 2
    assert ('No math here.', True, False) in fields._math_cache
    assert (first, True, False) not in fields._math_cache
    assert text_candidates(first, 0, len(first)) == expected
    assert len(fields._math_cache) == 2


def test_concurrent_cache_reads_and_eviction_preserve_exact_source(empty_lexical_cache):
    from concurrent.futures import ThreadPoolExecutor
    texts = [f'$λ_{i}$ % $discarded$\r\n$T_c$' for i in range(16)]
    expected = {text: text_candidates(text, 0, len(text)) for text in texts}
    with ThreadPoolExecutor(max_workers=4) as pool:
        actual = list(pool.map(lambda text: text_candidates(text, 0, len(text)), texts*4))
    assert actual == [expected[text] for text in texts*4]
    assert len(fields._math_cache) <= fields._MAX_MATH_ENTRIES
