"""Fixed, locally pinned PBEsol initialization adapter for the native worker loop.

An operator must provide exclusive one-shot host ownership. This module does not
install code, authenticate capture, grant budgets or enable unattended profiles.
The release record is opaque byte provenance, not verified installed contents.
"""

from __future__ import annotations

import hashlib
import math
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .contracts import Closed, Completion, Identifier, Sha256, canonical, digest
from .native_contract import NativeRuntime, read_regular
from .native_worker import NativeWorker, directory, write_once
from .pbesol_init_reader import decode_supported_xml
from .pbesol_native_contract import ARTIFACT_NAMES, OUTPUT_CAPS, validate_pbesol_inputs
from .pbesol_profile import MAX_METADATA_BYTES, MAX_TOTAL_BYTES, MAX_UPF_BYTES
from .pbesol_result_custody import strict_json


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class LocalProfile(Closed):
    schema_version: Literal["sclib-pbesol-local-profile/1"]
    method_profile: Literal["pbesol-source-coarse-qe75/1"]
    stage: Literal["initialize"]
    runtime_id: Identifier
    runtime_config_path: str
    runtime_config_sha256: Sha256
    adapter_release_manifest_path: str
    adapter_release_manifest_sha256: Sha256


def pinned_local_file(name, expected_sha, maximum):
    require(
        type(name) is str and 0 < len(name) <= 1024 and "\x00" not in name,
        "local absolute path required",
    )
    path = Path(name)
    require(
        path.is_absolute() and str(path) == name and ".." not in path.parts,
        "canonical local path required",
    )
    raw = read_regular(path, maximum)
    require(
        not path.stat().st_mode & 0o022,
        "local profile files cannot be group/world writable",
    )
    require(sha(raw) == expected_sha, "local profile file checksum mismatch")
    return raw


@dataclass(frozen=True, slots=True)
class InstalledProfilePins:
    """Locally selected configuration bytes, not an installation attestation."""

    path: str
    sha256: str
    config: LocalProfile
    runtime: NativeRuntime

    def identity(self):
        return {
            "profile_sha256": self.sha256,
            "runtime_config_file_sha256": self.config.runtime_config_sha256,
            "adapter_release_manifest_sha256": self.config.adapter_release_manifest_sha256,
        }


def load_profile(path, expected_sha):
    config = LocalProfile.model_validate(
        strict_json(pinned_local_file(str(path), expected_sha, 65536), 65536)
    )
    runtime_raw = strict_json(
        pinned_local_file(
            config.runtime_config_path, config.runtime_config_sha256, 65536
        ),
        65536,
    )
    runtime = NativeRuntime.model_validate(runtime_raw)
    require(
        canonical(runtime_raw) == canonical(runtime.model_dump(mode="json")),
        "complete runtime config required",
    )
    require(
        runtime.runtime_id == config.runtime_id,
        "local profile/runtime identity mismatch",
    )
    release = strict_json(
        pinned_local_file(
            config.adapter_release_manifest_path,
            config.adapter_release_manifest_sha256,
            256 * 1024,
        ),
        256 * 1024,
    )
    require(type(release) is dict, "pinned opaque release record must be an object")
    return InstalledProfilePins(str(path), expected_sha, config, runtime)


def validate_envelope(spec, profile, *, check_executables=True):
    require(
        spec.kind == "qe_initialize",
        "PBEsol execution currently supports initialization only",
    )
    require(
        spec.runtime_id == profile.config.runtime_id,
        "PBEsol installed runtime mismatch",
    )
    require(
        spec.max_attempts == 1
        and spec.resources.cpu_cores <= profile.runtime.max_cpu_cores
        and spec.resources.wall_seconds <= profile.runtime.max_wall_seconds
        and spec.resources.memory_bytes <= profile.runtime.max_memory_bytes,
        "PBEsol runtime envelope exceeded",
    )
    require(len(spec.input_artifacts) in {7, 8}, "PBEsol staged inventory count")
    require(
        sum(pin.bytes for pin in spec.input_artifacts) <= MAX_TOTAL_BYTES,
        "PBEsol staged total cap",
    )
    for pin in spec.input_artifacts:
        require(pin.name in ARTIFACT_NAMES, "PBEsol staged basename")
        require(
            pin.bytes
            <= (MAX_UPF_BYTES if pin.name.endswith(".upf") else MAX_METADATA_BYTES),
            "PBEsol staged file cap",
        )
    require(
        {rule.name for rule in spec.output_rules} == set(OUTPUT_CAPS),
        "PBEsol output inventory",
    )
    require(
        all(rule.max_bytes <= OUTPUT_CAPS[rule.name] for rule in spec.output_rules),
        "PBEsol output cap",
    )
    if check_executables:
        profile.runtime.validate_job(spec)


