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

MAX_LENGTH = 100

# ``$``, ``_``, ``{``, ``}``, ``\``, ``%`` and the Unicode minus are
# all signs of incomplete LaTeX / typesetting cleanup. They never
# legitimately appear in a chemical formula.
_FORBIDDEN_CHARS = re.compile(r"[\$_{}\\−%]")

# Whole-word, case-insensitive English descriptors that signal NER
# extracted a sentence fragment instead of a formula. Curated from
# the 2026-05 audit; extend conservatively (false positives blacklist
# real compounds and are user-visible).
_BLACKLIST_PATTERN = re.compile(
    r"\b(interface|bilayer|trilayer|multilayer|monolayer|superlattice"
    r"|superlattices|homobilayer|homobilayers|heterostructure"
    r"|graphene|diamond|molecule|molecules|organic|compound|compounds"
    r"|system|systems|doped|undoped|intercalated|hybrid|twisted|valley"
    r"|bulk|ladder|mirror|surface|surfaces|nanoparticle|nanoparticles"
    r"|film|films|wire|wires|polycrystal|polycrystals|tube|tubes"
    r"|composition|compositions|cuprate(?!s?[A-Z0-9])"  # bare 'cuprate' but not 'cuprateXYZ' (rare)
    r"|underdoped|overdoped|optimal|optimally"
    r"|holes?|electrons?|cells?|samples?|layers?"
    r"|chiral|kagome|nanotube|nanotubes|nanowire|nanowires"
    # English element / chemistry names (Cat 1 from Gemini audit)
    r"|hydrogen|oxygen|nitrogen|sulfur|sulphur|fluorine|chlorine"
    r"|bromine|iodine|silicon|water"
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
# whose ``δ`` was lost during cleanup (``YBa2Cu3O7-``). Either way
# the formula is not in canonical form.
_TRAILING_CHARGE = re.compile(r"[A-Za-z0-9][+\-]$")

# Condition descriptors NER sometimes appends to a formula:
# ``(x = 0.3)``, ``(z = 0.05)``, ``with n = 2`` etc.
_CONDITION_PATTERN = re.compile(r"\(?\s*[xyzn]\s*=\s*[0-9]", re.IGNORECASE)

# A formula must start with an element symbol (uppercase letter) or
# an opening bracket. Allowing Greek prefixes covers organic SC
# polymorphs (κ, α, β, λ). Numbers / lowercase letters at position 0
# almost always mean NER scraped a sentence start.
_VALID_START = re.compile(r"^[A-ZΑ-Ωα-ωκλαβγδε(\[]")


def normalize_whitespace(raw: str) -> str:
    """Strip leading + trailing + interior whitespace.

    Chemical formulas don't contain spaces — ``Ba 2 Cu 3 O 7-δ`` is
    just ``Ba2Cu3O7-δ`` written by an LLM that thought the subscripts
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
    # Order matters: the more specific Gemini-audit categories run
    # last so a generic descriptive-word match takes precedence
    # (cleaner UX when a string trips both rules).
    if _SYSTEM_DESIGNATOR.match(s):
        return False, SYSTEM_DESIGNATOR
    if _PHASE_PREFIX.match(s):
        return False, PHASE_PREFIX
    if _TRAILING_CHARGE.search(s):
        return False, INCOMPLETE_FORMULA
    return True, None
