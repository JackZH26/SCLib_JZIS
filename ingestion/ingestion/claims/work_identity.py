"""Conservative work-level identity planning for SCLib papers.

Grouping uses only exact DOI, explicit ``related_paper_id`` links, exact arXiv
identity, and singleton fallback.  Titles and authors are retained as metadata
but are never used to auto-merge works.
"""

from __future__ import annotations

import re
import uuid
from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import date, datetime
from typing import Any
from urllib.parse import unquote

WORK_IDENTITY_VERSION = "conservative-work-identity/v1"
_WORK_NAMESPACE = uuid.UUID("3fa6bc5f-1d88-4e0c-86c0-b33d5ec2e041")

_DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$", re.IGNORECASE)
_ARXIV_NEW_RE = re.compile(r"^\d{4}\.\d{4,5}$")
_ARXIV_OLD_RE = re.compile(r"^[a-z][a-z0-9.-]+/\d{7}$", re.IGNORECASE)


class WorkIdentityConflict(ValueError):
    """A connected paper component contains incompatible persisted work IDs."""


class _DisjointSet:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def add(self, item: str) -> None:
        self.parent.setdefault(item, item)

    def find(self, item: str) -> str:
        self.add(item)
        parent = self.parent[item]
        if parent != item:
            self.parent[item] = self.find(parent)
        return self.parent[item]

    def union(self, left: str, right: str) -> None:
        root_left = self.find(left)
        root_right = self.find(right)
        if root_left == root_right:
            return
        # Lexical root selection keeps results independent of input order.
        low, high = sorted((root_left, root_right))
        self.parent[high] = low


def canonicalize_doi(value: Any) -> str | None:
    """Return a lowercase bare DOI, or ``None`` when it is not exact."""
    if value is None:
        return None
    text = unquote(str(value)).strip()
    if not text:
        return None
    lowered = text.lower()
    for prefix in ("doi:", "https://doi.org/", "http://doi.org/", "https://dx.doi.org/"):
        if lowered.startswith(prefix):
            text = text[len(prefix) :]
            break
    text = text.strip().rstrip(".,;").lower()
    return text if _DOI_RE.fullmatch(text) else None


def canonicalize_arxiv_id(value: Any) -> str | None:
    """Return a version-free arXiv identifier, including legacy categories."""
    if value is None:
        return None
    text = unquote(str(value)).strip()
    if not text:
        return None

    lowered = text.lower()
    for prefix in (
        "arxiv:",
        "https://arxiv.org/abs/",
        "http://arxiv.org/abs/",
        "https://arxiv.org/pdf/",
        "http://arxiv.org/pdf/",
    ):
        if lowered.startswith(prefix):
            text = text[len(prefix) :]
            break
    text = text.split("?", 1)[0].split("#", 1)[0]
    if text.lower().endswith(".pdf"):
        text = text[:-4]
    text = re.sub(r"v\d+$", "", text, flags=re.IGNORECASE).strip()
    lowered = text.lower()
    if _ARXIV_NEW_RE.fullmatch(lowered) or _ARXIV_OLD_RE.fullmatch(lowered):
        return lowered
    return None


