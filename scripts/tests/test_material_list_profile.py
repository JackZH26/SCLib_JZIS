"""Offline profile contracts, with no API imports or service connections."""
from __future__ import annotations

import pytest

from scripts import profile_material_list as profile


@pytest.mark.parametrize("header", (
    'materials_path;desc="page_hit", total;dur=1.000, total;dur=2.000',
    'materials_path;desc="paper-user-input", total;dur=1.000',
    'materials_path;desc="scan", scope;dur=20.000, total;dur=10.000',
    'materials_path;desc="scan", query_user_input;dur=1.000, total;dur=10.000',
    'materials_path;desc="scan", total;dur=NaN',
    'materials_path;desc="scan", total;dur=-1.000',
    "x" * 2049,
))
def test_invalid_timing_never_becomes_a_stage_measurement(header):
    assert profile.parse_timing(header) == {"status": "invalid"}


def test_missing_header_is_not_zero_server_latency():
    assert profile.parse_timing(None) == {"status": "not_emitted"}


@pytest.mark.parametrize("parent", ("scope", "projection", "ranking_page"))
def test_nested_elapsed_subtotals_are_not_added_to_their_parent(parent):
    header = (f'materials_path;desc="scan", {parent};dur=34.000, '
              'parent_execute_elapsed;dur=3.000, lifecycle_resolver_elapsed;dur=15.000, '
              'lifecycle_execute_elapsed;dur=9.000, scope_policy_elapsed;dur=14.000, total;dur=35.000')
    parsed = profile.parse_timing(header)
    assert parsed["status"] == "available"
    assert sum(parsed["stage_ms"].values()) > parsed["stage_ms"]["total"]


@pytest.mark.parametrize("children", (
    'lifecycle_resolver_elapsed;dur=10.000, lifecycle_execute_elapsed;dur=11.000',
    'parent_execute_elapsed;dur=20.000, scope_policy_elapsed;dur=20.000',
))
def test_child_intervals_cannot_exceed_their_actual_enclosing_intervals(children):
    header = f'materials_path;desc="scan", scope;dur=30.000, {children}, total;dur=31.000'
    assert profile.parse_timing(header) == {"status": "invalid"}


def test_failures_and_cache_paths_have_separate_denominators():
    attempts = [
        {"status": 200, "error": None, "elapsed_seconds": 1,
         "timing": profile.parse_timing('materials_path;desc="scan", scope;dur=400.000, total;dur=500.000')},
        {"status": 200, "error": None, "elapsed_seconds": .3,
         "timing": profile.parse_timing('materials_path;desc="page_hit", revision;dur=1.000, total;dur=2.000')},
        {"status": 503, "error": "HTTPError", "elapsed_seconds": 20, "timing": profile.parse_timing(None)},
    ]
    summary = profile.summarize(attempts)
    assert summary["attempts"] == 3 and summary["successful"] == 2 and summary["failures"] == 1
    assert summary["timing_status_counts"] == {"available": 2, "not_emitted": 0, "invalid": 0}
    assert summary["by_server_path"]["scan"]["stage_median_ms"]["scope"] == 400
    assert "scope" not in summary["by_server_path"]["page_hit"]["stage_median_ms"]


@pytest.mark.parametrize("version_changes", (False, True))
def test_older_release_or_changed_version_cannot_complete_server_profile(monkeypatch, version_changes):
    version_reads = 0
    calls = []

    def read(url, encoding):
        nonlocal version_reads
        calls.append(url)
        if url.endswith("/version"):
            version_reads += 1
            value = {"site_version": "old" if version_reads == 1 or not version_changes else "new",
                     "dataset_version": "v1", "api_version": "1"}
        else:
            value = {"total": 1, "results": [{}]}
        return {"status": 200, "error": None, "elapsed_seconds": .1}, value

    monkeypatch.setattr(profile.public, "json_request", read)
    report = profile.collect(samples=2)
    assert len(calls) == 12 and all(url.startswith(profile.public.API + "/") for url in calls)
    assert report["http_capture_complete"] is (not version_changes)
    assert not report["server_profile_complete"]
    assert report["version_stable"] is (not version_changes)
    assert not report["scientific_acceptance"] and report["slo_acceptance"] is None
