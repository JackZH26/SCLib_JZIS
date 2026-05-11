"""Formula naming validator — gate-kept by NER post-process + aggregator.

A *valid* SC material formula must be a chemical-formula string, not a
description. Rules check element-symbol structure, forbid LaTeX +
English-prose markers, and trim whitespace.

The same rules are mirrored as Postgres regex in alembic 0020 and as
a periodic audit query in api/main.py. Keep all three in lockstep
when extending — see the unit-test pattern in
``ingestion/tests/test_formula_validator.py``.

Two public entry points:

* ``normalize_whitespace(raw)`` — drop interior whitespace; chemical
  formulas never contain it, NER routinely leaks it.
* ``validate_formula(raw)`` → ``(ok, reason)``. ``reason`` is one of
  the constants below when the formula is rejected; ``None`` when ok.
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Reject reasons — used both as return values and as
# materials.review_reason markers when the migration / lifespan audit
# tags a row that slipped past these checks.
# ---------------------------------------------------------------------------
EMPTY                 = "empty"
TOO_LONG              = "too_long"
NO_UPPERCASE          = "no_uppercase_element"
FORBIDDEN_CHAR        = "forbidden_char"
DESCRIPTIVE_WORD      = "descriptive_word"
CONDITION_DESCRIPTOR  = "condition_descriptor"
INVALID_START         = "invalid_start"

# Gemini-audit categories (2026-05-08 audit). Each is a distinct
# named-rule violation so admins can filter / un-flag per-category.
SYSTEM_DESIGNATOR     = "system_designator_not_compound"   # "Sr-Ru-O"
PHASE_PREFIX          = "phase_prefix_in_formula"          # "Fm-3m-CeH10"
INCOMPLETE_FORMULA    = "incomplete_or_charged_formula"    # "Al45-", "YBa2Cu3O7-"
ENGLISH_ELEMENT_NAME  = "english_element_name"             # "Oxygen", "Sulfur"

# 2026-05-11 tightening — new rejection categories from DB garbage survey
LITERAL_PLACEHOLDER   = "literal_placeholder"              # "None", "unknown"
SINGLE_ELEMENT        = "single_element_symbol"            # "H", "C", "V"
CONCATENATED_PROSE    = "concatenated_prose"                # >10 consecutive lowercase
TRADE_NAME            = "trade_name_not_compound"           # "HOPG", "Grafoil"
GENERIC_FAMILY_NAME   = "generic_family_name"               # "cuprates", "ironpnictides"

MAX_LENGTH = 100


# ===================================================================
# NEW: Literal placeholders — NER sometimes emits these verbatim
# ===================================================================
_PLACEHOLDERS = frozenset({
    "none", "unknown", "n/a", "na", "null", "tbd", "-", "?", "??",
})


# ===================================================================
# NEW: Single bare uppercase letter = element symbol, not a compound.
# V, C, H, S, W, Y, P, B alone are too ambiguous for a material entry.
# ===================================================================
_SINGLE_ELEMENT = re.compile(r"^[A-Z]$")


# ===================================================================
# NEW: Trade names / lab-jargon acronyms that aren't chemical formulas
# ===================================================================
_TRADE_NAMES = frozenset(name.lower() for name in {
    "HOPG", "Grafoil", "Papyex", "Grokene", "SWNTrope", "FGG",
    # Carbon nanotube acronyms
    "SWNT", "SWCNT", "MWNT", "MWCNT", "DWNT", "DWCNT", "CNT",
    # Graphene-stacking abbreviations
    "tBLG", "BLG", "MLG", "SLG",
    # Other jargon
    "3DTI", "2DEG",
})


# ===================================================================
# NEW: Generic family names that aren't formulas
# ===================================================================
_GENERIC_FAMILY = re.compile(
    r"^(cuprates?|iron-?pnictides?|copper-?oxides?"
    r"|pnictides?|chalcogenides?|borocarbides?"
    r"|heavy-?fermions?|cuprate-?superconductors?"
    r"|high-?Tc-?cuprate(?:material)?s?"
    r"|FeAs-?based-?materials?"
    r"|214systems?)$",
    re.IGNORECASE,
)


# ===================================================================
# NEW: Long consecutive lowercase run → concatenated English prose.
# Real chemical formulas alternate uppercase element symbols (1-2 char)
# with digits; 10+ consecutive lowercase never occurs in a valid
# formula. Catches: "magicangletwistedbilayergraphene",
# "neutronsuperfluidity", "copperoxides", "boron-dopeddiamond", etc.
# ===================================================================
_LONG_LOWERCASE_RUN = re.compile(r"[a-z]{10,}")


# ===================================================================
# LaTeX / typesetting characters — ``$``, ``_``, ``{``, ``}``, ``\``,
# ``%`` and the Unicode minus never appear in chemical formulas.
# ===================================================================
_FORBIDDEN_CHARS = re.compile(r"[\$_{}\\−%]")


# ===================================================================
# Whole-word English descriptors + element names.
# Curated from the 2026-05 DB garbage survey; extend conservatively.
# ===================================================================
_BLACKLIST_PATTERN = re.compile(
    r"\b("
    # ---- Structural / morphological descriptors ----
    r"interface|bilayer|trilayer|multilayer|monolayer|superlattice"
    r"|superlattices|homobilayer|homobilayers|heterostructure"
    r"|graphene|graphite|diamond|molecule|molecules|organic|compound|compounds"
    r"|system|systems|doped|undoped|intercalated|hybrid|twisted|valley"
    r"|bulk|ladder|mirror|surface|surfaces|nanoparticle|nanoparticles"
    r"|film|films|wire|wires|polycrystal|polycrystals|tube|tubes"
    r"|composition|compositions|cuprate(?!s?[A-Z0-9])"
    r"|underdoped|overdoped|optimal|optimally"
    r"|holes?|electrons?|cells?|samples?|layers?"
    r"|chiral|kagome|nanotube|nanotubes|nanowire|nanowires"
    # 2026-05-11 additions — more descriptors from DB audit
    r"|rhombohedral|borophene|phosphorene|silicene|stanene|germanene"
    r"|amorphous|granular|polycrystalline|epitaxial"
    r"|superconductors?|superfluidity|superfluid"
    r"|magic-?angle|flat-?band|quantum-?wells?"
    r"|quasicrystal|quasicrystals|proximitized"
    r"|stacked|capping|eutectic"
    r"|materials?|based"  # bare "materials", "material", "based"

    # ---- English element / chemistry names ----
    # Non-metals (original)
    r"|hydrogen|oxygen|nitrogen|sulfur|sulphur|fluorine|chlorine"
    r"|bromine|iodine|silicon|water"
    # Non-metals (2026-05-11 additions)
    r"|helium|neon|argon|krypton|xenon|radon"
    r"|carbon|boron|phosphorus|arsenic|antimony"
    r"|germanium|selenium|tellurium"
    # Metals — alkali / alkaline earth
    r"|lithium|beryllium|sodium|potassium|rubidium"
    r"|cesium|caesium|magnesium|calcium|strontium|barium"
    # Metals — transition metals
    r"|titanium|vanadium|chromium|manganese|iron|cobalt|nickel"
    r"|copper|zinc|zirconium|niobium|molybdenum|technetium"
    r"|ruthenium|rhodium|palladium|silver|cadmium"
    r"|hafnium|tantalum|tungsten|rhenium|osmium|iridium"
    r"|platinum|gold|mercury"
    # Metals — post-transition / other
    r"|aluminum|aluminium|gallium|indium|thallium|lead|bismuth"
    # Metals — rare earth / actinides
    r"|lanthanum|cerium|uranium|thorium|plutonium"
    # NOTE: "tin" intentionally excluded — \btin\b matches "TiN"
    #        (titanium nitride, 53 papers, legitimate SC).

    # ---- Compound-type suffixes ----
    r"|hydride|hydrides|oxide|oxides|sulfide|sulfides|selenide|selenides"
    r"|telluride|tellurides|arsenide|arsenides|phosphide|phosphides"
    r"|nitride|nitrides|carbide|carbides|silicide|silicides"
    r"|fluoride|chloride|bromide|iodide"
    r")\b",
    re.IGNORECASE,
)


# Cat 2B: ``Sr-Ru-O`` style. Element symbols separated by hyphens with
# no digits — represents a phase diagram / compositional family, not
# a specific compound.
_SYSTEM_DESIGNATOR = re.compile(r"^([A-Z][a-z]?-){2,}[A-Z][a-z]?$")

# Cat 3: space-group prefix attached. Common groups in cuprate /
# hydride papers; extend if new ones surface.
_PHASE_PREFIX = re.compile(
    r"^(Fd-?3m|Fm-?3m|Im-?3m|Pm-?3m|Pnma|P6_?3?/?mmc?|P6/mmm"
    r"|R-?3m|R-?3c|I4/mmm|I4/mcm|Pn-?3m|P6_?3mc"
    r"|C2/m|Cmcm|P-?1|P21/c|P-43m|P4/nmm|Pm-3n)-"
)

# Cat 4: trailing ``+`` or ``-`` immediately after a letter / digit —
# either a charged cluster (``Al47-``) or a stoichiometry suffix
# whose ``delta`` was lost during cleanup (``YBa2Cu3O7-``). Either way
# the formula is not in canonical form.
_TRAILING_CHARGE = re.compile(r"[A-Za-z0-9][+\-]$")

# Condition descriptors NER sometimes appends to a formula:
# ``(x = 0.3)``, ``(z = 0.05)``, ``with n = 2`` etc.
_CONDITION_PATTERN = re.compile(r"\(?\s*[xyzn]\s*=\s*[0-9]", re.IGNORECASE)

# A formula must start with an element symbol (uppercase letter) or
# an opening bracket. Allowing Greek prefixes covers organic SC
# polymorphs (kappa, alpha, beta, lambda). Numbers / lowercase letters at
# position 0 almost always mean NER scraped a sentence start.
_VALID_START = re.compile(r"^[A-ZΑ-ωκλαβγδε(\[]")


def normalize_whitespace(raw: str) -> str:
    """Strip leading + trailing + interior whitespace.

    Chemical formulas don't contain spaces — ``Ba 2 Cu 3 O 7-delta`` is
    just ``Ba2Cu3O7-delta`` written by an LLM that thought the subscripts
    were separate tokens. Collapse all whitespace.
    """
    if not isinstance(raw, str):
        return raw
    return re.sub(r"\s+", "", raw.strip())


def validate_formula(raw: str) -> tuple[bool, str | None]:
    """Return ``(ok, reason)``.

    ``reason`` is ``None`` when the formula passes. Otherwise it's one
    of the module-level constants above so callers can store it as
    ``materials.review_reason`` or report it in audit logs.
    """
    if not isinstance(raw, str):
        return False, EMPTY
    s = raw.strip()
    if not s:
        return False, EMPTY

    # ------ Fast exact-match rejections (before any regex) ------
    if s.lower() in _PLACEHOLDERS:
        return False, LITERAL_PLACEHOLDER
    if s.lower() in _TRADE_NAMES:
        return False, TRADE_NAME
    if _SINGLE_ELEMENT.match(s):
        return False, SINGLE_ELEMENT
    if _GENERIC_FAMILY.match(s):
        return False, GENERIC_FAMILY_NAME

    # ------ Structural checks ------
    if len(s) > MAX_LENGTH:
        return False, TOO_LONG
    if not re.search(r"[A-Z]", s):
        return False, NO_UPPERCASE
    if _FORBIDDEN_CHARS.search(s):
        return False, FORBIDDEN_CHAR
    if _BLACKLIST_PATTERN.search(s):
        return False, DESCRIPTIVE_WORD
    if _CONDITION_PATTERN.search(s):
        return False, CONDITION_DESCRIPTOR
    if not _VALID_START.match(s):
        return False, INVALID_START

    # ------ Concatenated-prose catch-all ------
    # Fires AFTER the blacklist so individual descriptive words get
    # the more specific DESCRIPTIVE_WORD tag. This catches the long-
    # tail of NER concatenations like "boron-dopeddiamond",
    # "rhombohedraltetralayergraphene", etc.
    if _LONG_LOWERCASE_RUN.search(s):
        return False, CONCATENATED_PROSE

    # ------ More-specific Gemini-audit categories (last) ------
    if _SYSTEM_DESIGNATOR.match(s):
        return False, SYSTEM_DESIGNATOR
    if _PHASE_PREFIX.match(s):
        return False, PHASE_PREFIX
    if _TRAILING_CHARGE.search(s):
        return False, INCOMPLETE_FORMULA
    return True, None
