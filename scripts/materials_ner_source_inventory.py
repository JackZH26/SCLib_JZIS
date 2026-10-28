"""Read-only source inventory. Run inside the configured API container.

No Harvest calls, credential export, source-text export or database writes.
GCS listing is optional and bounded; a partial listing is never a corpus total.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import datetime, timezone


async def inventory(gcs_limit: int = 0, paper_plan: bool = False) -> dict:
    from sqlalchemy import text
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import create_async_engine

    report = {"schema": "materials-ner-source-inventory/1",
              "captured_at": datetime.now(timezone.utc).isoformat(),
              "database_read_only": True, "harvest_called": False, "errors": []}
    url = make_url(os.environ["DATABASE_URL"]).set(drivername="postgresql+asyncpg")
    engine = create_async_engine(url, connect_args={"timeout": 10})
    queries = {
        "papers": """SELECT source, count(*) AS papers,
            count(*) FILTER (WHERE related_paper_id IS NOT NULL) AS linked_papers,
            count(*) FILTER (WHERE jsonb_array_length(materials_extracted)>0) AS with_ner,
            sum(chunk_count) AS declared_chunks
            FROM papers GROUP BY source ORDER BY source""",
        "chunk_types": """SELECT p.source, coalesce(e.chunk_kind,'legacy_unknown') AS kind,
            count(*) AS chunks, count(DISTINCT c.paper_id) AS papers,
            sum(length(c.text)) AS characters,
            count(*) FILTER (WHERE c.has_table) AS table_flags
            FROM chunks c JOIN papers p ON p.id=c.paper_id
            LEFT JOIN chunk_evidence_current cc ON cc.chunk_id=c.id
            LEFT JOIN rag_evidence_revisions e ON e.id=cc.evidence_revision_id
            GROUP BY p.source, coalesce(e.chunk_kind,'legacy_unknown')
            ORDER BY p.source, kind""",
        "aps_section_types": """SELECT coalesce(c.section,'') AS section, count(*) AS chunks
            FROM chunks c JOIN papers p ON p.id=c.paper_id WHERE p.source='aps'
            GROUP BY c.section ORDER BY count(*) DESC LIMIT 30""",
        "aps_overlap": """WITH arxiv_dois AS
            (SELECT DISTINCT lower(doi) AS doi FROM papers WHERE source='arxiv' AND doi IS NOT NULL)
            SELECT count(*) AS aps_papers,
            count(*) FILTER (WHERE a.id IS NOT NULL OR d.doi IS NOT NULL) AS arxiv_matches
            FROM papers p LEFT JOIN papers a ON a.id=p.related_paper_id AND a.source='arxiv'
            LEFT JOIN arxiv_dois d ON lower(p.doi)=d.doi
            WHERE p.source='aps'""",
        "aps_samples": """SELECT p.id,p.doi,p.title,p.related_paper_id,p.chunk_count,
            jsonb_array_length(p.materials_extracted) AS old_ner_records
            FROM papers p WHERE p.source='aps'
            ORDER BY md5(p.id) LIMIT 24""",
    }
    try:
        async with engine.connect() as connection:
            async with connection.begin():
                await connection.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
                await connection.execute(text("SET LOCAL statement_timeout='45s'"))
                for key, sql in queries.items():
                    report[key] = [dict(row) for row in
                                   (await connection.execute(text(sql))).mappings()]
                if paper_plan:
                    report["paper_plan"] = [dict(row) for row in (await connection.execute(text("""
                        SELECT id,source,arxiv_id,doi,title,related_paper_id,material_family,
                        status,date_submitted,date_published,chunk_count,
                        jsonb_array_length(materials_extracted) AS old_ner_records
                        FROM papers ORDER BY id
                    """))).mappings()]
    finally:
        await engine.dispose()
    if gcs_limit:
        try:
            from google.cloud import storage
            client = storage.Client(project=os.getenv("GCP_PROJECT", "jzis-sclib"))
            bucket = os.getenv("GCS_BUCKET", "sclib-jzis")
            report["gcs"] = {"bucket": bucket, "listing_complete": False,
                             "per_prefix_limit": gcs_limit, "objects": [], "prefixes": []}
            for prefix in ("src/", "pdf/", "captures/arxiv/"):
                count = 0
                for blob in client.list_blobs(bucket, prefix=prefix, max_results=gcs_limit,
                                              timeout=30):
                    count += 1
                    report["gcs"]["objects"].append({
                        "name": blob.name, "size": blob.size, "generation": blob.generation,
                        "crc32c": blob.crc32c, "updated": blob.updated.isoformat() if blob.updated else None,
                    })
                report["gcs"]["prefixes"].append({"prefix": prefix, "count": count,
                                                 "complete": count < gcs_limit})
            report["gcs"]["listing_complete"] = all(p["complete"] for p in report["gcs"]["prefixes"])
        except Exception as error:
            # Provider exceptions may contain credential endpoints; keep only the class.
            report["errors"].append({"stage": "gcs_inventory", "error": type(error).__name__})
    report["scientific_acceptance"] = False
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gcs-limit", type=int, default=0)
    parser.add_argument("--paper-plan", action="store_true")
    args = parser.parse_args()
    if not 0 <= args.gcs_limit <= 100000:
        parser.error("gcs-limit must be 0..100000")
    print(json.dumps(asyncio.run(inventory(args.gcs_limit, args.paper_plan)), ensure_ascii=False, default=str))