def read_staged(spec, work, profile):
    validate_envelope(spec, profile)
    for path in (work, work / "pseudo", work / "out", work / "tmp"):
        require(
            path.is_dir() and not path.is_symlink() and not path.stat().st_mode & 0o077,
            "PBEsol staged directories must be real owner-only directories",
        )
    for name in ("out", "tmp"):
        require(
            next((work / name).iterdir(), None) is None,
            "PBEsol initialization requires fresh empty scratch",
        )
    files = {
        pin.name: read_regular(
            work / "pseudo" / pin.name
            if pin.name.endswith(".upf")
            else work / pin.name,
            pin.bytes,
        )
        for pin in spec.input_artifacts
    }
    return validate_pbesol_inputs(
        spec, files, expected_runtime_id=profile.config.runtime_id
    )


def read_archived(spec, attempt_dir, profile):
    # Original downloaded bytes survive rejected or modified solver work files.
    validate_envelope(spec, profile, check_executables=False)
    files = {
        pin.name: read_regular(attempt_dir / "input-evidence" / pin.name, pin.bytes)
        for pin in spec.input_artifacts
    }
    return validate_pbesol_inputs(
        spec, files, expected_runtime_id=profile.config.runtime_id
    )


def descriptor_data(projection, profile):
    return {
        "schema_version": "sclib-pbesol-local-descriptor/1",
        "input_name": projection.input_name,
        "prefix": projection.prefix,
        "source_manifest_name": projection.source_manifest_name,
        "pseudo_names": list(projection.pseudo_names),
        "source_id": projection.source_id,
        "preparation_phase": projection.preparation_phase,
        "job_spec_sha256": projection.job_spec_sha256,
        "input_manifest_sha256": projection.input_manifest_sha256,
        "input_binding": {
            "name": projection.binding_name,
            "bytes": projection.binding_byte_length,
            "sha256": projection.binding_sha256,
        },
        "local_profile": profile.identity(),
    }


