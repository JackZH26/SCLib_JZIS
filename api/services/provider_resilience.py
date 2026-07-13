"""Timeout and circuit-breaker boundary for blocking cloud SDK calls."""
from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from services.metrics import observe_provider

T = TypeVar("T")


class ProviderUnavailable(RuntimeError):
    """A provider timed out, failed, or has an open circuit."""


@dataclass(slots=True)
class _Circuit:
    failures: int = 0
    opened_until: float = 0.0


_circuits: dict[str, _Circuit] = {}


async def run_blocking(
    provider: str,
    operation: Callable[[], T],
    *,
    timeout_seconds: float,
    failure_threshold: int,
    cooldown_seconds: float,
    max_attempts: int = 2,
) -> T:
    """Run a blocking provider call with timeout, retry, and circuit isolation.

    Immediate provider exceptions may be retried. A timed-out thread cannot be
    safely cancelled, so timeout failures are never duplicated.
    """
    circuit = _circuits.setdefault(provider, _Circuit())
    started = time.monotonic()
    now = started
    if circuit.opened_until > now:
        observe_provider(provider, "circuit_open", 0.0, 0)
        raise ProviderUnavailable(f"{provider} circuit is open")

    attempts = max(1, min(max_attempts, 3))
    last_exception: Exception | None = None
    for attempt in range(attempts):
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(operation),
                timeout=timeout_seconds,
            )
            break
        except TimeoutError:
            _record_failure(circuit, failure_threshold, cooldown_seconds)
            observe_provider(provider, "timeout", time.monotonic() - started, attempt + 1)
            raise ProviderUnavailable(f"{provider} timed out") from None
        except Exception as exc:
            last_exception = exc
            if attempt + 1 < attempts:
                continue
            _record_failure(circuit, failure_threshold, cooldown_seconds)
            observe_provider(provider, "failure", time.monotonic() - started, attempt + 1)
            raise ProviderUnavailable(f"{provider} failed") from exc
    else:  # pragma: no cover - the bounded loop always returns or raises
        raise ProviderUnavailable(f"{provider} failed") from last_exception

    circuit.failures = 0
    circuit.opened_until = 0.0
    observe_provider(provider, "success", time.monotonic() - started, attempt + 1)
    return result


def _record_failure(
    circuit: _Circuit,
    failure_threshold: int,
    cooldown_seconds: float,
) -> None:
    circuit.failures += 1
    if circuit.failures >= max(1, failure_threshold):
        circuit.opened_until = time.monotonic() + max(0.0, cooldown_seconds)


def reset() -> None:
    """Reset breaker state for tests and controlled process teardown."""
    _circuits.clear()
