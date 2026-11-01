"""Conservative browsing families derived from source notation, not Tc or pairing.

This is a search taxonomy, not a structure determination or an exact-composition
parser. Unknown notation stays unclassified. See docs/materials-families.md.
"""
import hashlib
import re
import unicodedata

from services._composition.formula_enrichment import enrich_formula, _ELEMENTS

VERSION = 'materials-family/1'
FAMILIES = {
    'cuprate': 'Cuprates', 'iron_based': 'Iron pnictides & chalcogenides',
    'nickelate': 'Nickelate oxides', 'hydride': 'Hydrides', 'mgb2': 'MgB2 family',
    'heavy_fermion': 'Heavy-fermion hosts', 'kagome': 'Kagome hosts',
    'organic': 'Organic & molecular materials', 'fulleride': 'Fullerides',
    'borocarbide': 'Borocarbides', 'ruthenate': 'Ruthenate oxides',
    'bismuthate': 'Bismuthate oxides', 'bis2_layered': 'BiS2 / BiSe2 layered hosts',
    'oxide': 'Other oxides', 'boride': 'Other borides', 'carbide': 'Other carbides',
    'nitride': 'Nitrides', 'carbon': 'Carbon materials & intercalates', 'chalcogenide': 'Other chalcogenides',
    'pnictide': 'Other pnictides', 'elemental': 'Elemental materials',
    'intermetallic': 'Intermetallics & alloys', 'heterostructure': 'Heterostructures',
    'other_compound': 'Other compounds', 'unclassified': 'Unclassified',
}
FAMILY_SQL = """CASE WHEN
    m.material_semantics->'family_classification'->>'version'='materials-family/1'
    AND m.material_semantics->'family_classification'->>'family'=m.family
    AND m.material_semantics->'family_classification'->>'formula_sha256'=encode(sha256(convert_to(m.formula,'UTF8')),'hex')
    AND m.family IN (""" + ','.join("'"+x+"'" for x in FAMILIES) + ") THEN m.family ELSE 'unclassified' END"
# Exact documented hosts only: no inference from the presence of Ce/U/Pu.
HEAVY_HOSTS = frozenset(('CeCu2Si2 CeCu2Ge2 CeCoIn5 CeIrIn5 CeRhIn5 CeIn3 '
    'CePd2Si2 CePt3Si CeIrSi3 CeRhSi3 CeRhGe3 CeCoGe3 CeNiGe3 '
    'UBe13 UPt3 URu2Si2 UPd2Al3 UNi2Al3 UGe2 URhGe UCoGe UTe2 '
    'PuCoGa5 PuRhGa5 PuCoIn5 NpPd5Al2 PrOs4Sb12').split())
KAGOME_HOSTS = frozenset(('KV3Sb5 RbV3Sb5 CsV3Sb5 CsTi3Bi5 RbTi3Bi5 LaRu3Si2').split())
MOLECULAR = re.compile(r'BEDT-TTF|BEDSe-TTF|BETS|TMTSF|TMTTF|ET\)')
ALKALI = {'Li', 'Na', 'K', 'Rb', 'Cs'}
RARE_EARTH = set('La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Y Sc'.split())
NONMETAL = set('H B C N O F Si P S Cl Ge As Se Br Sb Te I At He Ne Ar Kr Xe Rn'.split())
ELEMENT_TOKEN = re.compile('|'.join(sorted(_ELEMENTS, key=lambda x: (-len(x), x))))


