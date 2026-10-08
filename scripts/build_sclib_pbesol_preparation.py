"""Prepare four pinned PBEsol source models offline; execution support is pending."""

from __future__ import annotations

import argparse
import copy
import ctypes
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import xml.etree.ElementTree as ET
from decimal import Decimal, localcontext
from pathlib import Path, PurePosixPath

PROFILE = Path(__file__).resolve().parents[1] / "docs/data/discovery-batches-20261008/pbesol-source-profile-v1.json"
PROFILE_SHA256 = "4c0d2f406bdb200b88f01299074ce200e331c56952d07fdc8354621b807b263c"
SCHEMA = "sclib-pbesol-source-preparation/1"
NML = {
    "CONTROL": {"calculation", "etot_conv_thr", "forc_conv_thr", "outdir", "prefix", "pseudo_dir", "restart_mode", "tprnfor", "tstress"},
    "SYSTEM": {"celldm(1)", "celldm(3)", "degauss", "ecutwfc", "ibrav", "la2f", "occupations", "smearing", "nat", "ntyp"},
    "ELECTRONS": {"conv_thr", "diagonalization", "electron_maxstep", "mixing_beta", "mixing_mode"},
    "IONS": {"ion_dynamics"}, "CELL": {"cell_dynamics", "press_conv_thr"},
}
NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eEdD][+-]?\d+)?"
ASSIGN = re.compile(r"\s*([a-z_][a-z0-9_]*(?:\(\d+\))?)\s*=\s*('(?:[^']|'')*'|\.(?:TRUE|FALSE)\.|" + NUMBER + r")\s*,?\s*", re.IGNORECASE)
AUTHORITY = {"execution_supported": False, "native_profile_pending": True, "queue_authorization": False,
             "calculation_executed": False, "budget_reserved": 0, "scientific_publication_authority": False,
             "candidate_grade_changed": False, "tc_calculated": False}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def encoded(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()


def safe_relative(value: str) -> PurePosixPath:
    require(bool(value) and "\\" not in value and all(x not in {"", ".", ".."} for x in value.split("/")), "Expected normalized relative path")
    result = PurePosixPath(value)
    require(not result.is_absolute(), "Expected normalized relative path")
    return result


def check_directory(path: Path) -> None:
    require(path.is_dir(), "Required directory is missing")
    for ancestor in [path.absolute(), *path.absolute().parents]:
        require(not ancestor.is_symlink(), "Symlink directories are forbidden")


def read_regular(root: Path, relative: str) -> bytes:
    check_directory(root)
    parts = safe_relative(relative).parts
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
        with os.fdopen(fd, "rb") as handle:
            info = os.fstat(handle.fileno())
            require(stat.S_ISREG(info.st_mode) and info.st_size <= 2_000_000, "Expected bounded regular source file")
            data = handle.read(2_000_001)
            require(len(data) <= 2_000_000, "Source file exceeded size limit")
            return data
    finally:
        os.close(descriptor)


def check_pin(data: bytes, pin: dict) -> None:
    require(len(data) == pin["bytes"] and sha256(data) == pin["sha256"], "Pinned source bytes changed")


def load_profile() -> dict:
    raw = read_regular(PROFILE.parent, PROFILE.name)
    require(sha256(raw) == PROFILE_SHA256, "Pinned public source profile changed")
    return json.loads(raw)


def scalar(literal: str):
    if literal.startswith("'"):
        return literal[1:-1].replace("''", "'")
    if literal.upper() in {".TRUE.", ".FALSE."}:
        return literal.upper() == ".TRUE."
    require(bool(re.fullmatch(NUMBER, literal)), "Unsupported numeric literal")
    value = Decimal(literal.lower().replace("d", "e"))
    require(value.is_finite() and abs(value) < Decimal("1e100"), "Unbounded/nonfinite number")
    return value


def parse_source(data: bytes, state: dict) -> dict:
    """Only the pinned historical coarse grammar, never an execution validator."""
    lines = data.decode("utf-8").splitlines(keepends=True)
    require(bool(lines) and all(line.endswith("\n") and "\r" not in line for line in lines), "Expected LF terminated source lines")
    groups, blocks, cards = {}, {}, {}
    group = mode = None
    for i, raw in enumerate(lines, 1):
        text = raw.strip()
        if not text:
            continue
        if group:
            if text == "/":
                blocks[group]["end"] = i
                group = None
                continue
            match = ASSIGN.fullmatch(text)
            require(match is not None, f"Unsupported source primitive on line {i}")
            key, literal = match.groups()
            key = key.lower()
            require(key in NML[group] and key not in groups[group], "Unsupported/duplicate source field: " + key)
            scalar(literal)
            groups[group][key] = {"literal": literal, "line": i}
        elif text.startswith("&"):
            group = text[1:]
            require(mode is None and group in NML and group not in groups, "Unsupported/duplicate namelist")
            groups[group], blocks[group] = {}, {"start": i}
        elif text in {"ATOMIC_SPECIES", "ATOMIC_POSITIONS crystal", "K_POINTS automatic"}:
            mode = text
            require(mode not in cards, "Duplicate source card")
            cards[mode] = []
        else:
            require(mode is not None, "Unsupported source card")
            cards[mode].append({"line": i, "text": raw.rstrip("\n")})
    require(group is None and list(groups) == list(NML), "Missing/unclosed/reordered source namelist")
    require(list(cards) == ["ATOMIC_SPECIES", "ATOMIC_POSITIONS crystal", "K_POINTS automatic"], "Missing/unsupported source card")
    expected = {
        "CONTROL": {"calculation": "scf", "etot_conv_thr": Decimal("1e-8"), "forc_conv_thr": Decimal("1e-6"), "outdir": "outdir", "prefix": "qe", "restart_mode": "from_scratch", "tprnfor": True, "tstress": True},
        "SYSTEM": {"ibrav": Decimal(state["ibrav"]), "nat": Decimal(4), "ntyp": Decimal(len(state["species_rows"])), "degauss": Decimal("0.014699728870262"), "ecutwfc": Decimal(state["ecutwfc_ry"]), "la2f": False, "occupations": "smearing", "smearing": "mp", **{k: Decimal(v) for k, v in state["celldm_literals"].items()}},
        "ELECTRONS": {"conv_thr": Decimal("1e-12"), "diagonalization": "david", "mixing_beta": Decimal("0.7"), "mixing_mode": "plain"},
        "IONS": {"ion_dynamics": "bfgs"}, "CELL": {"cell_dynamics": "bfgs", "press_conv_thr": Decimal("0.05")},
    }
    if state["source_electron_maxstep"] is not None:
        expected["ELECTRONS"]["electron_maxstep"] = Decimal(state["source_electron_maxstep"])
    require("pseudo_dir" in groups["CONTROL"], "Missing source pseudo_dir")
    original_pseudo_dir = scalar(groups["CONTROL"]["pseudo_dir"]["literal"])
    require(type(original_pseudo_dir) is str and original_pseudo_dir.startswith("/") and "\x00" not in original_pseudo_dir, "Unexpected historical pseudo_dir")
    expected["CONTROL"]["pseudo_dir"] = original_pseudo_dir  # Inert source metadata only.
    for name, fields in expected.items():
        require(set(groups[name]) == set(fields), "Missing/extra source fields in " + name)
        for key, value in fields.items():
            found = scalar(groups[name][key]["literal"])
            require(type(found) is type(value) and found == value, "Source method mismatch: " + key)
    require([r["text"] for r in cards["ATOMIC_SPECIES"]] == state["species_rows"], "Source species/order/mass changed")
    require([r["text"] for r in cards["ATOMIC_POSITIONS crystal"]] == state["position_rows"], "Source coordinates/order changed")
    krows = cards["K_POINTS automatic"]
    require(len(krows) == 1 and krows[0]["text"].split() == [str(x) for x in [*state["mesh"], 0, 0, 0]], "Source k mesh/shift changed")
    return {"namelists": groups, "blocks": blocks, "cards": cards}


def validate_upf(data: bytes, pin: dict) -> dict:
    check_pin(data, pin)
    require(hashlib.md5(data).hexdigest() == pin["md5"], "UPF MD5 mismatch")
    require(b"<!DOCTYPE" not in data.upper() and b"<!ENTITY" not in data.upper(), "UPF XML declarations forbidden")
    root = ET.fromstring(data)
    headers = root.findall("PP_HEADER")
    require(root.tag == "UPF" and root.attrib.get("version") == "2.0.1" and len(headers) == 1, "Unsupported UPF structure")
    h = headers[0].attrib
    required = {"element": pin["element"], "functional": "PBESOL", "pseudo_type": "NC", "relativistic": "scalar", "is_ultrasoft": "F", "is_paw": "F", "has_so": "F"}
    require(all(h.get(k) == v for k, v in required.items()), "UPF element/XC/type/relativity mismatch")
    require(scalar(h["z_valence"].strip()) == Decimal(pin["valence_electrons"]), "UPF valence mismatch")
    return h


def geometry(state: dict) -> dict:
    """Exact-decimal ibrav2/6 row bases from audited QE latgen; no inverse/wrapping."""
    with localcontext() as ctx:
        ctx.prec = 60
        a = Decimal(state["celldm_literals"]["celldm(1)"])
        zero = Decimal(0)
        if state["ibrav"] == 2:
            basis = [[-a / 2, zero, a / 2], [zero, a / 2, a / 2], [-a / 2, a / 2, zero]]
        else:
            require(state["ibrav"] == 6, "Unsupported Bravais representation")
            basis = [[a, zero, zero], [zero, a, zero], [zero, zero, a * Decimal(state["celldm_literals"]["celldm(3)"])]]
        atoms = []
        for i, row in enumerate(state["position_rows"]):
            element, *coords = row.split()
            fractions = [Decimal(x) for x in coords]
            cart = [sum(fractions[k] * basis[k][j] for k in range(3)) for j in range(3)]
            atoms.append({"source_atom_index": i + 1, "element": element, "fractional_literals": coords, "cartesian_bohr_decimal": list(map(str, cart))})
    return {"ibrav": state["ibrav"], "celldm_literals": state["celldm_literals"], "cell_vectors_bohr_decimal": [list(map(str, row)) for row in basis], "atoms": atoms, "species_rows": state["species_rows"], "normalization": "none; original fractions and order retained", "matrix_origin": "Static QE7.5 latgen row basis; not measured XML"}


def derive(data: bytes, parsed: dict, state: dict, phase: str) -> tuple[bytes, dict, dict]:
    require(phase in {"initialize", "scf"}, "Unsupported preparation phase")
    prefix = f"sclib_pbesol_{state['id']}_{phase}"
    require(re.fullmatch(r"[a-z0-9_]{1,64}", prefix) is not None, "Unsafe derived prefix")
    additions = {"CONTROL": {"nstep": "0" if phase == "initialize" else "1", "max_seconds": "600"},
                 "SYSTEM": {"ecutrho": str(state["ecutrho_ry"]), "nbnd": str(state["nbnd"]), "nspin": "1", "noncolin": ".FALSE.", "lspinorb": ".FALSE.", "tot_charge": "0"}, "ELECTRONS": {}}
    if state["source_electron_maxstep"] is None:
        additions["ELECTRONS"]["electron_maxstep"] = "100"
    replacements = {"outdir": "'./out'", "pseudo_dir": "'./pseudo'", "prefix": f"'{prefix}'"}
    rules = {}
    for group in ["IONS", "CELL"]:
        block = parsed["blocks"][group]
        for line in range(block["start"], block["end"] + 1):
            rules[line] = (None, "Remove source " + group + ": SCF has no enabled ionic/cell dynamics; metadata/default change logged")
    for key in ["etot_conv_thr", "forc_conv_thr"]:
        rules[parsed["namelists"]["CONTROL"][key]["line"]] = (None, "Remove parsed but inactive SCF ionic threshold; metadata/default change, electronic conv_thr retained")
    for key, value in replacements.items():
        rules[parsed["namelists"]["CONTROL"][key]["line"]] = (f"  {key} = {value},\n", "Safe isolated path/prefix relocation; source bytes retained")
    inserts = {parsed["blocks"][group]["end"]: fields for group, fields in additions.items()}
    ledger, output = [], []
    for i, before in enumerate(data.decode().splitlines(keepends=True), 1):
        for key, value in inserts.get(i, {}).items():
            after = f"  {key} = {value},\n"
            reason = ("Explicit source-output effective value" if key in {"ecutrho", "nbnd"} else
                      "Declared QE7.5 electron_maxstep=100; omitted by this historical source" if key == "electron_maxstep" else
                      "Declared scalar neutral nonmagnetic probe assumption; not experimental evidence" if key in {"nspin", "noncolin", "lspinorb", "tot_charge"} else
                      "Explicit initialization/SCF phase or new bounded engine guard; no queue authorization")
            output.append(after)
            ledger.append({"action": "insert", "source_line": None, "source_anchor_line": i, "derived_line": len(output), "before": None, "after": after, "reason": reason})
        after, reason = rules.get(i, (before, "Retained byte-for-byte"))
        action = "delete" if after is None else "retain" if after == before else "replace"
        if after is not None:
            output.append(after)
        ledger.append({"action": action, "source_line": i, "derived_line": len(output) if after is not None else None, "before": before, "after": after, "reason": reason})
    derived = "".join(output).encode()
    require("".join(x["before"] for x in ledger if x["before"] is not None).encode() == data, "Incomplete source delta coverage")
    require("".join(x["after"] for x in ledger if x["after"] is not None).encode() == derived, "Incomplete derived delta coverage")
    settings = {name: {key: item["literal"] for key, item in fields.items()} for name, fields in parsed["namelists"].items() if name not in {"IONS", "CELL"}}
    for key in ["etot_conv_thr", "forc_conv_thr"]:
        settings["CONTROL"].pop(key)
    settings["CONTROL"].update(replacements)
    for name, fields in additions.items():
        settings[name].update(fields)
    delta = {"schema_version": "sclib-pbesol-line-delta/1", "source_sha256": sha256(data), "derived_sha256": sha256(derived), "complete_source_and_derived_line_coverage": True, "entries": ledger}
    return derived, delta, {"prefix": prefix, "namelist_literals": settings, "mesh": state["mesh"], "shifts": [0, 0, 0]}


def publish_exclusive(staging: Path, output: Path) -> None:
    """Atomic directory publication without replacing even a newly created empty target."""
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin" and hasattr(libc, "renamex_np"):
        func = libc.renamex_np
        func.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        result = func(os.fsencode(staging), os.fsencode(output), 4)  # RENAME_EXCL
    elif sys.platform.startswith("linux") and hasattr(libc, "renameat2"):
        func = libc.renameat2
        func.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        result = func(-100, os.fsencode(staging), -100, os.fsencode(output), 1)  # AT_FDCWD, RENAME_NOREPLACE
    else:
        raise ValueError("Atomic no-replace publication requires supported macOS/Linux libc")
    if result != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), str(output))


