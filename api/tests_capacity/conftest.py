"""Separate owned-service invocation; never load app code before the safety gate.

The shared bootstrap validates the runner's live capability before imports,
creates only its owned schema and drops it on exit. Keep these large committed
fixtures out of the ordinary API session: immutable audit history is not erased
between its tests.
"""
from tests.conftest import _schema as _schema
