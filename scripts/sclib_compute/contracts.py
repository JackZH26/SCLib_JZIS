"""Closed transport contracts; none of these records grant scientific approval."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
JobKind = Literal["dummy", "structure_check", "qe_initialize", "qe_scf", "qe_relax", "qe_ph"]
JOB_KINDS = {"dummy", "structure_check", "qe_initialize", "qe_scf", "qe_relax", "qe_ph"}
ACTIVE_STATES = {"leased", "preparing", "running", "uploading"}


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class FilePin(Closed):
    name: Identifier
    sha256: Sha256
    bytes: Annotated[int, Field(ge=0, le=16 * 1024 * 1024)]


class OutputRule(Closed):
    name: Identifier
    max_bytes: Annotated[int, Field(ge=1, le=16 * 1024 * 1024)]


class Resources(Closed):
    cpu_cores: Annotated[int, Field(ge=1, le=64)]
    wall_seconds: Annotated[int, Field(ge=1, le=86400)]
    memory_bytes: Annotated[int, Field(ge=1, le=1024**4)]
    output_bytes: Annotated[int, Field(ge=1, le=64 * 1024 * 1024)]


class JobSpec(Closed):
    schema_version: Literal["sclib-compute-job/1"] = "sclib-compute-job/1"
    job_id: Identifier
    kind: JobKind
    runtime_id: Identifier
    case_ref: Identifier
    state_ref: Identifier
    action_ref: Identifier
    input_artifacts: Annotated[list[FilePin], Field(min_length=1, max_length=16)]
    output_rules: Annotated[list[OutputRule], Field(min_length=1, max_length=16)]
    resources: Resources
    max_attempts: Annotated[int, Field(ge=1, le=3)] = 1
    deadline_unix: Annotated[int, Field(ge=1)]
    input_visibility: Literal["private_staging"] = "private_staging"
    scientific_publication_authority: Literal[False] = False

    @model_validator(mode="after")
    def unique_names(self):
        for files in [self.input_artifacts, self.output_rules]:
            names = [item.name for item in files]
            if len(names) != len(set(names)) or any(name in {".", ".."} for name in names):
                raise ValueError("artifact names must be distinct bounded basenames")
        if sum(item.max_bytes for item in self.output_rules) > self.resources.output_bytes:
            raise ValueError("output rules exceed the frozen output envelope")
        return self

    @property
    def input_manifest_sha256(self) -> str:
        return digest([item.model_dump(mode="json") for item in self.input_artifacts])


class NodeRegistration(Closed):
    # Identity is supplied by authenticated certificate mapping, never this body.
    runtime_id: Identifier
    capabilities: Annotated[list[JobKind], Field(min_length=1, max_length=6)]
    platform: Literal["dummy_test", "linux_x86_64", "macos_arm64"]

    @model_validator(mode="after")
    def distinct_capabilities(self):
        if len(set(self.capabilities)) != len(self.capabilities):
            raise ValueError("capabilities must be distinct")
        return self


class Claim(Closed):
    claim_request_id: Identifier


class Heartbeat(Closed):
    fencing_token: Annotated[int, Field(ge=1)]
    phase: Literal["leased", "preparing", "running", "uploading"]
    elapsed_seconds: Annotated[int, Field(ge=0, le=86400)]
    observed_memory_bytes: Annotated[int, Field(ge=0, le=1024**4)]


class Completion(Closed):
    fencing_token: Annotated[int, Field(ge=1)]
    input_manifest_sha256: Sha256
    runtime_id: Identifier
    manifest: Annotated[list[FilePin], Field(min_length=1, max_length=16)]
    solver_outcome: Literal["success", "solver_failure", "not_converged", "clean_checkpoint"]
    elapsed_seconds: Annotated[int, Field(ge=0, le=86400)]
    scientific_status: Literal["not_assessed"] = "not_assessed"

    @model_validator(mode="after")
    def distinct(self):
        if len({item.name for item in self.manifest}) != len(self.manifest):
            raise ValueError("manifest contains duplicate artifact names")
        return self


class Failure(Closed):
    fencing_token: Annotated[int, Field(ge=1)]
    code: Literal["download_interrupted", "upload_interrupted", "worker_crash", "execution_timeout", "solver_failure", "not_converged"]


class Drain(Closed):
    enabled: bool


class DummyInput(Closed):
    mode: Literal["success", "solver_failure", "not_converged", "clean_checkpoint"] = "success"
    steps: Annotated[int, Field(ge=1, le=5)] = 1
