"""Run with python -I: prove the bridge and both dependencies are installed."""
from importlib.metadata import version
import hashlib
import json
from pathlib import Path
import sys

import ingestion.index.indexer as indexer
import native_publisher.producer as producer
import native_publisher.batch as batch
import services.retrieval_native as native
from services.schema_lifecycle import expected_heads

modules = {"bridge": producer, "batch_worker": batch, "source_writer": indexer, "native_contract": native}
assert all(Path(module.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
    for module in modules.values()), "Refusing repository imports"
assert expected_heads() == ("0117_retrieval_policy_v4",)
assert callable(producer.publish_prepared) and callable(indexer.upsert_paper_with_chunks)
print(json.dumps({"version": "native-publisher-installed-probe/1.0.0",
    "interpreter": sys.version.split()[0], "repository_imports": False,
    "packages": {name: version(name) for name in ("sclib-native-publisher", "sclib-api", "sclib-ingestion")},
    "schema_heads": expected_heads(), "modules_sha256": {key: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
        for key, module in modules.items()}, "database_connected": False, "provider_calls": False}))
