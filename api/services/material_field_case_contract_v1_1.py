"""Opt-in raw-only pending field cases; frozen 1.0 operations stay separate."""
from services import material_field_case_contract as legacy
from services.material_literal_field_contract import FIELDS as RAW_FIELDS
from services.material_literal_field_contract import PROFILE as PROFILE
from services.research_release_manifest import canonical

VERSION = "material-field-case/1.1.0"
REQUEST_VERSION = "material-field-case-operation/1.1.0"
FIELDS = tuple(RAW_FIELDS)
ALL_FIELDS = (*legacy.FIELDS, *FIELDS)
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
        p = request["payload"]
        legacy.closed(p, ("field_id", "target"))
        legacy.require(type(p["field_id"]) is str and p["field_id"] in FIELDS,
                       "field_case_raw_field_registry")
        selector(p["target"])
        legacy.require(len(canonical(request)) <= MAX_BYTES, "field_case_operation_bound")
    else:
        # Association/attempt shapes are unchanged. The service and SQL separately
        # pin the target's raw profile; this does not extend the old registry.
        legacy.validate({**request, "version": legacy.REQUEST_VERSION})
    return request