def notation(raw):
    """Strip supported typography only; never fill variables or expand macros."""
    value = unicodedata.normalize('NFKC', raw).replace('−', '-').replace('⋅', '·')
    if len(value) > 500:
        return None, 'unresolved_notation'
    # Balanced braces are essential before removing TeX grouping.
    depth = 0
    for c in value:
        depth += (c == '{') - (c == '}')
        if depth < 0:
            return None, 'unbalanced_notation'
    if depth:
        return None, 'unbalanced_notation'
    value = re.sub(r'\\(?:mathrm|textrm|mathbf|mathit|text|mbox|ce)(?=\s*\{)', '', value)
    value = re.sub(r'\\(?:rm|it|bf)(?![A-Za-z])', '', value)
    for name, glyph in {'delta': 'δ', 'Delta': 'Δ', 'alpha': 'α', 'beta': 'β',
                        'gamma': 'γ', 'kappa': 'κ', 'epsilon': 'ε', 'cdot': '·'}.items():
        value = re.sub(r'\\'+name+r'(?![A-Za-z])', glyph, value)
    value = re.sub(r'\\[,;! ]', '', value)
    value = re.sub(r'\\[()\[\]]', '', value)
    if '\\' in value:
        return None, 'unresolved_macro'
    # Superscript isotope/charge notation is retained for specialist resolution.
    if '^' in value or any(c in raw for c in '⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻'):
        return None, 'isotope_or_charge_notation'
    value = re.sub(r'[\s${}_]', '', value)
    return value, None


