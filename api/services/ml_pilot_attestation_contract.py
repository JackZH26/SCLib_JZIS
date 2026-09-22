"""Immutable wording of a voluntary account declaration, not a legal signature."""

from hashlib import sha256

VERSION = "ml08-own-review-declaration/1.0.0"
TEXT = (
    "For an attestation, I confirm that the complete original documents identified "
    "in this preview contain my own completed review contributions, including all "
    "revisions, failures and unresolved cases, without substituted candidates. "
    "I take responsibility for those recorded assessments and their stated limitations. "
    "If I am the recorded conclusion author, I also endorse that exact conclusion "
    "and its field-specific recommendations. For a withdrawal, I withdraw my prior "
    "declaration identified in this preview, without erasing its history. "
    "This account declaration does not verify independent human identity, external "
    "review dates or source permissions, approve public release, establish collective "
    "pilot acceptance, or authorize machine-learning execution."
)
SHA256 = sha256(TEXT.encode("utf-8")).hexdigest()
