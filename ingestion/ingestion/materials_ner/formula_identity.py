"""Negative lexical check only; a letter does not establish chemical identity."""
import re


def has_identity_token(raw):
    if raw is None:
        return True
    # Formatting commands are not elements, variables or a source acronym.
    # Keep their arguments verbatim, including isotope and variable notation.
    literal = re.sub(r'\\[A-Za-z]+\*?', '', raw)
    return any(character.isalpha() for character in literal)
