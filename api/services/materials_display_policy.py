"""Flag out-of-scope Tc assertions without rewriting their scientific values.

The 300 K ceiling is inclusive. Any explicit scalar or interval endpoint above
it suppresses the entire assertion, as does a strict lower bound of >300 K.
Pressure, source text, non-Tc properties, admission history and immutable source
exports are outside this presentation policy. Fixed SQL aliases match the
canonical Materials/timeline query, and filtering precedes counts/pagination.
"""
from collections.abc import Mapping
from decimal import Decimal

TC_DISPLAY_MAX_KELVIN = 300
TC_DISPLAY_EXCLUSION_FLAG = 'tc_above_300k'
TC_DISPLAY_EXCLUSION_SQL = """CASE WHEN (
    c.value_kelvin > 300 OR c.value_lower_kelvin > 300 OR c.value_upper_kelvin > 300
    OR (c.value_relation = 'gt' AND c.value_lower_kelvin >= 300)
) THEN 'tc_above_300k' ELSE NULL END"""
PUBLIC_TC_DISPLAY_WHERE = f'({TC_DISPLAY_EXCLUSION_SQL}) IS NULL'


def tc_display_exclusion(row: Mapping) -> str | None:
    """The same deterministic flag for audits and non-SQL projections."""
    for key in ('value_kelvin', 'value_lower_kelvin', 'value_upper_kelvin'):
        value = row.get(key)
        if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool) and value > TC_DISPLAY_MAX_KELVIN:
            return TC_DISPLAY_EXCLUSION_FLAG
    if row.get('value_relation') == 'gt' and row.get('value_lower_kelvin') == TC_DISPLAY_MAX_KELVIN:
        return TC_DISPLAY_EXCLUSION_FLAG
    return None
