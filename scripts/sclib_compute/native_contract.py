"""Strict, from-scratch QE subset for the first native queue integration.

Transport success and an SCF stopping condition are not scientific validation.
Only decks produced by the existing discovery-qe-input/1.0.0 preparer are accepted.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import subprocess
import sys
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .contracts import Closed, Identifier, JobSpec, Sha256

OUTPUT_NAMES = {"stdout.txt", "stderr.txt", "data-file-schema.xml", "execution.json"}
NUMBER = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eEdD][+-]?\d+)?$")


class NativeInput(Closed):
    schema_version: Literal["sclib-native-qe/1"] = "sclib-native-qe/1"
    input_name: Identifier
    source_manifest_name: Identifier
    prefix: Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,63}$")]
    pseudo_names: Annotated[list[Identifier], Field(min_length=1, max_length=8)]

    @model_validator(mode="after")
    def unique(self):
        names = [
            "native.json",
            self.input_name,
            self.source_manifest_name,
            *self.pseudo_names,
        ]
        if len(set(names)) != len(names) or any(n in {".", ".."} for n in names):
            raise ValueError("native input names must be unique basenames")
        return self


class ExecutablePin(Closed):
    path: str
    sha256: Sha256


class NativeRuntime(Closed):
    schema_version: Literal["sclib-native-runtime/1"] = "sclib-native-runtime/1"
    runtime_id: Identifier
    pw: ExecutablePin
    mpiexec: ExecutablePin
    max_cpu_cores: Annotated[int, Field(ge=1, le=4)] = 4
    max_wall_seconds: Annotated[int, Field(ge=1, le=3600)] = 900
    max_memory_bytes: Annotated[int, Field(ge=1024**2, le=16 * 1024**3)] = 12 * 1024**3
    max_scratch_bytes: Annotated[int, Field(ge=1024**2, le=32 * 1024**3)] = 4 * 1024**3
    min_free_bytes: Annotated[int, Field(ge=1024**2)] = 20 * 1024**3
    min_available_memory_bytes: Annotated[int, Field(ge=1024**2)] = 24 * 1024**3
    heartbeat_seconds: Annotated[int, Field(ge=1, le=15)] = 5

    def validate_job(self, spec: JobSpec):
        if (
            spec.kind not in {"qe_initialize", "qe_scf"}
            or spec.runtime_id != self.runtime_id
        ):
            raise ValueError("native runtime/capability mismatch")
        if spec.max_attempts != 1:
            raise ValueError(
                "initial native jobs require one attempt; no automatic rerun"
            )
        if (
            spec.resources.cpu_cores > self.max_cpu_cores
            or spec.resources.wall_seconds > self.max_wall_seconds
            or spec.resources.memory_bytes > self.max_memory_bytes
        ):
            raise ValueError("job exceeds local native envelope")
        if {r.name for r in spec.output_rules} != OUTPUT_NAMES:
            raise ValueError("native output contract mismatch")
        for pin in [self.pw, self.mpiexec]:
            executable(pin)


def read_regular(path: Path, maximum: int) -> bytes:
    for parent in [path, *path.parents]:
        if parent.is_symlink():
            raise ValueError("symlink in native artifact path")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > maximum:
            raise ValueError("native artifact is nonregular or too large")
        data = stream.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError("native artifact grew above limit")
    return data


def available_memory_bytes() -> int:
    """Conservative actual launch gate; no total-RAM substitution on failure."""
    if sys.platform == "darwin":
        result = subprocess.run(
            ["/usr/bin/vm_stat"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
        )
        match = re.search(r"page size of (\d+) bytes", result.stdout)
        values = {}
        for line in result.stdout.splitlines():
            field = re.fullmatch(
                r"(Pages free|Pages inactive|Pages speculative):\s+(\d+)\.", line
            )
            if field:
                values[field[1]] = int(field[2])
        if match and len(values) == 3:
            return int(match[1]) * sum(values.values())
    elif sys.platform.startswith("linux"):
        match = re.search(
            r"^MemAvailable:\s+(\d+) kB$",
            Path("/proc/meminfo").read_text(),
            re.MULTILINE,
        )
        if match:
            return int(match[1]) * 1024
    raise ValueError("actual available memory could not be established")


def executable(pin: ExecutablePin) -> Path:
    path = Path(pin.path)
    if not path.is_absolute():
        raise ValueError("runtime executable needs absolute resolved path")
    data = read_regular(path, 512 * 1024**2)
    if path.stat().st_mode & 0o022 or not os.access(path, os.X_OK):
        raise ValueError(
            "runtime executable must be executable and not group/world writable"
        )
    if hashlib.sha256(data).hexdigest() != pin.sha256:
        raise ValueError("runtime executable checksum mismatch")
    return path


def number(value):
    if not NUMBER.fullmatch(value):
        raise ValueError("invalid QE numeric token")
    result = float(value.lower().replace("d", "e"))
    if not math.isfinite(result):
        raise ValueError("nonfinite QE number")
    return result


def validate_inputs(spec: JobSpec, files: dict[str, bytes]) -> NativeInput:
    descriptor = NativeInput.model_validate_json(files["native.json"])
    expected = {
        "native.json",
        descriptor.input_name,
        descriptor.source_manifest_name,
        *descriptor.pseudo_names,
    }
    if set(files) != expected or expected != {p.name for p in spec.input_artifacts}:
        raise ValueError("native input set differs from descriptor")
    for pin in spec.input_artifacts:
        data = files[pin.name]
        if len(data) != pin.bytes or hashlib.sha256(data).hexdigest() != pin.sha256:
            raise ValueError("native input checksum mismatch")
    manifest = json.loads(files[descriptor.source_manifest_name])
    if (
        manifest.get("version") != "discovery-qe-input/1.0.0"
        or manifest.get("settings", {}).get("calculation") != "scf"
    ):
        raise ValueError("unsupported QE source manifest")
    mode = "initialization" if spec.kind == "qe_initialize" else "execution"
    source = manifest["files"][mode]
    if (
        source["filename"] != descriptor.input_name
        or source["sha256"] != hashlib.sha256(files[descriptor.input_name]).hexdigest()
    ):
        raise ValueError("source manifest does not bind exact selected deck")
    pseudos = manifest["pseudopotentials"]
    if len(pseudos) != len(descriptor.pseudo_names) or {
        p["filename"] for p in pseudos
    } != set(descriptor.pseudo_names):
        raise ValueError("source manifest pseudo set mismatch")
    for pseudo in pseudos:
        data = files[pseudo["filename"]]
        if (
            len(data) != pseudo["byte_length"]
            or hashlib.sha256(data).hexdigest() != pseudo["sha256"]
        ):
            raise ValueError("source UPF hash/length mismatch")
    validate_deck(files[descriptor.input_name], descriptor, spec.kind)
    return descriptor


def validate_deck(data: bytes, descriptor: NativeInput, kind: str):
    """Closed grammar rejects new namelists, file paths and unreviewed QE options."""
    if len(data) > 256 * 1024:
        raise ValueError("QE deck too large")
    text = data.decode("ascii")
    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("!")
    ]
    schemas = {
        "CONTROL": {
            "calculation",
            "restart_mode",
            "prefix",
            "pseudo_dir",
            "outdir",
            "nstep",
            "max_seconds",
            "tprnfor",
            "tstress",
        },
        "SYSTEM": {
            "ibrav",
            "nat",
            "ntyp",
            "ecutwfc",
            "ecutrho",
            "tot_charge",
            "nspin",
            "noncolin",
            "lspinorb",
            "occupations",
            "smearing",
            "degauss",
        },
        "ELECTRONS": {
            "conv_thr",
            "electron_maxstep",
            "mixing_beta",
            "diagonalization",
            "startingpot",
            "startingwfc",
        },
    }
    parsed, index = {}, 0
    for section, keys in schemas.items():
        if index >= len(lines) or lines[index] != "&" + section:
            raise ValueError("unsupported QE namelist order")
        index += 1
        values = {}
        while index < len(lines) and lines[index] != "/":
            match = re.fullmatch(r"([a-z_]+)\s*=\s*([^,]+),", lines[index])
            if not match or match[1] not in keys or match[1] in values:
                raise ValueError("unreviewed/duplicate QE assignment")
            values[match[1]] = match[2].strip()
            index += 1
        if set(values) != keys or index >= len(lines):
            raise ValueError("incomplete QE namelist")
        parsed[section] = values
        index += 1
    required = {
        "calculation": "'scf'",
        "restart_mode": "'from_scratch'",
        "prefix": repr(descriptor.prefix),
        "pseudo_dir": "'./pseudo'",
        "outdir": "'./out'",
        "nstep": "0" if kind == "qe_initialize" else "1",
        "tprnfor": ".true.",
        "tstress": ".true.",
        "ibrav": "0",
        "nspin": "1",
        "tot_charge": "0",
        "noncolin": ".false.",
        "lspinorb": ".false.",
        "occupations": "'smearing'",
        "diagonalization": "'david'",
        "startingpot": "'atomic'",
        "startingwfc": "'atomic+random'",
    }
    all_values = {k: v for values in parsed.values() for k, v in values.items()}
    for key, value in all_values.items():
        if key in required:
            if value != required[key]:
                raise ValueError("QE protected assignment mismatch: " + key)
        elif key == "smearing":
            if value not in {"'mv'", "'gaussian'", "'mp'", "'fd'"}:
                raise ValueError("unreviewed smearing")
        else:
            number(value)
    nat, ntyp = int(number(all_values["nat"])), int(number(all_values["ntyp"]))
    if not 1 <= nat <= 128 or not 1 <= ntyp <= 8:
        raise ValueError("native atom/species bound exceeded")
    if all_values["nat"] != str(nat) or all_values["ntyp"] != str(ntyp):
        raise ValueError("atom counts must be integers")
    if lines[index : index + 1] != ["ATOMIC_SPECIES"]:
        raise ValueError("missing species card")
    species = set()
    pseudo_names = set()
    for line in lines[index + 1 : index + 1 + ntyp]:
        parts = line.split()
        if (
            len(parts) != 3
            or not re.fullmatch("[A-Z][a-z]?", parts[0])
            or parts[2] not in descriptor.pseudo_names
        ):
            raise ValueError("invalid species/pseudo basename")
        if number(parts[1]) <= 0 or parts[0] in species:
            raise ValueError("invalid species mass or duplicate")
        species.add(parts[0])
        pseudo_names.add(parts[2])
    if len(species) != ntyp or pseudo_names != set(descriptor.pseudo_names):
        raise ValueError("incomplete species card")
    index += ntyp + 1
    if lines[index : index + 1] != ["CELL_PARAMETERS angstrom"]:
        raise ValueError("invalid cell card")
    for line in lines[index + 1 : index + 4]:
        if len(line.split()) != 3:
            raise ValueError("invalid cell vector")
        for token in line.split():
            number(token)
    index += 4
    if lines[index : index + 1] != ["ATOMIC_POSITIONS crystal"]:
        raise ValueError("invalid positions card")
    for line in lines[index + 1 : index + nat + 1]:
        parts = line.split()
        if len(parts) != 4 or parts[0] not in species:
            raise ValueError("invalid atomic position")
        for token in parts[1:]:
            number(token)
    index += nat + 1
    if lines[index : index + 1] != ["K_POINTS automatic"] or index + 2 != len(lines):
        raise ValueError("unreviewed trailing QE card")
    tokens = lines[index + 1].split()
    if len(tokens) != 6 or any(not re.fullmatch(r"\d+", token) for token in tokens):
        raise ValueError("invalid k mesh")
    if any(not 1 <= int(token) <= 64 for token in tokens[:3]) or any(
        token not in {"0", "1"} for token in tokens[3:]
    ):
        raise ValueError("k mesh outside native bound")
