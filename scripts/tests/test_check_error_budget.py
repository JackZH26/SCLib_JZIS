from __future__ import annotations

import argparse
import unittest

from scripts.check_error_budget import (
    _increase_query,
    _valid_window,
    evaluate_availability,
    evaluate_freshness,
)


class ErrorBudgetEvaluationTests(unittest.TestCase):
    def test_availability_passes_at_target(self) -> None:
        result = evaluate_availability(
            "public-api",
            total=10_000,
            errors=10,
            target=0.999,
            minimum_requests=100,
            allow_no_data=False,
        )
        self.assertTrue(result.passed)
        self.assertAlmostEqual(result.observed or 0, 0.999)

    def test_availability_fails_when_budget_is_exhausted(self) -> None:
        result = evaluate_availability(
            "ai-api",
            total=1_000,
            errors=6,
            target=0.995,
            minimum_requests=20,
            allow_no_data=False,
        )
        self.assertFalse(result.passed)

    def test_missing_traffic_fails_closed_by_default(self) -> None:
        result = evaluate_availability(
            "public-api",
            total=None,
            errors=None,
            target=0.999,
            minimum_requests=100,
            allow_no_data=False,
        )
        self.assertFalse(result.passed)
        self.assertIsNone(result.observed)

    def test_missing_traffic_can_be_allowed_for_bootstrap(self) -> None:
        result = evaluate_availability(
            "public-api",
            total=2,
            errors=0,
            target=0.999,
            minimum_requests=100,
            allow_no_data=True,
        )
        self.assertTrue(result.passed)

    def test_data_older_than_24_hours_fails(self) -> None:
        result = evaluate_freshness(
            age_seconds=86_401,
            maximum_age_seconds=86_400,
            allow_no_data=False,
        )
        self.assertFalse(result.passed)

    def test_prometheus_query_matches_parameterized_route_labels(self) -> None:
        query = _increase_query(
            r"/v1/paper/[{]paper_id[}]",
            "30d",
            errors_only=True,
        )
        self.assertIn('route=~"/v1/paper/[{]paper_id[}]"', query)
        self.assertIn('status=~"5.."', query)

    def test_invalid_window_is_rejected(self) -> None:
        with self.assertRaises(argparse.ArgumentTypeError):
            _valid_window("30 days")


if __name__ == "__main__":
    unittest.main()
