"""Offline invariants for the finite source table; original-byte replay is separate."""
import hashlib
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from build_material_nb_cvs_pressure import NAME, build, serialized  # noqa: E402


def test_public_factual_cells_have_source_pins_and_original_numeric_tokens():
    path = ROOT / "frontend/public/research-pilots" / NAME
    raw = path.read_bytes()
    data = json.loads(raw)
    assert serialized(data) == raw
    assert path.with_name(NAME + ".sha256").read_text() == f"{hashlib.sha256(raw).hexdigest()}  {NAME}\n"
    cells = [cell for field in data["fields"] for cell in field["cells"]]
    assert len(cells) == 32
    assert sum(cell["state"] == "source_dash" for cell in cells) == 3
    assert all(cell["normalized_value"] is None for cell in cells)
    assert len({cell["value_locator"]["element_id"] for cell in cells}) == 32
    for cell in cells:
        pin = cell["value_locator"]
        assert pin["html_char_end"] - pin["html_char_start"] == len(cell["raw_value"])
        assert pin["sha256"] == hashlib.sha256(cell["raw_value"].encode()).hexdigest()
    assert data["fields"][5]["cells"][2]["raw_value"] == "3.5(9)"
    assert data["fields"][1]["symbol"] == "λ(T > 0)"
    assert data["fields"][2]["display_unit"] is None
    assert data["counts"]["additional_property_parameters"] == 18
    assert data["counts"]["fit_statistic_numeric_cells"] == 8
    assert not any(data["authority"].values())


def test_replay_rejects_unpinned_sources_before_parsing():
    with pytest.raises(ValueError, match="differs from the inspected source version"):
        build(b"<table>plausible but unauthenticated values</table>", b"%PDF-changed")
