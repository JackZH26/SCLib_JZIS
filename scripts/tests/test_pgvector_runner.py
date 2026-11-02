"""Custom image selection never introduces an attach or credential path."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from run_disposable_tests import DisposableServices


@pytest.mark.parametrize("image", ["postgres:latest", "postgres:16-alpine", "existing-container",
                                   "postgres@sha256:" + "a" * 64, "sha256:" + "g" * 64])
def test_custom_images_require_a_local_immutable_id(tmp_path, image):
    with pytest.raises(RuntimeError, match="immutable local image ID"):
        DisposableServices(tmp_path, "docker", None, None, image, True)


def test_native_backend_does_not_accept_an_image(tmp_path):
    with pytest.raises(RuntimeError, match="Docker backend"):
        DisposableServices(tmp_path, "native", None, None, "sha256:" + "a" * 64, True)


def test_default_remains_an_owned_fresh_postgres_service(tmp_path):
    services = DisposableServices(tmp_path, "docker", None, None)
    assert services.postgres_image == "postgres:16-alpine"
    assert services.containers == []
    assert services.manifest["backend"] == "docker"
