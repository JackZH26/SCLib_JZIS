#!/usr/bin/env python3
"""Create (or reuse) the Vertex AI Vector Search index for SCLib_JZIS.

Run once during Phase 0, either on VPS2 (where ADC is already configured at
/root/.config/gcloud/application_default_credentials.json) or locally with a
service-account JSON referenced by GOOGLE_APPLICATION_CREDENTIALS.

Idempotent: if an index or endpoint with the target display name already
exists, it is reused instead of recreated.

What this script creates:
  1. MatchingEngineIndex       (display_name=sclib-papers-v1, streaming updates,
                                768-dim, COSINE, TREE_AH)
  2. MatchingEngineIndexEndpoint (display_name=sclib-papers-endpoint, public)
  3. Deploys the index to the endpoint as deployed_index_id=sclib_papers_v1

On success it prints the three env-var lines to paste into VPS2 .env:
  VERTEX_AI_INDEX_ENDPOINT=projects/.../locations/.../indexEndpoints/<id>
  VERTEX_AI_DEPLOYED_INDEX_ID=sclib_papers_v1
  GCS_BUCKET=sclib-jzis   (already known, just a reminder)

Usage:
  uv pip install google-cloud-aiplatform
  python scripts/create_vertex_index.py \
      --project jzis-sclib --region us-central1

Heads up: Vector Search endpoint deployment takes 20-40 minutes. The script
blocks until the deployed index is READY.
"""
from __future__ import annotations

import argparse
import logging
import sys
from typing import Optional

try:
    from google.cloud import aiplatform
    from google.cloud.aiplatform import MatchingEngineIndex, MatchingEngineIndexEndpoint
except ImportError as exc:  # pragma: no cover
    sys.stderr.write(
        "ERROR: google-cloud-aiplatform not installed. Run:\n"
        "  uv pip install google-cloud-aiplatform\n"
    )
    raise SystemExit(1) from exc


INDEX_DISPLAY_NAME = "sclib-papers-v1"
ENDPOINT_DISPLAY_NAME = "sclib-papers-endpoint"
DEPLOYED_INDEX_ID = "sclib_papers_v1"  # must match env VERTEX_AI_DEPLOYED_INDEX_ID
DIMENSIONS = 768  # text-embedding-005
APPROXIMATE_NEIGHBORS_COUNT = 150


log = logging.getLogger("create_vertex_index")


def find_index(display_name: str) -> Optional[MatchingEngineIndex]:
    for idx in MatchingEngineIndex.list(filter=f'display_name="{display_name}"'):
        return idx
    return None


def find_endpoint(display_name: str) -> Optional[MatchingEngineIndexEndpoint]:
    for ep in MatchingEngineIndexEndpoint.list(filter=f'display_name="{display_name}"'):
        return ep
    return None


def create_index() -> MatchingEngineIndex:
    existing = find_index(INDEX_DISPLAY_NAME)
    if existing is not None:
        log.info("Reusing existing index: %s", existing.resource_name)
        return existing

    log.info("Creating new streaming index %s (%dd, COSINE, TREE_AH)",
             INDEX_DISPLAY_NAME, DIMENSIONS)
    index = MatchingEngineIndex.create_tree_ah_index(
        display_name=INDEX_DISPLAY_NAME,
        dimensions=DIMENSIONS,
        approximate_neighbors_count=APPROXIMATE_NEIGHBORS_COUNT,
        distance_measure_type="COSINE_DISTANCE",
        leaf_node_embedding_count=500,
        leaf_nodes_to_search_percent=7,
        index_update_method="STREAM_UPDATE",
        description="SCLib_JZIS superconductivity paper chunks (text-embedding-005)",
    )
    log.info("Created index: %s", index.resource_name)
    return index


def create_endpoint() -> MatchingEngineIndexEndpoint:
    existing = find_endpoint(ENDPOINT_DISPLAY_NAME)
    if existing is not None:
        log.info("Reusing existing endpoint: %s", existing.resource_name)
        return existing

    log.info("Creating public endpoint %s (this may take a few minutes)",
             ENDPOINT_DISPLAY_NAME)
    endpoint = MatchingEngineIndexEndpoint.create(
        display_name=ENDPOINT_DISPLAY_NAME,
        public_endpoint_enabled=True,
        description="SCLib_JZIS Vector Search endpoint",
    )
    log.info("Created endpoint: %s", endpoint.resource_name)
    return endpoint


def deploy(index: MatchingEngineIndex, endpoint: MatchingEngineIndexEndpoint) -> None:
    for deployed in endpoint.deployed_indexes:
        if deployed.id == DEPLOYED_INDEX_ID:
            log.info("Index already deployed as %s; skipping", DEPLOYED_INDEX_ID)
            return

    log.info("Deploying index %s to endpoint as %s (20-40 min, blocking)",
             index.display_name, DEPLOYED_INDEX_ID)
    endpoint.deploy_index(
        index=index,
        deployed_index_id=DEPLOYED_INDEX_ID,
        display_name=DEPLOYED_INDEX_ID,
        min_replica_count=1,
        max_replica_count=1,
    )
    log.info("Deployment complete")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default="jzis-sclib")
    parser.add_argument("--region", default="us-central1")
    parser.add_argument("--skip-deploy", action="store_true",
                        help="Create index+endpoint but do not deploy (debug)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    log.info("Initializing aiplatform: project=%s region=%s", args.project, args.region)
    aiplatform.init(project=args.project, location=args.region)

    index = create_index()
    endpoint = create_endpoint()
    if not args.skip_deploy:
        deploy(index, endpoint)

    print()
    print("=" * 70)
    print("Phase 0.6 complete. Paste the following into VPS2 /opt/SCLib_JZIS/.env:")
    print("=" * 70)
    print(f"VERTEX_AI_INDEX_ENDPOINT={endpoint.resource_name}")
    print(f"VERTEX_AI_DEPLOYED_INDEX_ID={DEPLOYED_INDEX_ID}")
    print(f"GCS_BUCKET=sclib-jzis")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