def plan_work_identities(
    papers: Iterable[Mapping[str, Any]],
    *,
    existing_work_ids: Mapping[str, uuid.UUID | str] | None = None,
) -> dict[str, Any]:
    """Build deterministic ``works`` and ``paper_work_map`` payloads.

    ``existing_work_ids`` is optional incremental-run state keyed by paper ID.
    A component with exactly one persisted ID reuses it.  Multiple different
    persisted IDs raise :class:`WorkIdentityConflict`; the helper never
    silently merges already-established works.
    """
    rows: dict[str, dict[str, Any]] = {}
    for paper in papers:
        paper_id = _paper_id(paper)
        if not paper_id:
            raise ValueError("every paper must have a non-empty id")
        if paper_id in rows:
            raise ValueError(f"duplicate paper id: {paper_id}")
        rows[paper_id] = dict(paper)

    dsu = _DisjointSet()
    doi_groups: dict[str, list[str]] = defaultdict(list)
    arxiv_groups: dict[str, list[str]] = defaultdict(list)
    for paper_id, paper in rows.items():
        dsu.add(paper_id)
        doi = _paper_doi(paper_id, paper)
        if doi:
            doi_groups[doi].append(paper_id)
        arxiv_id = _paper_arxiv_id(paper_id, paper)
        if arxiv_id:
            arxiv_groups[arxiv_id].append(paper_id)

        related = _text(paper.get("related_paper_id"))
        if related:
            # Explicit relation links are authoritative even if the target is
            # outside this snapshot.  The virtual node stabilizes the anchor.
            dsu.union(paper_id, related)

    for paper_ids in doi_groups.values():
        first = paper_ids[0]
        for paper_id in paper_ids[1:]:
            dsu.union(first, paper_id)
    for paper_ids in arxiv_groups.values():
        first = paper_ids[0]
        for paper_id in paper_ids[1:]:
            dsu.union(first, paper_id)

    components: dict[str, set[str]] = defaultdict(set)
    for node in tuple(dsu.parent):
        components[dsu.find(node)].add(node)

    existing: dict[str, uuid.UUID] = {}
    for paper_id, raw_work_id in (existing_work_ids or {}).items():
        normalized_paper_id = str(paper_id).strip()
        if not normalized_paper_id:
            raise ValueError("existing work mappings require a non-empty paper ID")
        try:
            normalized_work_id = uuid.UUID(str(raw_work_id))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError(
                f"invalid persisted work ID for paper {normalized_paper_id!r}"
            ) from exc
        existing[normalized_paper_id] = normalized_work_id

    # A reviewed mapping already stored in the database is an authoritative
    # identity edge even if this snapshot no longer carries the original DOI
    # or related-paper metadata.  Reconnect all known members before building
    # components so one persisted work can never be emitted twice.
    persisted_groups: dict[uuid.UUID, list[str]] = defaultdict(list)
    for paper_id, work_id in existing.items():
        dsu.add(paper_id)
        persisted_groups[work_id].append(paper_id)
    for paper_ids in persisted_groups.values():
        first = paper_ids[0]
        for paper_id in paper_ids[1:]:
            dsu.union(first, paper_id)

    # Persisted mappings may have joined components, so rebuild the component
    # index after applying those edges.
    components = defaultdict(set)
    for node in tuple(dsu.parent):
        components[dsu.find(node)].add(node)

    works: list[dict[str, Any]] = []
    paper_maps: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    for members in sorted(components.values(), key=lambda group: sorted(group)):
        real_ids = sorted(member for member in members if member in rows)
        if not real_ids:
            continue
        component_rows = [rows[paper_id] for paper_id in real_ids]

        arxiv_ids = sorted(
            {
                arxiv_id
                for paper_id, paper in zip(real_ids, component_rows, strict=True)
                for arxiv_id in (_paper_arxiv_id(paper_id, paper),)
                if arxiv_id
            }
            | {
                arxiv_id
                for member in members
                for arxiv_id in (canonicalize_arxiv_id(member),)
                if arxiv_id
            }
        )
        dois = sorted(
            {
                doi
                for paper_id, paper in zip(real_ids, component_rows, strict=True)
                for doi in (_paper_doi(paper_id, paper),)
                if doi
            }
            | {
                doi
                for member in members
                for doi in (canonicalize_doi(_doi_from_paper_id(member)),)
                if doi
            }
        )

        # Prefer an arXiv anchor when present.  If a formal DOI version is
        # linked later, the deterministic ID remains based on the preprint
        # instead of changing merely because metadata became richer.
        if arxiv_ids:
            identity_key = f"arxiv:{arxiv_ids[0]}"
        elif dois:
            identity_key = f"doi:{dois[0]}"
        else:
            identity_key = f"singleton:{real_ids[0]}"

        # Include explicit related-paper targets that sit outside the current
        # snapshot. Their persisted mapping is the stable anchor when a new
        # source version arrives later.
        persisted = {existing[paper_id] for paper_id in members if paper_id in existing}
        if len(persisted) > 1:
            raise WorkIdentityConflict(
                f"component {real_ids!r} contains persisted work IDs {sorted(persisted)!r}"
            )
        work_id = next(iter(persisted)) if persisted else uuid.uuid5(_WORK_NAMESPACE, identity_key)

        canonical_row = _canonical_metadata_row(real_ids, rows)
        available_at = _component_available_at(component_rows)
        status = _component_status(component_rows)
        title = _text(canonical_row.get("title")) or _paper_id(canonical_row) or real_ids[0]
        external_related = {
            related
            for paper in component_rows
            for related in (_text(paper.get("related_paper_id")),)
            if related and related not in rows
        }
        review_required = len(dois) > 1 or len(arxiv_ids) > 1 or bool(external_related)
        if len(dois) > 1:
            warnings.append(
                {
                    "code": "multiple_dois_in_work_component",
                    "paper_id": real_ids[0],
                    "values": dois,
                }
            )
        if len(arxiv_ids) > 1:
            warnings.append(
                {
                    "code": "multiple_arxiv_ids_in_work_component",
                    "paper_id": real_ids[0],
                    "values": arxiv_ids,
                }
            )

        merge_signals = _component_signals(real_ids, rows)
        if sum(paper_id in existing for paper_id in real_ids) > 1:
            merge_signals = sorted({*merge_signals, "existing_mapping"})

        works.append(
            {
                "id": work_id,
                "canonical_title": title,
                "canonical_doi": dois[0] if dois else None,
                "canonical_arxiv_id": arxiv_ids[0] if arxiv_ids else None,
                "publication_status": status,
                "available_at": available_at,
                "identity_metadata": {
                    "resolver_version": WORK_IDENTITY_VERSION,
                    "identity_key": identity_key,
                    "paper_ids": real_ids,
                    "doi_aliases": dois,
                    "arxiv_aliases": arxiv_ids,
                    "auto_merge_signals": merge_signals,
                    "title_used_for_matching": False,
                },
            }
        )

        for paper_id in real_ids:
            paper = rows[paper_id]
            method = _match_method(
                paper_id,
                paper,
                len(real_ids),
                has_existing_mapping=paper_id in existing,
            )
            related = _text(paper.get("related_paper_id"))
            if related and related not in rows:
                warnings.append(
                    {
                        "code": "related_paper_outside_snapshot",
                        "paper_id": paper_id,
                        "related_paper_id": related,
                    }
                )
            paper_maps.append(
                {
                    "paper_id": paper_id,
                    "work_id": work_id,
                    "relation_type": _relation_type(paper_id, paper),
                    "match_method": method,
                    "match_score": 1.0,
                    "review_status": "pending" if review_required else "accepted",
                }
            )

    works.sort(key=lambda row: str(row["id"]))
    paper_maps.sort(key=lambda row: row["paper_id"])
    warnings.sort(key=lambda row: (row["code"], row["paper_id"]))
    return {
        "resolver_version": WORK_IDENTITY_VERSION,
        "works": works,
        "paper_work_map": paper_maps,
        "warnings": warnings,
    }


