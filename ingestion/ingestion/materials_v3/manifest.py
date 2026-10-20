"""Frozen sampling gate. Availability and source rights are distinct facts."""

from __future__ import annotations

from collections import Counter, defaultdict

from .contract import digest

FAMILIES = {"high_pressure_hydride", "cuprate", "iron_based", "nickelate", "conventional"}
SPLITS = {"development": 2, "validation": 2, "blind_test": 6}


def source_captures(paper):
    """One work may have main text and separately captured supplementary sources."""
    supplements = paper.get("supplement_captures", [])
    if not isinstance(supplements, list) or len(supplements) > 20:
        raise ValueError("supplement_capture_count_outside_pilot_budget")
    main = {
        **paper,
        "capture_kind": "main",
        "source_sha256": paper.get("main_text_sha256"),
    }
    captures = [main]
    for supplement in supplements:
        if not isinstance(supplement, dict):
            raise ValueError("invalid_supplement_capture")
        # Permissions belong to the capture; they cannot be inherited from a
        # permissively licensed main text to a differently licensed attachment.
        captures.append(
            {
                **supplement,
                "paper_id": paper["paper_id"],
                "work_id": paper["work_id"],
                "capture_kind": "supplement",
            }
        )
    identities = [c.get("content_manifest_sha256") for c in captures]
    if any(not i for i in identities) or len(set(identities)) != len(identities):
        raise ValueError("source_capture_identity_missing_or_duplicated")
    return captures


def validate_manifest(manifest, *, freeze=False):
    errors = []
    papers = manifest.get("papers", [])
    if len(papers) != 50:
        errors.append("requires_50_works")
    works = [p.get("work_id") for p in papers]
    ids = [p.get("paper_id") for p in papers]
    if any(not p for p in ids) or len(set(ids)) != len(ids):
        errors.append("paper_identity_missing_or_duplicated")
    if any(not w for w in works) or len(set(works)) != len(works):
        errors.append("work_identity_missing_or_duplicated")
    groups = defaultdict(set)
    for p in papers:
        for field in (
            "paper_id",
            "work_id",
            "title",
            "doi_or_arxiv_id",
            "family",
            "study_dependency_group",
            "split",
        ):
            if not p.get(field):
                errors.append("missing_" + field)
        groups[p.get("study_dependency_group")].add(p.get("split"))
        if p.get("prior_prompt_example") and p.get("split") == "blind_test":
            errors.append("blind_prompt_leakage")
        if freeze:
            for field in (
                "source_version",
                "source_url",
                "source_license",
                "main_text_sha256",
                "content_manifest_sha256",
                "source_format",
                "coverage",
            ):
                if not p.get(field):
                    errors.append("freeze_missing_" + field)
            if p.get("transfer_allowed") is not True:
                errors.append("source_transfer_permission_unconfirmed")
            if p.get("supplement_status") not in {"included", "confirmed_absent"}:
                errors.append("supplement_scope_unconfirmed")
            try:
                captures = source_captures(p)
            except (ValueError, KeyError):
                errors.append("source_capture_manifest_invalid")
                captures = []
            if p.get("supplement_status") == "included" and len(captures) < 2:
                errors.append("included_supplement_capture_missing")
            if p.get("supplement_status") == "confirmed_absent" and len(captures) > 1:
                errors.append("supplement_absence_contradicts_captures")
            for capture in captures[1:]:
                for field in (
                    "source_version",
                    "source_url",
                    "source_license",
                    "source_sha256",
                    "content_manifest_sha256",
                    "source_format",
                    "coverage",
                ):
                    if not capture.get(field):
                        errors.append("freeze_missing_supplement_" + field)
                if capture.get("transfer_allowed") is not True:
                    errors.append("supplement_transfer_permission_unconfirmed")
            if p.get("work_identity_status") != "verified":
                errors.append("work_identity_not_verified")
            for field in ("dependency_group_review_status", "family_review_status"):
                if p.get(field) != "verified":
                    errors.append(field + "_unconfirmed")
    if any(len(splits) != 1 for splits in groups.values()):
        errors.append("dependency_group_split_leakage")
    for family in FAMILIES:
        rows = [p for p in papers if p.get("family") == family]
        if Counter(p.get("split") for p in rows) != Counter(SPLITS):
            errors.append("family_split_quota:" + family)
    if freeze:
        targets = {
            "multi_point_same_paper_material": 20,
            "table_header_and_footnote_binding": 15,
            "negative_or_inconclusive_sc_outcome": 5,
            "cited_and_primary_results": 10,
            "bounds_ranges_or_uncertainty": 10,
            "multiple_tc_criteria": 8,
            "calculated_results_with_method_parameters": 10,
            "critical_evidence_after_old_16k_prefix_or_section_eight": 5,
        }
        for tag, minimum in targets.items():
            if sum(tag in p.get("verified_case_tags", []) for p in papers) < minimum:
                errors.append("challenge_quota_unverified:" + tag)
        known = defaultdict(set)
        for p in papers:
            for material in p.get("verified_independent_materials", []):
                known[material].add(p["study_dependency_group"])
        if sum(len(groups) >= 2 for groups in known.values()) < 5:
            errors.append("cross_paper_independence_quota_unverified")
    return sorted(set(errors))


def freeze_manifest(manifest):
    errors = validate_manifest(manifest, freeze=True)
    if errors:
        raise ValueError("manifest_freeze_refused:" + ";".join(errors))
    body = {k: v for k, v in manifest.items() if k != "manifest_sha256"}
    # A source snapshot must remain identical on the coordinator and Mini.
    # Host-specific paths are an access index, never part of the frozen dataset.
    body["papers"] = []
    for paper in manifest["papers"]:
        public = {k: v for k, v in paper.items() if not k.startswith("private_")}
        public["supplement_captures"] = [
            {k: v for k, v in c.items() if not k.startswith("private_")}
            for c in paper.get("supplement_captures", [])
        ]
        body["papers"].append(public)
    body["status"] = "frozen"
    return {**body, "manifest_sha256": digest(body)}