def classify_material_family(raw):
    """Return an auditable result for every string, including unknown inputs."""
    formula, issue = notation(raw)
    def result(family, rule, status='unresolved'):
        return dict(version=VERSION, family=family, rule=rule,
            formula_sha256=hashlib.sha256(raw.encode()).hexdigest(),
            basis='derived_from_reported_formula', formula_status=status)
    if issue:
        return result('unclassified', issue)
    if re.match(r'^(?:SC|NSC|sample)\s', raw):
        return result('unclassified', 'descriptive_prefix', 'unresolved')
    if MOLECULAR.search(formula):
        return result('organic', 'recognized_molecular_donor', 'molecular_notation')
    # Common aliases support browsing but never certify numeric composition.
    if re.fullmatch(r'(?:(?:YBCO|BSCCO|LSCO|LBCO|LCCO|NCCO|PCCO)[0-9.]*|Bi-?22(?:01|12|23)|Tl-?22(?:01|12|23)|Hg-?12(?:01|12|23))', formula):
        return result('cuprate', 'cuprate_alias', 'shorthand')
    if formula in {'graphite', 'graphene', 'diamond', 'boron-dopeddiamond'}:
        return result('carbon', 'carbon_material_name', 'shorthand')
    # Polytype prefixes are useful identity information; ignore only for family.
    formula = re.sub(r'^(?:(?:1T|2H|3R|4Hb|6R|Td|α|β|γ|κ)-)', '', formula)
    if formula in _ELEMENTS:
        return result('elemental', 'single_element', 'exact')
    parsed = enrich_formula(formula)
    status = parsed['composition_status']
    if '/' in formula and re.search(r'/[A-Z(]', formula):
        parts = formula.split('/')
        if all(p in _ELEMENTS or enrich_formula(p)['composition_status'] in {'exact', 'variable'} for p in parts):
            return result('heterostructure', 'explicit_interface', 'interface')
        return result('unclassified', 'unresolved_interface', 'unresolved')
    # Validate every token even for variable formulas (no prose/unknown elements).
    tokens = ELEMENT_TOKEN.findall(formula)
    rest = ELEMENT_TOKEN.sub('', formula)
    if not tokens or any(t not in _ELEMENTS for t in tokens) or re.search(r'[^0-9xyzδΔε.()+\-/,·\[\]]', rest):
        return result('unclassified', 'unresolved_formula', 'unresolved')
    if status == 'invalid':
        # The exact-composition parser deliberately rejects some valid symbolic
        # site occupancies. Recognize their elements without numeric features.
        if re.search(r'[xyzδΔε]', rest) and formula.count('(') == formula.count(')') and formula.count('[') == formula.count(']'):
            status = 'variable'
        else:
            return result('unclassified', 'unresolved_formula', 'unresolved')
    e = set(tokens)
    if formula in HEAVY_HOSTS:
        return result('heavy_fermion', 'documented_heavy_fermion_host', status)
    if formula in KAGOME_HOSTS:
        return result('kagome', 'documented_kagome_host', status)
    if re.fullmatch(r'(?:\(NH3\)[0-9.x-]*)?(?:(?:Li|Na|K|Rb|Cs)[0-9.x-]*)+C(?:60|70)', formula):
        return result('fulleride', 'alkali_fulleride', status)
    if len(e) == 1:
        return result('elemental', 'single_element', status)
    if formula == 'MgB2' or re.fullmatch(r'Mg(?:1-xAlx)?\(B(?:1-xCx|[0-9.]+C[0-9.]+)\)2|MgB(?:2-xCx|1\.8C0\.2)', formula):
        return result('mgb2', 'mgb2_host', status)
    if {'Cu', 'O'} <= e and e & (RARE_EARTH | {'Sr', 'Ba', 'Ca', 'Bi', 'Tl', 'Hg'}):
        return result('cuprate', 'copper_oxide_host', status)
    if 'Fe' in e and e & {'As', 'P', 'S', 'Se', 'Te'} and 'Cu' not in e and ('C' not in e or bool(re.search(r'Fe[0-9.xyz+\-]*(?:Se|Te)', formula))):
        return result('iron_based', 'iron_pnictide_or_chalcogenide', status)
    if 'H' in e and not e & {'O', 'C', 'N', 'F', 'Cl', 'Br', 'I'}:
        return result('hydride', 'hydrogen_compound', status)
    if {'Ni', 'O'} <= e and e & (RARE_EARTH | {'Sr', 'Ca', 'Ba'}) and not e & {'As', 'P', 'S', 'Se', 'Te'}:
        return result('nickelate', 'nickel_oxide_host', status)
    if {'Ru', 'O'} <= e and e & {'Sr', 'Ca', 'Ba'}:
        return result('ruthenate', 'ruthenium_oxide_host', status)
    if {'Bi', 'O'} <= e and e & {'Ba', 'K', 'Rb', 'Sr'} and not e & {'S', 'Se', 'Te'}:
        return result('bismuthate', 'bismuth_oxide_host', status)
    if 'Bi' in e and e & {'S', 'Se'} and e & (RARE_EARTH | {'Sr'}) and re.search(r'Bi(?:S|Se)(?:2|[0-9.]+)', formula):
        return result('bis2_layered', 'bismuth_dichalcogenide_host', status)
    if {'B', 'C', 'Ni'} <= e and not e & {'O', 'N'}:
        return result('borocarbide', 'nickel_borocarbide', status)
    if formula in {'CaC6', 'C6Ca', 'YbC6', 'C6Yb', 'LiC6', 'KC8'}:
        return result('carbon', 'graphite_intercalate', status)
    if {'C', 'H'} <= e:
        if re.search(r'TiSe2', formula):
            return result('chalcogenide', 'intercalated_tise2_host', status)
        if re.search(r'C(?:[6-9]|[1-9]\d+)H', formula):
            return result('organic', 'molecular_carbon_hydrogen_composition', status)
        return result('other_compound', 'mixed_molecular_composition', status)
    for element, family in [('O','oxide'), ('N','nitride'), ('C','carbide'), ('B','boride')]:
        if element in e:
            return result(family, 'composition_group', status)
    if e & {'S', 'Se', 'Te'}:
        return result('chalcogenide', 'composition_group', status)
    if e & {'P', 'As'}:
        return result('pnictide', 'composition_group', status)
    if not e & (NONMETAL - {'Si', 'Ge', 'Sb'}):
        return result('intermetallic', 'metal_or_metalloid_compound', status)
    return result('other_compound', 'other_resolved_composition', status)


def current_family(formula, family, semantics):
    """Only versioned labels tied to the unchanged formula enter the new UI."""
    provenance = (semantics or {}).get('family_classification', {})
    if (provenance.get('version') == VERSION and provenance.get('family') == family
        and family in FAMILIES and provenance.get('formula_sha256') == hashlib.sha256(formula.encode()).hexdigest()):
        return family
    return 'unclassified'
