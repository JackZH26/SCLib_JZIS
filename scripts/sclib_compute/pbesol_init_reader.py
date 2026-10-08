"""Offline initialization-only PBEsol reader.

Input truth is revalidated by the repository binding validator for every
call. Caller files/outputs are bounded in-memory bytes. No job, process, service,
filesystem loader, runtime attestation or scientific result is constructed here.
Validation uses synthetic outputs only; no actual runtime or result is accepted.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from sclib_compute.pbesol_profile import BUNDLE_SHA256, validate_input_binding

QES_NS = "http://www.quantum-espresso.org/ns/qes/qes-1.0"
FLOAT = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eEdD][+-]?\d+)?"
FRACTIONAL_TOLERANCE = 1e-8
MAX_ABS_FRACTIONAL_COORDINATE = 1024
MAX_ABS_LATTICE_SHIFT = 1024
BINARY64_EPSILON = 2**-52
MAX_XML = 8 * 1024**2
MAX_STDOUT = 8 * 1024**2
MAX_STDERR = 1024**2


@dataclass(frozen=True)
class _VerifiedPreparation:
    manifest: dict
    bundle_sha256: str
    manifest_sha256: str
    input_sha256: str
    upf_sha256: tuple
    expected_electrons: int


class Rejected(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(f"{code}: {message}")


def require(ok, code, message):
    if not ok:
        raise Rejected(code, message)


def sha(b):
    return hashlib.sha256(b).hexdigest()


def strict_number(raw, code="METHOD_SCALAR"):
    require(type(raw) is str and re.fullmatch(FLOAT, raw.strip()) is not None, code, "finite numeric text required")
    n = float(raw.strip().replace("d", "e").replace("D", "e"))
    require(math.isfinite(n), code, "nonfinite numeric text")
    return n


def strict_integer(raw, code="METHOD_SCALAR"):
    n = strict_number(raw, code)
    require(n >= 0 and n.is_integer() and n <= 2**53 - 1, code, "nonnegative safe integer required")
    return int(n)


def close(actual, expected, code="METHOD_SCALAR", rel=1e-10, absolute=0):
    require(
        math.isfinite(actual)
        and math.isfinite(expected)
        and abs(actual - expected) <= max(absolute, rel * abs(expected)),
        code,
        f"{actual} differs from {expected}",
    )


def inv3(matrix):
    require(
        type(matrix) in (list, tuple)
        and len(matrix) == 3
        and all(type(r) in (list, tuple) and len(r) == 3 for r in matrix),
        "STRUCTURE_BASIS",
        "3x3 rows required",
    )
    require(
        all(type(x) in (int, float) and math.isfinite(x) for r in matrix for x in r),
        "STRUCTURE_BASIS",
        "finite real matrix required",
    )
    a, b, c = matrix[0]
    d, e, f = matrix[1]
    g, h, i = matrix[2]
    det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    norms = [math.hypot(*r) for r in matrix]
    product = math.prod(norms)
    require(
        math.isfinite(det) and math.isfinite(product) and product > 0 and det > 0 and det / product > 1e-10,
        "STRUCTURE_CONDITION",
        "singular, left-handed or near-singular cell",
    )
    inverse = [
        [(e * i - f * h) / det, (c * h - b * i) / det, (b * f - c * e) / det],
        [(f * g - d * i) / det, (a * i - c * g) / det, (c * d - a * f) / det],
        [(d * h - e * g) / det, (b * g - a * h) / det, (a * e - b * d) / det],
    ]
    condition = max(sum(abs(x) for x in row) for row in matrix) * max(sum(abs(x) for x in row) for row in inverse)
    require(math.isfinite(condition) and condition <= 1e10, "STRUCTURE_CONDITION", "ill-conditioned cell")
    return inverse, det, condition


def one(node, path):
    for part in path.split("/"):
        found = [c for c in node if c.tag == part]
        require(len(found) != 0, "XML_MISSING", path)
        require(len(found) == 1, "XML_DUPLICATE", path)
        node = found[0]
    return node


def text(node, path):
    return (one(node, path).text or "").strip()


def eq(actual, expected, code):
    require(actual == expected, code, f"{actual!r} differs from {expected!r}")


def vector(node, code):
    tokens = (node.text or "").split()
    require(len(tokens) == 3, code, "3-vector required")
    return [strict_number(x, code) for x in tokens]


def check_structure(node, context):
    geom = context.manifest["geometry"]["source"]
    atoms = geom["atoms"]
    require(
        [child.tag for child in node if child.tag in {"atomic_positions", "crystal_positions", "wyckoff_positions"}]
        == ["atomic_positions"],
        "STRUCTURE_REPRESENTATION",
        "one Cartesian atomic_positions representation required",
    )
    eq(strict_integer(node.attrib.get("nat", ""), "STRUCTURE_ORDER"), len(atoms), "STRUCTURE_ORDER")
    eq(strict_integer(node.attrib.get("bravais_index", ""), "STRUCTURE_BASIS"), geom["ibrav"], "STRUCTURE_BASIS")
    basis = [vector(one(node, "cell/" + axis), "STRUCTURE_BASIS") for axis in ["a1", "a2", "a3"]]
    inverse, det, condition = inv3(basis)
    for i, row in enumerate(basis):
        for j, value in enumerate(row):
            close(value, float(geom["cell_vectors_bohr_decimal"][i][j]), "STRUCTURE_BASIS", 1e-8, 1e-8)
    rows = list(one(node, "atomic_positions"))
    require(len(rows) == len(atoms), "STRUCTURE_ORDER", "atom inventory")
    out = []
    for i, (row, expected) in enumerate(zip(rows, atoms)):
        eq(row.tag, "atom", "STRUCTURE_ORDER")
        eq(row.attrib.get("name"), expected["element"], "STRUCTURE_ORDER")
        eq(strict_integer(row.attrib.get("index", ""), "STRUCTURE_ORDER"), i + 1, "STRUCTURE_ORDER")
        cart = vector(row, "STRUCTURE_POSITION")
        frac = [sum(cart[k] * inverse[k][j] for k in range(3)) for j in range(3)]
        # Reject before subtracting the source coordinate or rounding: otherwise
        # large finite coordinates can lose every fractional bit and look like
        # exact integer translations, even when all source atoms overlap.
        require(
            all(math.isfinite(x) and abs(x) <= MAX_ABS_FRACTIONAL_COORDINATE for x in frac),
            "STRUCTURE_POSITION_PRECISION",
            "outside supported fractional-coordinate comparison domain",
        )
        inverse_column_norm = max(sum(abs(inverse[k][j]) for k in range(3)) for j in range(3))
        precision_guard = (
            128 * BINARY64_EPSILON * (condition + 1) * max(1, max(abs(x) for x in cart) * inverse_column_norm)
        )
        require(
            math.isfinite(precision_guard) and precision_guard <= FRACTIONAL_TOLERANCE / 8,
            "STRUCTURE_POSITION_PRECISION",
            "insufficient binary64 comparison margin",
        )
        delta = [frac[j] - float(expected["fractional_literals"][j]) for j in range(3)]
        shifts = [round(x) for x in delta]
        require(
            all(abs(x) <= MAX_ABS_LATTICE_SHIFT for x in shifts),
            "STRUCTURE_POSITION_PRECISION",
            "outside supported lattice-shift comparison domain",
        )
        require(
            all(abs(x - shift) <= FRACTIONAL_TOLERANCE for x, shift in zip(delta, shifts)),
            "STRUCTURE_POSITION",
            "not an integer lattice translation",
        )
        out.append(
            {
                "source_atom_index": i + 1,
                "element": expected["element"],
                "cartesian_bohr": cart,
                "fractional": frac,
                "integer_lattice_shift": shifts,
                "binary64_precision_guard_fractional": precision_guard,
            }
        )
    return {"determinant_bohr3": det, "condition_infinity": condition, "atoms": out}


def _check_method_geometry(context, root):
    """Called only with context reconstructed after exact input validation."""
    eq(root.tag, "{" + QES_NS + "}espresso", "XML_VERSION")
    eq(root.attrib.get("Units"), "Hartree atomic units", "XML_UNITS")
    creator = one(root, "general_info/creator")
    fmt = one(root, "general_info/xml_format")
    eq((creator.attrib.get("NAME"), creator.attrib.get("VERSION")), ("PWSCF", "7.5"), "XML_VERSION")
    eq((fmt.attrib.get("NAME"), fmt.attrib.get("VERSION")), ("QEXSD", "25.05.21"), "XML_VERSION")
    one(root, "closed")
    source = context.manifest
    require(
        sha((json.dumps(source, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode())
        == context.manifest_sha256,
        "PREPARATION_PIN",
        "verified context mutated",
    )
    settings = source["derived_settings"]["namelist_literals"]
    system = settings["SYSTEM"]
    electrons = settings["ELECTRONS"]
    control = settings["CONTROL"]
    inp = one(root, "input")
    out = one(root, "output")
    for section in [inp, out]:
        dft = one(section, "dft")
        eq(text(section, "dft/functional"), "PBESOL", "METHOD_XC")
        require([c.tag for c in dft] == ["functional"], "METHOD_CORRECTION", "unexpected correction")
    for path, expect in [
        ("basis/ecutwfc", strict_number(system["ecutwfc"]) / 2),
        ("basis/ecutrho", strict_number(system["ecutrho"]) / 2),
        ("electron_control/conv_thr", strict_number(electrons["conv_thr"]) / 2),
        ("electron_control/mixing_beta", strict_number(electrons["mixing_beta"])),
        ("bands/tot_charge", 0),
    ]:
        close(strict_number(text(inp, path)), expect)
    for key in ["ecutwfc", "ecutrho"]:
        close(strict_number(text(out, "basis_set/" + key)), strict_number(system[key]) / 2)
    eq(strict_integer(text(inp, "bands/nbnd")), source["expected_nbnd"], "METHOD_BANDS")
    eq(text(inp, "electron_control/mixing_mode"), "plain", "METHOD_MIXING")
    eq(text(inp, "electron_control/diagonalization"), "davidson", "METHOD_SCALAR")
    eq(strict_integer(text(inp, "electron_control/max_nstep")), int(electrons["electron_maxstep"]), "METHOD_SCALAR")
    eq(text(inp, "bands/occupations"), "smearing", "METHOD_SCALAR")
    eq(text(inp, "bands/smearing"), "mp", "METHOD_SCALAR")
    close(strict_number(one(inp, "bands/smearing").attrib.get("degauss", "")), strict_number(system["degauss"]) / 2)
    for flag in ["lsda", "noncolin", "spinorbit"]:
        eq(text(inp, "spin/" + flag), "false", "METHOD_SCALAR")
        eq(text(out, "magnetization/" + flag), "false", "METHOD_SCALAR")
    for path, value in [
        ("calculation", "scf"),
        ("prefix", source["derived_settings"]["prefix"]),
        ("restart_mode", "from_scratch"),
        ("forces", "true"),
        ("stress", "true"),
    ]:
        eq(text(inp, "control_variables/" + path), value, "METHOD_SCALAR")
    eq(strict_integer(text(inp, "control_variables/nstep")), int(control["nstep"]), "UNSUPPORTED_PHASE")
    close(strict_number(text(inp, "control_variables/max_seconds")), 600)
    eq(text(inp, "ion_control/ion_dynamics"), "none", "METHOD_SCALAR")
    eq(text(inp, "cell_control/cell_dynamics"), "none", "METHOD_SCALAR")
    grid = one(inp, "k_points_IBZ/monkhorst_pack")
    for i, n in enumerate(source["derived_settings"]["mesh"], 1):
        eq(strict_integer(grid.attrib.get("nk" + str(i), "")), n, "METHOD_SCALAR")
        eq(strict_integer(grid.attrib.get("k" + str(i), "")), 0, "METHOD_SCALAR")
    for section in [inp, out]:
        species = one(section, "atomic_species")
        expected = source["geometry"]["source"]["species_rows"]
        rows = list(species)
        eq(strict_integer(species.attrib.get("ntyp", "")), len(expected), "STRUCTURE_ORDER")
        eq(len(rows), len(expected), "STRUCTURE_ORDER")
        for row, wanted in zip(rows, expected):
            el, mass, pseudo = wanted.split()
            eq(row.tag, "species", "STRUCTURE_ORDER")
            eq(row.attrib.get("name"), el, "STRUCTURE_ORDER")
            eq(text(row, "pseudo_file"), pseudo, "UPF_HEADER")
            close(strict_number(text(row, "mass")), float(mass))
    check_structure(one(inp, "atomic_structure"), context)
    check_structure(one(out, "atomic_structure"), context)
    return {
        "checks": {
            "preparation_binding": True,
            "method_subset": True,
            "geometry_full_3x3": True,
            "xml_unit_conversion": True,
        },
        "numeric_comparison_policy": {
            "fractional_tolerance": FRACTIONAL_TOLERANCE,
            "max_abs_fractional_coordinate": MAX_ABS_FRACTIONAL_COORDINATE,
            "max_abs_lattice_shift": MAX_ABS_LATTICE_SHIFT,
            "physical_limit": False,
            "precision_guard": "128 * epsilon * (condition + 1) * max(1, norm_inf(cart) * norm_1(inverse)) <= tolerance / 8",
        },
    }


SCALAR_TAGS = {
    "functional",
    "ecutwfc",
    "ecutrho",
    "conv_thr",
    "mixing_beta",
    "mixing_mode",
    "diagonalization",
    "max_nstep",
    "nbnd",
    "nelec",
    "tot_charge",
    "occupations",
    "smearing",
    "lsda",
    "noncolin",
    "spinorbit",
    "calculation",
    "prefix",
    "restart_mode",
    "forces",
    "stress",
    "nstep",
    "max_seconds",
    "ion_dynamics",
    "cell_dynamics",
    "mass",
    "pseudo_file",
    "a1",
    "a2",
    "a3",
    "atom",
    "convergence_achieved",
    "n_scf_steps",
    "scf_error",
    "exit_status",
    "n_opt_steps",
    "etot",
    "fermi_energy",
    "nprocs",
    "nthreads",
}
STOP_OR_FATAL = re.compile(
    r"Error in routine|MPI_ABORT|segmentation fault|\bfatal\b|\bkilled\b"
    r"|maximum\s+(?:(?:CPU|wall(?:clock)?)\s+)?time\s+(?:exceeded|reached)"
    r"|(?:CPU|wall(?:clock)?)\s+time\s+limit\s+(?:exceeded|reached)"
    r"|signal(?:\s+[0-9]+)?\s+(?:received|caught|trapped)|(?:caught|received|trapped|terminated by)\s+signal"
    r"|\bSIG(?:TERM|INT|KILL|SEGV|ABRT)\b|stop(?:ping|ped)?\s+(?:requested|by\s+user)"
    r"|user\s+requested\s+stop",
    re.IGNORECASE,
)
ELECTRONIC_EXECUTION = re.compile(
    r"iteration\s*#|convergence\s+(?:NOT\s+achieved|has\s+(?:NOT\s+)?been\s+achieved)"
    r"|\btotal\s+energy\b|\bestimated\s+scf\s+accuracy\b"
    r"|\bFermi\s+energy\b|\btotal\s+force\b|\btotal\s+stress\b"
    r"|\bSelf-consistent\s+Calculation\b",
    re.IGNORECASE,
)
FORBIDDEN_INIT_OUTPUT = {
    "total_energy",
    "band_structure",
    "forces",
    "stress",
    "fermi_energy",
    "nelec",
    "nbnd",
    "etot",
    "ks_energies",
    "eigenvalues",
    "occupations",
    "electric_field",
    "fcp_force",
    "fcp_tot_charge",
    "rism3d",
    "rismlaue",
    "two_chem",
}


def _bounded_bytes(raw, maximum, code, *, allow_empty=False):
    require(
        type(raw) is bytes and len(raw) <= maximum and (allow_empty or len(raw) > 0),
        code,
        "bounded immutable bytes required",
    )


def _xml(raw):
    require(not re.search(rb"<!\s*(DOCTYPE|ENTITY)", raw, re.IGNORECASE), "XML_UNSAFE", "declarations forbidden")
    try:
        root = ET.fromstring(raw.decode("utf-8"))
    except (ET.ParseError, UnicodeError) as error:
        raise Rejected("XML_PARSE", "complete UTF-8 XML required") from error
    stack = [(root, 0, False)]
    count = 0
    while stack:
        node, depth, numeric_scope = stack.pop()
        count += 1
        require(count <= 100000 and depth <= 40, "XML_COMPLEXITY", "bounded node/depth domain required")
        if node is not root:
            require(not node.tag.startswith("{"), "XML_NAMESPACE", "unqualified QEXSD child required")
        if numeric_scope:
            require(
                not any(key.rsplit("}", 1)[-1].lower() in {"unit", "units"} for key in node.attrib),
                "XML_UNITS",
                "numeric subtrees cannot override the pinned unit domain",
            )
        elif node is root:
            require(
                not any(key != "Units" and key.rsplit("}", 1)[-1].lower() in {"unit", "units"} for key in node.attrib),
                "XML_UNITS",
                "one root Units declaration required",
            )
        if node.tag in {"atomic_positions", "cell", "basis", "basis_set"}:
            require(not node.attrib, "XML_UNITS", "unit-sensitive container has unexpected attributes")
        if node.tag == "atomic_structure":
            require(
                set(node.attrib) <= {"nat", "num_of_atomic_wfc", "alat", "bravais_index", "alternative_axes"},
                "XML_UNITS",
                "unsupported atomic structure attribute",
            )
        if node.tag in SCALAR_TAGS:
            require(not len(node), "XML_SCALAR_CHILD", "nested scalar/vector")
            allowed = {
                "smearing": {"degauss"},
                "atom": {"name", "index"},
                "forces": {"rank", "dims"},
                "stress": {"rank", "dims"},
            }.get(node.tag, set())
            require(set(node.attrib) <= allowed, "XML_SCALAR_ATTRIBUTE", "unexpected scalar/vector attribute")
        if len(node):
            require(
                not (node.text or "").strip() and all(not (child.tail or "").strip() for child in node),
                "XML_MIXED_CONTENT",
                "unexpected mixed content",
            )
        stack.extend((child, depth + 1, numeric_scope or child.tag in {"input", "output"}) for child in node)
    return root


def _unique_stdout_number(stdout, label, numeric):
    rows = [line for line in stdout.splitlines() if re.match(r"^[ \t]*" + re.escape(label) + r"\b", line, re.ASCII)]
    require(len(rows) == 1, "STDOUT_UNIQUE", label)
    match = re.fullmatch(r"[ \t]*" + re.escape(label) + r"[ \t]*=[ \t]*(" + numeric + r")[ \t]*", rows[0], re.ASCII)
    require(match is not None, "STDOUT_NUMBER", "complete numeric report required")
    return strict_number(match.group(1), "STDOUT_NUMBER")


def _stdout(context, stdout_raw, stderr_raw):
    try:
        stdout, stderr = stdout_raw.decode("utf-8"), stderr_raw.decode("utf-8")
    except UnicodeError as error:
        raise Rejected("STDOUT_ENCODING", "UTF-8 stdout/stderr required") from error
    require("\x00" not in stdout and "\x00" not in stderr, "STDOUT_ENCODING", "NUL output is unsupported")
    banners = [line for line in stdout.splitlines() if re.search(r"\bProgram\s+PWSCF\b", line, re.IGNORECASE)]
    done = [line for line in stdout.splitlines() if "JOB DONE." in line]
    require(
        len(banners) == len(done) == 1
        and re.fullmatch(r"[ \t]*Program PWSCF[ \t]+v\.7\.5[ \t]+starts(?: on [^\r\n]+)?[ \t]*", banners[0])
        and re.fullmatch(r"[ \t]*JOB DONE\.[ \t]*", done[0]),
        "STDOUT_COMPLETE",
        "one complete QE7.5 banner and completion line required",
    )
    combined = stdout + "\n" + stderr
    require(not STOP_OR_FATAL.search(combined), "EXECUTION_CONTRADICTION", "fatal or interrupted execution marker")
    require(not ELECTRONIC_EXECUTION.search(combined), "INITIALIZATION_CONFLICT", "electronic execution marker")
    stop_rows = [line for line in combined.splitlines() if re.match(r"^[ \t]*STOP\b", line, re.IGNORECASE)]
    require(
        len(stop_rows) <= 1 and all(re.fullmatch(r"[ \t]*STOP[ \t]+(?:0|255)[ \t]*", line) for line in stop_rows),
        "EXECUTION_CONTRADICTION",
        "unsupported STOP report",
    )
    expected = context.manifest
    for label, value in [
        ("number of atoms/cell", 4),
        ("number of atomic types", len(expected["pseudopotentials"])),
        ("number of Kohn-Sham states", expected["expected_nbnd"]),
    ]:
        eq(_unique_stdout_number(stdout, label, r"\d+"), value, "STDOUT_INVENTORY")
    close(
        _unique_stdout_number(stdout, "number of electrons", FLOAT),
        context.expected_electrons,
        "STDOUT_ELECTRONS",
        rel=0,
        absolute=0.005000001,
    )


def _initialization(root):
    out = one(root, "output")
    eq(text(root, "input/control_variables/nstep"), "0", "INITIALIZATION_CONFLICT")
    eq(text(out, "convergence_info/scf_conv/convergence_achieved"), "false", "INITIALIZATION_CONFLICT")
    eq(strict_integer(text(out, "convergence_info/scf_conv/n_scf_steps")), 0, "INITIALIZATION_CONFLICT")
    error = strict_number(text(out, "convergence_info/scf_conv/scf_error"))
    require(error >= 0, "INITIALIZATION_CONFLICT", "negative SCF metadata error")
    status = strict_integer(text(root, "exit_status"))
    require(status in (0, 255), "INITIALIZATION_CONFLICT", "unsupported initialization XML status")
    require(
        not any(node.tag in FORBIDDEN_INIT_OUTPUT for node in out.iter()),
        "INITIALIZATION_CONFLICT",
        "uncomputed result objects must remain absent",
    )
    require(not root.findall("step"), "INITIALIZATION_CONFLICT", "electronic/ionic trajectory unavailable at nstep0")
    ionic = out.findall("convergence_info/opt_conv")
    require(len(ionic) <= 1, "XML_DUPLICATE", "opt_conv")
    if ionic:
        eq(text(ionic[0], "convergence_achieved"), "false", "INITIALIZATION_CONFLICT")
        eq(strict_integer(text(ionic[0], "n_opt_steps")), 0, "INITIALIZATION_CONFLICT")
    return status


def read_initialization(
    binding_bytes: bytes,
    files: dict[str, bytes],
    *,
    xml: bytes,
    stdout: bytes,
    stderr: bytes = b"",
    process_exit_code: int | None = None,
) -> dict:
    """Return a bounded semantic reading, never an authenticated execution result.

    Revalidate actual source/deck/UPF bytes with installed PR160 trust on every
    call. No binding-shaped object or caller-declared expected numbers are used.
    process_exit_code is separately supplied, unverified process metadata; it is
    never inferred from XML and never rewritten. Custody is outside this reader.
    """
    _bounded_bytes(xml, MAX_XML, "XML_SIZE", allow_empty=True)
    _bounded_bytes(stdout, MAX_STDOUT, "STDOUT_SIZE", allow_empty=True)
    _bounded_bytes(stderr, MAX_STDERR, "STDERR_SIZE", allow_empty=True)
    require(
        process_exit_code is None or type(process_exit_code) is int and -255 <= process_exit_code <= 255,
        "PROCESS_EXIT",
        "optional integer process exit required",
    )
    report = {
        "schema_version": "sclib-pbesol-initialization-reading/1",
        "implementation_status": "offline_reader_synthetic_output_tests_only",
        "evidence_origin": "caller_supplied_unattested_bytes",
        "input_binding_verified": False,
        "custody_verified": False,
        "current_returned_attempt": None,
        "capture_complete": None,
        "semantic_reading_status": "rejected",
        "execution_consistency_ready_for_review": False,
        "process_exit_code_supplied": process_exit_code,
        "xml_exit_status": None,
        "exit_requires_review": True,
        "transport_outcome_verified": None,
        "next_stage_ready": False,
        "actual_runtime_acceptance": False,
        "scientific_acceptance": False,
        "tc_calculated": False,
        "candidate_grade_changed": False,
        "solver_calls": 0,
        "queue_calls": 0,
        "physical_outputs": {
            name: None
            for name in (
                "total_energy_hartree",
                "forces",
                "stress",
                "fermi_energy_hartree",
                "electrons",
                "scf_error_hartree",
            )
        },
        "output_pins": {
            name: {"bytes": len(raw), "sha256": sha(raw)}
            for name, raw in (("xml", xml), ("stdout", stdout), ("stderr", stderr))
        },
        "expected_input": None,
        "rejection": None,
    }
    try:
        require(type(files) is dict and 6 <= len(files) <= 7, "INPUT_BINDING", "bounded exact input map required")
        snapshot = files.copy()
        require(
            all(type(value) is bytes for value in snapshot.values()), "INPUT_BINDING", "immutable input bytes required"
        )
        binding = validate_input_binding(binding_bytes, snapshot)
        require(
            binding.preparation_phase == "initialize",
            "INITIALIZATION_ONLY",
            "SCF inputs are unsupported by this reader",
        )
        source = json.loads(snapshot["preparation.json"])  # Exact bytes already independently verified above.
        context = _VerifiedPreparation(
            source,
            BUNDLE_SHA256,
            binding.preparation_manifest.sha256,
            binding.derived_deck.sha256,
            tuple(p.file.sha256 for p in binding.pseudopotentials),
            binding.expected_electrons,
        )
        report["input_binding_verified"] = True
        report["expected_input"] = {
            "source_id": binding.source_id,
            "phase": binding.preparation_phase,
            "functional": "PBESOL",
            "expected_electrons": binding.expected_electrons,
            "expected_nbnd": binding.expected_nbnd,
            "electron_scope": "input_UPF_inventory_not_measured_output",
            "binding_sha256": sha(binding_bytes),
            "input_sha256": binding.derived_deck.sha256,
            "geometry_sha256": binding.geometry_sha256,
            "la2f": False,
            "la2f_basis": "exact_validated_input_deck_not_XML",
        }
        root = _xml(xml)
        partial = _check_method_geometry(context, root)
        _stdout(context, stdout, stderr)
        xml_status = _initialization(root)
        report.update(
            semantic_reading_status="initialization_only",
            xml_exit_status=xml_status,
            exit_requires_review=process_exit_code != 0,
            scf_steps=0,
            electronic_convergence_reported=False,
            method_geometry_checks=partial["checks"],
            numeric_comparison_policy=partial["numeric_comparison_policy"],
        )
        # OS255 may be a valid dry-run representation, but remains a process failure.
        report["supplied_process_classification"] = (
            "unknown"
            if process_exit_code is None
            else "succeeded"
            if process_exit_code == 0
            else "solver_failure"
            if process_exit_code > 0
            else "terminated_by_signal"
        )
    except (ValueError, TypeError, KeyError, RecursionError) as error:
        code = getattr(error, "code", "INPUT_BINDING")
        report["semantic_reading_status"] = "unreadable" if code in {"XML_PARSE", "STDOUT_ENCODING"} else "rejected"
        report["rejection"] = {"code": code, "message": str(error)[:240]}
    return report
