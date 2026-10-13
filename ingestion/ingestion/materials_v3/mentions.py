"""High-specificity source mention cues, not adjudicated claims or scoring gold."""

import re

from .wire import source_catalog


NUMBER = r"[+\-−]?(?:\d+(?:\.\d*)?|\.\d+)"
LABEL = (
    r"(?:\bTc|T_?\{(?:\\rm\s*|\\mathrm\{)?c\}?\}|\bT_c)"
    r"(?:\^\{[^}]{1,20}\})?(?:\([^)]{1,24}\))?"
)
PATTERN = re.compile(
    rf"(?:{LABEL}\s*(?:=|<|>|≤|≥|~|≈|\\simeq|\\approx)*\s*"
    rf"|\b(?:onset(?:\s+Tc)?|zero(?:[\s-]+resistance)?(?:\s+Tc)?)"
    rf"(?:\s+(?:was|is|of|at|temperature))*\s*[:=~≈]?\s*"
    rf"|\b(?:critical|transition)\s+temperature\s+"
    rf"(?:as\s+high\s+as|of|is|was|around|about|approximately)?\s*[~≈]?\s*)"
    rf"{NUMBER}\s*(?:mK|K)\b",
    re.IGNORECASE,
)


def tc_mentions(blocks):
    rows, _ = source_catalog(blocks)
    return [
        {"ref": row["ref"], "raw_mention": match.group(), "status": "lexical_source_cue_not_gold"}
        for row in rows
        if row["block_role"] == "target"
        for match in PATTERN.finditer(row["text"])
    ]
