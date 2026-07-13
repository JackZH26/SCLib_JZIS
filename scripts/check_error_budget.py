#!/usr/bin/env python3
"""Fail a release when production SLO error budgets are exhausted."""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

PUBLIC_ROUTES = (
    r'/v1/(stats|version|materials|materials/[{]material_id[}]|'
    r'paper/[{]paper_id[}]|timeline|discovery/candidates)'
)
AI_ROUTES = r'/v1/(search|ask|paper/[{]paper_id[}]/similar)'
_WINDOW_PATTERN = re.compile(r"^[1-9][0-9]*[smhdwy]$")


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    observed: float | None
    target: float
    message: str


def evaluate_availability(
    name: str,
    *,
    total: float | None,
    errors: float | None,
    target: float,
    minimum_requests: int,
    allow_no_data: bool,
) -> CheckResult:
    if total is None or errors is None or total < minimum_requests:
        passed = allow_no_data
        return CheckResult(
            name,
            passed,
            None,
            target,
            f"insufficient traffic ({total or 0:.0f}/{minimum_requests} requests)",
        )
    availability = max(0.0, min(1.0, 1.0 - errors / total))
    return CheckResult(
        name,
        availability >= target,
        availability,
        target,
        f"availability {availability:.5%} from {total:.0f} requests and {errors:.0f} errors",
    )


def evaluate_freshness(
    *,
    age_seconds: float | None,
    maximum_age_seconds: float,
    allow_no_data: bool,
) -> CheckResult:
    if age_seconds is None or not math.isfinite(age_seconds):
        return CheckResult(
            "data-freshness",
            allow_no_data,
            None,
            maximum_age_seconds,
            "dataset age metric is unavailable",
        )
    return CheckResult(
        "data-freshness",
        age_seconds <= maximum_age_seconds,
        age_seconds,
        maximum_age_seconds,
        f"dataset age is {age_seconds / 3600:.2f} hours",
    )


def prometheus_scalar(base_url: str, query: str, timeout: float) -> float | None:
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Prometheus URL must be an http(s) origin")
    url = f"{base_url.rstrip('/')}/api/v1/query?{urlencode({'query': query})}"
    request = Request(url, headers={"Accept": "application/json"})
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - operator URL
        payload: dict[str, Any] = json.load(response)
    if payload.get("status") != "success":
        raise RuntimeError(f"Prometheus query failed: {payload}")
    result = payload.get("data", {}).get("result", [])
    if not result:
        return None
    value = result[0].get("value")
    if not isinstance(value, list) or len(value) != 2:
        return None
    return float(value[1])


def _increase_query(routes: str, window: str, *, errors_only: bool) -> str:
    status = ',status=~"5.."' if errors_only else ""
    return (
        "sum(increase(sclib_http_requests_total{"
        f'route=~"{routes}"{status}'
        f"}}[{window}]))"
    )


def run_checks(args: argparse.Namespace) -> list[CheckResult]:
    checks: list[CheckResult] = []
    for name, routes, target, minimum in (
        ("public-api", PUBLIC_ROUTES, 0.999, 100),
        ("ai-api", AI_ROUTES, 0.995, 20),
    ):
        total = prometheus_scalar(
            args.prometheus_url,
            _increase_query(routes, args.window, errors_only=False),
            args.timeout,
        )
        errors = prometheus_scalar(
            args.prometheus_url,
            _increase_query(routes, args.window, errors_only=True),
            args.timeout,
        )
        checks.append(
            evaluate_availability(
                name,
                total=total,
                errors=errors,
                target=target,
                minimum_requests=minimum,
                allow_no_data=args.allow_no_data,
            )
        )
    age = prometheus_scalar(
        args.prometheus_url,
        "max(sclib_dataset_age_seconds)",
        args.timeout,
    )
    checks.append(
        evaluate_freshness(
            age_seconds=age,
            maximum_age_seconds=86400,
            allow_no_data=args.allow_no_data,
        )
    )
    return checks


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--prometheus-url",
        default="http://127.0.0.1:9090",
        help="Prometheus base URL (default: loopback production instance)",
    )
    parser.add_argument(
        "--window",
        default="30d",
        type=_valid_window,
        help="Prometheus range duration",
    )
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument(
        "--allow-no-data",
        action="store_true",
        help="Pass insufficient-data checks (local/bootstrap use only)",
    )
    parser.add_argument("--json", action="store_true", dest="json_output")
    return parser.parse_args(argv)


def _valid_window(value: str) -> str:
    if not _WINDOW_PATTERN.fullmatch(value):
        raise argparse.ArgumentTypeError("window must look like 30d, 4w, or 12h")
    return value


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        checks = run_checks(args)
    except Exception as exc:  # noqa: BLE001 - gate must fail closed
        print(f"release gate could not query Prometheus: {exc}", file=sys.stderr)
        return 2

    if args.json_output:
        print(json.dumps([asdict(check) for check in checks], indent=2))
    else:
        for check in checks:
            marker = "PASS" if check.passed else "FAIL"
            print(f"[{marker}] {check.name}: {check.message}")
    return 0 if all(check.passed for check in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