def _component_signals(real_ids: list[str], rows: Mapping[str, Mapping[str, Any]]) -> list[str]:
    signals: set[str] = set()
    doi_counts: dict[str, int] = defaultdict(int)
    for paper_id in real_ids:
        paper = rows[paper_id]
        doi = _paper_doi(paper_id, paper)
        if doi:
            doi_counts[doi] += 1
        if _text(paper.get("related_paper_id")):
            signals.add("related_paper")
    if any(count > 1 for count in doi_counts.values()):
        signals.add("exact_doi")
    arxiv_counts: dict[str, int] = defaultdict(int)
    for paper_id in real_ids:
        arxiv_id = _paper_arxiv_id(paper_id, rows[paper_id])
        if arxiv_id:
            arxiv_counts[arxiv_id] += 1
    if any(count > 1 for count in arxiv_counts.values()):
        signals.add("exact_arxiv")
    if len(real_ids) == 1 and not signals:
        signals.add("singleton")
    return sorted(signals)


def _match_method(
    paper_id: str,
    paper: Mapping[str, Any],
    component_size: int,
    *,
    has_existing_mapping: bool,
) -> str:
    if _paper_doi(paper_id, paper):
        return "exact_doi"
    if _text(paper.get("related_paper_id")):
        return "related_paper"
    if _paper_arxiv_id(paper_id, paper):
        return "exact_arxiv"
    if has_existing_mapping:
        # The Phase-1 import does not yet carry the original adjudication
        # method. ``manual`` is the only conservative, non-fabricated label.
        return "manual"
    # A multi-paper component can only have been formed by an exact DOI or an
    # explicit related-paper edge.  This fallback therefore represents an
    # incoming related edge, never a title/author metadata match.
    return "singleton" if component_size == 1 else "related_paper"


