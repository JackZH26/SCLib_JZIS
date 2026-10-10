"""Fixed-label, request-local Materials timings; never stored in response caches."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from time import perf_counter

from services.metrics import MATERIAL_LIST_STAGE_DURATION

# Durations are aggregated across all batches in one request. Children overlap
# their enclosing scope/projection/ranking_page stages, and resolver includes
# execute. These elapsed intervals are not additive or CPU/DB-server timings.
# No SQL, query or source IDs are labels.
TOP_LEVEL_STAGES = (
    "revision", "lock_wait", "scan_fetch", "scope", "selection", "scan_close",
    "projection", "ranking_page", "ranking_publish", "serialization", "total",
)
SCOPE_CHILD_STAGES = (
    "parent_execute_elapsed", "lifecycle_resolver_elapsed",
    "lifecycle_execute_elapsed", "scope_policy_elapsed",
)
STAGES = TOP_LEVEL_STAGES + SCOPE_CHILD_STAGES
PATHS = frozenset({"uncached", "page_hit", "waited_hit", "ranking", "scan"})


@dataclass(slots=True)
class MaterialListTiming:
    path: str = "uncached"
    seconds: dict[str, float] = field(default_factory=dict)

    def header(self) -> str:
        return ", ".join([
            f'materials_path;desc="{self.path}"',
            *(f"{stage};dur={self.seconds[stage] * 1000:.3f}"
              for stage in STAGES if stage in self.seconds),
        ])


_current: ContextVar[MaterialListTiming | None] = ContextVar("material_list_timing", default=None)


@contextmanager
def material_list_request() -> Iterator[MaterialListTiming]:
    timing = MaterialListTiming()
    token = _current.set(timing)
    try:
        yield timing
    finally:
        # Also reset on a refusal, revision conflict or request cancellation.
        _current.reset(token)


def material_list_path(path: str) -> None:
    if path not in PATHS:
        raise ValueError("Unknown Materials timing path")
    if (timing := _current.get()) is not None:
        timing.path = path


@contextmanager
def material_list_stage(stage: str) -> Iterator[None]:
    if stage not in STAGES:
        raise ValueError("Unknown Materials timing stage")
    timing = _current.get()
    if timing is None:
        # The shared revision helper also serves detail/enrichment routes.
        # Their work must not appear in Materials-list stage metrics.
        yield
        return
    started = perf_counter()
    try:
        yield
    finally:
        duration = perf_counter() - started
        MATERIAL_LIST_STAGE_DURATION.labels(stage).observe(duration)
        timing.seconds[stage] = timing.seconds.get(stage, 0.0) + duration
