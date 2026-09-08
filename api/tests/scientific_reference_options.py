"""Explicit opt-in paths, loaded only with -p tests.scientific_reference_options.

The API conftest still requires the disposable-test capability before any SQL.
This plugin performs no reads, network access, or database initialization.
"""


def pytest_addoption(parser):
    parser.addoption("--scientific-reference-capsules", default=None,
                     help="Read-only directory of batch30 pinned QE capsules")
    parser.addoption("--scientific-force-constants", default=None,
                     help="Read-only directory of two pinned actual force-constant sidecars")