def _relation_type(paper_id: str, paper: Mapping[str, Any]) -> str:
    source = (_text(paper.get("source")) or "").lower()
    status = (_text(paper.get("status")) or "").lower()
    if source in {"supplement", "supplementary"}:
        return "supplement"
    if source in {"correction", "erratum", "corrigendum"} or status == "corrected":
        return "correction"
    if source == "arxiv" or canonicalize_arxiv_id(paper_id):
        return "preprint"
    if source == "aps" or _paper_doi(paper_id, paper):
        return "published_version"
    return "canonical_version"


def _canonical_metadata_row(
    real_ids: list[str],
    rows: Mapping[str, Mapping[str, Any]],
) -> Mapping[str, Any]:
    def rank(paper_id: str) -> tuple[int, date, str]:
        paper = rows[paper_id]
        source = (_text(paper.get("source")) or "").lower()
        published = _parse_date(paper.get("date_published"))
        submitted = _parse_date(paper.get("date_submitted"))
        when = published or submitted or date.max
        # Prefer formal published metadata, then earliest deterministic row.
        return (0 if source == "aps" or _paper_doi(paper_id, paper) else 1, when, paper_id)

    return rows[min(real_ids, key=rank)]


def _component_available_at(rows: list[Mapping[str, Any]]) -> date | None:
    values: list[date] = []
    for paper in rows:
        for key in ("available_at", "date_submitted", "date_published"):
            parsed = _parse_date(paper.get(key))
            if parsed:
                values.append(parsed)
    return min(values) if values else None


def _component_status(rows: list[Mapping[str, Any]]) -> str:
    statuses = {(_text(row.get("status")) or "").lower() for row in rows}
    if "retracted" in statuses:
        return "retracted"
    if "withdrawn" in statuses:
        return "withdrawn"
    if statuses & {"corrected", "correction", "erratum", "corrigendum"}:
        return "corrected"
    if statuses & {"published", "active", "accepted"}:
        return "active"
    return "unknown"


def _paper_id(paper: Mapping[str, Any]) -> str | None:
    return _text(paper.get("id")) or _text(paper.get("paper_id"))


def _paper_doi(paper_id: str, paper: Mapping[str, Any]) -> str | None:
    return canonicalize_doi(paper.get("doi")) or canonicalize_doi(_doi_from_paper_id(paper_id))


def _doi_from_paper_id(paper_id: str) -> str | None:
    lowered = paper_id.lower()
    if lowered.startswith("aps:"):
        return paper_id[4:]
    if lowered.startswith("doi:"):
        return paper_id[4:]
    return None


def _paper_arxiv_id(paper_id: str, paper: Mapping[str, Any]) -> str | None:
    return canonicalize_arxiv_id(paper.get("arxiv_id")) or canonicalize_arxiv_id(paper_id)


def _parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        try:
            return date.fromisoformat(text)
        except ValueError:
            return None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
