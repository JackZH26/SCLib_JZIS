"""Explicit opt-in targets for the two supported thermal-table fields."""
from services import material_field_case_contract as legacy
from services.material_table_field_contract import FIELDS as TABLE_FIELDS
from services.material_table_field_contract import PROFILE as PROFILE
from services.research_release_manifest import canonical

VERSION = "material-field-case/1.2.0"
REQUEST_VERSION = "material-field-case-operation/1.2.0"
FIELDS = tuple(TABLE_FIELDS)
AUTHORITY = legacy.AUTHORITY
OUTCOMES = legacy.OUTCOMES
REASONS = legacy.REASONS
MAX_BYTES = legacy.MAX_BYTES
MAX_PAGE = legacy.MAX_PAGE
selector = legacy.selector
bounded_text = legacy.bounded_text


def validate(request):
    legacy.closed(request, ("version", "request_key", "operation", "payload"))
    legacy.require(request["version"] == REQUEST_VERSION, "field_case_request_version")
    if request["operation"] == "target":
        legacy.request_key(request["request_key"])
        payload = request["payload"]
        legacy.closed(payload, ("field_id", "target"))
        legacy.require(type(payload["field_id"]) is str and payload["field_id"] in FIELDS,
                       "field_case_table_field_registry")
        selector(payload["target"])
        legacy.require(len(canonical(request)) <= MAX_BYTES, "field_case_operation_bound")
    else:
        legacy.validate({**request, "version": legacy.REQUEST_VERSION})
    return request
