"""Read-only typed result identity for the next Materials review contract.

The claim adjudication writer consumes this exact snapshot separately. This
service never creates a review or grants dataset authority.
"""
import asyncio
from dataclasses import dataclass
import hashlib
import json
from uuid import NAMESPACE_URL, UUID, uuid5

import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError

from services.scientific_result_subject import (MAX_SECONDS, MAX_SUBJECT_BYTES, VERSION_V2, VERSION_V3,
    ScientificSubjectUnavailable, identifier, require, require_read_session, _json)

VERSION = VERSION_V2


def typed_target(result_kind, result_id):
    require(type(result_kind) is str and result_kind in {"claim", "property"}, "scientific_subject_result_kind")
    return result_kind, identifier(result_id)


@dataclass(frozen=True, slots=True)
class MaterialsResultSubject:
    text: str
    sha256: str
    subject_id: UUID
    result_row_sha256: str
    version: str = VERSION

    @property
    def data(self):
        require(hashlib.sha256(self.text.encode()).hexdigest()==self.sha256, "scientific_subject_private_snapshot_changed")
        return _json(self.text, version=self.version)


async def capture_subject(db, *, result_kind, result_id):
    return await _capture(db, result_kind=result_kind, result_id=result_id, version=VERSION)


async def capture_context_subject(db, *, result_kind, result_id):
    """Read new context without lending it the authority of a v2 decision."""
    return await _capture(db, result_kind=result_kind, result_id=result_id, version=VERSION_V3)


async def _capture(db, *, result_kind, result_id, version):
    result_kind, result_id = typed_target(result_kind, result_id)
    table = "material_claims" if result_kind == "claim" else "event_properties"
    function = "sclib_scientific_subject_capture_v3" if version == VERSION_V3 else "sclib_scientific_subject_capture_v2"
    try:
        async with asyncio.timeout(MAX_SECONDS):
            await require_read_session(db)
            with db.no_autoflush:
                row=(await db.execute(sa.text(f"""
                  WITH captured AS MATERIALIZED (
                    SELECT public.{function}(:kind,:id) AS body
                  ) SELECT body,
                    (SELECT public.sclib_scientific_adjudication_canonical_v1(item->'snapshot')
                     FROM jsonb_array_elements(body::jsonb->'rows') item
                     WHERE item->>'table'=:table AND item->>'row_id'=:key) AS result_text
                  FROM captured
                """),{"kind":result_kind,"id":result_id,"table":table,"key":str(result_id)})).mappings().one()
                text, result_text = row["body"], row["result_text"]
                data=_json(text,version=version)
                if version == VERSION:
                    require(not any(r["table"]=="research_events" and "materials_context" in r["snapshot"]["context"]
                                    for r in data["rows"]), "materials_context_review_contract_required")
                    require(not any(r["table"]=="material_states" and r["snapshot"]["condition_schema_version"] in {"materials-conditions/1","materials-conditions/2","materials-conditions/3"}
                                    for r in data["rows"]), "materials_conditions_review_contract_required")
                require(data["target"]["result_kind"]==result_kind and data["target"]["result_id"]==str(result_id)
                        and type(result_text) is str and 0<len(result_text.encode())<=MAX_SUBJECT_BYTES,
                        "scientific_subject_target_mismatch")
                sha=hashlib.sha256(text.encode()).hexdigest()
                uid=uuid5(NAMESPACE_URL,json.dumps([version,result_kind,str(result_id),sha],separators=(",",":")))
                return MaterialsResultSubject(text,sha,uid,hashlib.sha256(result_text.encode()).hexdigest(),version)
    except (SQLAlchemyError,TimeoutError):
        raise ScientificSubjectUnavailable("scientific_subject_capture_unavailable") from None
