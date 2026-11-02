"""An ordinary application release must preserve the running database model."""
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_default_postgres_service_matches_the_approved_production_baseline():
    baseline = json.loads((ROOT / "ops/postgres/production-service-baseline.json").read_text())
    current = yaml.safe_load((ROOT / "docker-compose.yml").read_text())["services"]["postgres"]
    assert baseline["source_revision"] == "984d5d96f7bc5a8727fab20579e4016f740bef42"
    assert current == baseline["service"]


def test_maintenance_override_requires_explicit_image_and_memory_inputs():
    override = yaml.safe_load((ROOT / "docker-compose.pgvector.yml").read_text())["services"]
    assert set(override) == {"postgres"}
    assert set(override["postgres"]) == {"image", "shm_size"}
    assert override["postgres"]["image"].startswith("${POSTGRES_IMAGE:?")
    assert override["postgres"]["shm_size"].startswith("${POSTGRES_SHM_SIZE:?")