def build(source_root: Path, upf_root: Path, output: Path) -> dict:
    require(not output.exists() and not output.is_symlink(), "Output must be new; existing preparations are immutable")
    check_directory(source_root)
    check_directory(upf_root)
    check_directory(output.parent)
    profile = load_profile()
    upf_bytes, headers = {}, {}
    for pin in profile["upfs"]:
        content = read_regular(upf_root, pin["filename"])
        headers[pin["element"]] = validate_upf(content, pin)
        upf_bytes[pin["element"]] = content
    sources = []
    for state in profile["states"]:
        content = read_regular(source_root, state["source_deck"]["path"])
        check_pin(content, state["source_deck"])
        parsed = parse_source(content, state)
        electrons = sum(scalar(headers[row.split()[0]]["z_valence"].strip()) for row in state["position_rows"])
        require(electrons == Decimal(state["valence_electrons"]), "Composition-weighted UPF electron mismatch")
        sources.append((state, content, parsed))
    staging = Path(tempfile.mkdtemp(prefix=".pbesol-preparation-", dir=output.parent))
    written = []

    def save(relative: str, content: bytes) -> dict:
        parts = safe_relative(relative).parts
        parent = staging
        for part in parts[:-1]:
            parent = parent / part
            parent.mkdir(mode=0o700, exist_ok=True)
        target = parent / parts[-1]
        with target.open("xb") as handle:
            os.chmod(target, 0o600)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        pin = {"path": relative, "bytes": len(content), "sha256": sha256(content)}
        written.append(pin)
        return pin

    try:
        save("source-profile.json", encoded(profile))
        for pin in profile["upfs"]:
            save("source/upf/" + pin["filename"], upf_bytes[pin["element"]])
        preparations = []
        for state, content, parsed in sources:
            source_pin = save(f"source/{state['id']}/scf_coarse.in", content)
            geom = geometry(state)
            source_settings = {name: {key: item["literal"] for key, item in fields.items()} for name, fields in parsed["namelists"].items()}
            for phase in ["initialize", "scf"]:
                directory = f"prepared/{state['id']}/{phase}"
                derived, delta, settings = derive(content, parsed, state, phase)
                input_pin = save(directory + "/input.in", derived)
                delta_pin = save(directory + "/delta.json", encoded(delta))
                selected = []
                for pin in profile["upfs"]:
                    if pin["element"] in {row.split()[0] for row in state["species_rows"]}:
                        new_pin = save(directory + "/pseudo/" + pin["filename"], upf_bytes[pin["element"]])
                        selected.append({**pin, "prepared_file": new_pin, "validated_header": headers[pin["element"]]})
                manifest = {"schema_version": SCHEMA, "status": "native_profile_pending", **AUTHORITY,
                            "source_id": state["id"], "formula": state["formula"], "role": state["role"], "preparation_phase": phase,
                            "source_dataset": profile["source_dataset"], "qe75_source_audit": profile["qe75_source_audit"],
                            "source_qe_version": state["source_qe_version"], "proposed_qe_version": "7.5",
                            "cross_version_scope": "Independent source-method port; historical executables/compiler/MPI/BLAS not recovered",
                            "source_file": source_pin, "derived_file": input_pin, "line_delta": delta_pin,
                            "geometry": {"source": geom, "derived": copy.deepcopy(geom), "source_sha256": sha256(encoded(geom)), "derived_sha256": sha256(encoded(geom)), "changed": False},
                            "source_namelist_literals": source_settings, "derived_settings": settings,
                            "expected_valence_electrons": state["valence_electrons"], "expected_nbnd": state["nbnd"],
                            "xc_from_exact_upfs": "PBESOL", "pseudopotentials": selected,
                            "native_manifest": None, "job_spec": None,
                            "required_before_execution": ["Reviewed distinct PBEsol reader and native profile", "Compatibility and initialization acceptance", "Fresh attempt directory and measured per-stage resource admission"]}
                pin = save(directory + "/preparation-manifest.json", encoded(manifest))
                preparations.append({"source_id": state["id"], "phase": phase, "manifest": pin, "input": input_pin})
        bundle = {"schema_version": "sclib-pbesol-preparation-bundle/1", "status": "native_profile_pending", **AUTHORITY,
                  "source_profile_sha256": PROFILE_SHA256, "preparer_sha256": sha256(Path(__file__).read_bytes()),
                  "preparations": preparations, "files": list(written)}
        manifest_pin = save("bundle-manifest.json", encoded(bundle))
        save("SHA256SUMS", "".join(f"{pin['sha256']}  {pin['path']}\n" for pin in written).encode())
        publish_exclusive(staging, output)
        return {"schema_version": "sclib-pbesol-preparation-result/1", "bundle_manifest": manifest_pin, "prepared_decks": 8, **AUTHORITY}
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True, type=Path, help="Directory containing the four Formula_agm*/scf_coarse.in source files")
    parser.add_argument("--upf-root", required=True, type=Path, help="Directory containing exact Ti.upf, Nb.upf, Mo.upf and Ta.upf")
    parser.add_argument("--output", required=True, type=Path, help="New output directory; its parent must already exist")
    args = parser.parse_args()
    print(json.dumps(build(args.source_root, args.upf_root, args.output)))


if __name__ == "__main__":
    main()