class PbesolWorker(NativeWorker):
    capabilities = ("qe_initialize",)
    guardian_module = "sclib_compute.pbesol_supervisor"

    def __init__(self, client, root, profile_path, profile_sha256):
        self.profile = load_profile(profile_path, profile_sha256)
        super().__init__(client, root, self.profile.runtime)

    def reload_profile(self):
        current = load_profile(self.profile.path, self.profile.sha256)
        require(current == self.profile, "PBEsol installed profile changed")
        return current

    def validate_input(self, spec, files):
        profile = self.reload_profile()
        validate_envelope(spec, profile)
        return validate_pbesol_inputs(
            spec, files, expected_runtime_id=profile.config.runtime_id
        )

    def descriptor_data(self, descriptor):
        return descriptor_data(descriptor, self.profile)

    def retain_inputs(self, spec, files, attempt_dir):
        archive = attempt_dir / "input-evidence"
        directory(archive)
        for pin in spec.input_artifacts:
            target = archive / pin.name
            if target.exists():
                require(
                    read_regular(target, pin.bytes) == files[pin.name],
                    "PBEsol immutable input evidence changed",
                )
            else:
                write_once(target, files[pin.name])

    def execution_context(self):
        return {**super().execution_context(), "local_profile": self.profile.identity()}

    def read_descriptor(self, spec, attempt_dir):
        profile = self.reload_profile()
        projection = read_archived(spec, attempt_dir, profile)
        expected = descriptor_data(projection, profile)
        saved = strict_json(read_regular(attempt_dir / "descriptor.json", 8192), 8192)
        require(
            canonical(saved) == canonical(expected), "PBEsol saved descriptor changed"
        )
        return expected

    def validate_recovery(self, state, spec, attempt_dir):
        validate_envelope(
            spec,
            self.reload_profile(),
            check_executables=not state.get("execution_started"),
        )
        require(
            not state.get("outbox") or state.get("execution_started"),
            "PBEsol outbox lacks execution identity",
        )
        if state.get("execution_started"):
            started = state["execution_started"]
            require(
                set(started) == {"at_unix", "runtime", "local_profile"},
                "PBEsol execution identity absent",
            )
            require(
                canonical({k: started[k] for k in ("runtime", "local_profile")})
                == canonical(self.execution_context()),
                "PBEsol recovery runtime/release identity differs",
            )
            descriptor = self.read_descriptor(spec, attempt_dir)
            final_path = attempt_dir / "execution-final.json"
            if final_path.exists():
                frozen = strict_json(
                    read_regular(final_path, OUTPUT_CAPS["execution.json"]),
                    OUTPUT_CAPS["execution.json"],
                )
                expected = self.execution_metadata(dict(frozen), descriptor)
                require(
                    canonical(expected) == canonical(frozen),
                    "PBEsol frozen execution profile differs",
                )
                require(
                    frozen["runtime_pins"] == started["runtime"]
                    and frozen["runtime_id"] == spec.runtime_id
                    and frozen["runtime_config_sha256"] == digest(started["runtime"])
                    and frozen["input_manifest_sha256"] == spec.input_manifest_sha256
                    and frozen["input_manifest"]
                    == [pin.model_dump(mode="json") for pin in spec.input_artifacts]
                    and frozen["job_id"] == spec.job_id
                    and frozen["attempt_id"] == state["claim"]["attempt"]["attempt_id"]
                    and frozen["fencing_token"]
                    == state["claim"]["attempt"]["fencing_token"],
                    "PBEsol frozen execution identity differs",
                )
                if state.get("outbox"):
                    require(
                        read_regular(
                            attempt_dir / "return/execution.json",
                            OUTPUT_CAPS["execution.json"],
                        )
                        == canonical(frozen),
                        "PBEsol outbox execution differs from frozen return",
                    )
                    completion = Completion.model_validate(
                        state["outbox"]["completion"]
                    )
                    require(
                        completion.runtime_id == spec.runtime_id
                        and completion.input_manifest_sha256
                        == spec.input_manifest_sha256
                        and completion.fencing_token
                        == state["claim"]["attempt"]["fencing_token"]
                        and completion.elapsed_seconds == frozen["elapsed_seconds"]
                        and completion.solver_outcome == frozen["solver_outcome"],
                        "PBEsol saved Completion identity differs",
                    )
                    rules = {rule.name: rule.max_bytes for rule in spec.output_rules}
                    require(
                        [pin.name for pin in completion.manifest] == sorted(rules)
                        and all(
                            pin.bytes <= rules[pin.name] for pin in completion.manifest
                        ),
                        "PBEsol saved Completion output inventory differs",
                    )
            elif state.get("outbox"):
                raise ValueError("PBEsol outbox lacks frozen execution")

    def guardian_args(self):
        return [
            "--profile-config",
            self.profile.path,
            "--profile-sha256",
            self.profile.sha256,
        ]

    def guardian_request(self, request):
        return {
            **request,
            "local_profile": self.profile.identity(),
            "launch_deadline_unix": min(
                time.time() + request["remaining_wall_seconds"],
                request["spec"]["deadline_unix"],
            ),
        }

    @staticmethod
    def xml_parseable(xml):
        try:
            ET.fromstring(decode_supported_xml(xml))
            return True
        except (ValueError, ET.ParseError):
            return False

    def execution_metadata(self, execution, descriptor):
        execution.update(
            schema_version="sclib-pbesol-qe-execution/1",
            adapter_version="pbesol-qe/1",
            input_binding=descriptor["input_binding"],
            method_profile="pbesol-source-coarse-qe75/1",
            source_id=descriptor["source_id"],
            preparation_phase=descriptor["preparation_phase"],
            adapter_release_manifest_sha256=self.profile.config.adapter_release_manifest_sha256,
        )
        return execution

    def validate_frozen_execution(self, frozen, current):
        require(
            type(frozen.get("elapsed_seconds")) is int
            and math.ceil(current["process"]["elapsed_seconds"])
            <= frozen["elapsed_seconds"]
            <= 86400,
            "PBEsol frozen elapsed invalid",
        )
        require(
            canonical({k: v for k, v in frozen.items() if k != "elapsed_seconds"})
            == canonical({k: v for k, v in current.items() if k != "elapsed_seconds"}),
            "PBEsol frozen capture changed during recovery",
        )
