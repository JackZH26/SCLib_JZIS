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
    r")\b",
    re.IGNORECASE,
)

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
    return True, None
