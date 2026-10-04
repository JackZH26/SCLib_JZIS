"""Private native-file returns: research association is explicitly unverified."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from services import discovery_feedback_contract as common
from services.qe_pw_import import preflight_pw
from services.research_release_manifest import canonical
from services.source_property_pending import SourcePropertyError

VERSION = "discovery-calculation-return/1.0.0"
REQUEST_VERSION = "discovery-calculation-operation/1.0.0"
MAX_REQUEST_BYTES = 32768
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_INPUT_BYTES = 1024 * 1024
MAX_PACKAGE_BYTES = 81 * 1024 * 1024
MAX_PAGE = 8
AUTHORITY = {"scientific_acceptance": False, "ml_training_approved": False,
             "public_release": False, "execution_authenticated": False,
             "candidate_source_association_verified": False, "canonical_promotions": 0}


def require(ok, code):
    if not ok:
        raise SourcePropertyError(code)


def validate(request):
    common.closed(request, ("version", "request_key", "design", "files", "findings", "decision", "reason", "unknowns", "association"))
    require(request["version"] == REQUEST_VERSION, "calculation_request_version")
    require(type(request["request_key"]) is str and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/+@-]{0,159}", request["request_key"]), "calculation_request_key")
    common.design_pin(request["design"])
    require(request["association"] == "researcher_linked_unverified", "calculation_explicit_association_required")
    common.text(request["findings"], 4000)
    common.text(request["reason"], 2000)
    require(request["decision"] in common.DECISIONS, "calculation_decision_required")
    require(type(request["unknowns"]) is list and len(request["unknowns"]) <= 16, "calculation_unknowns_bound")
    for item in request["unknowns"]:
        common.text(item, 1000)
    require(len(set(request["unknowns"])) == len(request["unknowns"]), "calculation_duplicate_unknown")
    files = request["files"]
    require(type(files) is list and 4 <= len(files) <= 11, "calculation_file_inventory_bound")
    for item in files:
        common.closed(item, ("role", "name", "sha256", "size_bytes"))
        require(item["role"] in ("input", "xml", "stdout", "upf"), "calculation_file_role")
        require(type(item["name"]) is str and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}", item["name"])
                and ".." not in item["name"], "calculation_logical_filename")
        common.checksum(item["sha256"])
        require(type(item["size_bytes"]) is int and 1 <= item["size_bytes"] <=
                (MAX_INPUT_BYTES if item["role"] == "input" else MAX_FILE_BYTES), "calculation_file_size")
    require(all(sum(f["role"] == role for f in files) == 1 for role in ("input", "xml", "stdout")), "calculation_required_files")
    require(len({(f["role"], f["name"]) for f in files}) == len(files), "calculation_duplicate_file")
    require(files == sorted(files, key=lambda f: (f["role"], f["name"])), "calculation_inventory_order")
    require(sum(f["size_bytes"] for f in files) <= MAX_PACKAGE_BYTES, "calculation_package_bound")
    require(len(canonical(request)) <= MAX_REQUEST_BYTES, "calculation_request_bound")
    return request


@dataclass(frozen=True, slots=True)
class Prepared:
    """Internal parser product; never deserialized from an HTTP report."""
    request_json: str
    files: tuple[bytes, ...]
    report_json: str

    @property
    def request(self):
        return json.loads(self.request_json)

    @property
    def report_sha256(self):
        return hashlib.sha256(self.report_json.encode()).hexdigest()


def prepare(request, files):
    validate(request)
    request_text = canonical(request).decode()
    frozen = json.loads(request_text)
    require(type(files) in (list, tuple) and len(files) == len(frozen["files"]), "calculation_exact_bytes_inventory")
    # Complete cheap size/hash validation precedes any scientific parsing.
    for item, raw in zip(frozen["files"], files, strict=True):
        require(type(raw) is bytes and len(raw) == item["size_bytes"], "calculation_original_size_mismatch")
        require(hashlib.sha256(raw).hexdigest() == item["sha256"], "calculation_original_hash_mismatch")
    by_role = {item["role"]: raw for item, raw in zip(frozen["files"], files, strict=True) if item["role"] != "upf"}
    pseudos = {item["name"]: raw for item, raw in zip(frozen["files"], files, strict=True) if item["role"] == "upf"}
    report = preflight_pw(input_bytes=by_role["input"], xml_bytes=by_role["xml"],
                          stdout_bytes=by_role["stdout"], pseudopotentials=pseudos)
    report_json = canonical(report).decode()
    require(len(report_json.encode()) <= 256 * 1024, "calculation_report_bound")
    return Prepared(request_text, tuple(files), report_json)
