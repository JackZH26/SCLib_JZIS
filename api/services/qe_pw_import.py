"""Server-runtime preflight of original PWSCF files, independent of UI readings.

This pure parser does not import SQL rows or attest execution. It consumes the
explicit Discovery input subset, native QEXSD 25.05.21 and PWSCF 7.5 stdout,
and exact local UPF bytes. No user-supplied JSON report supplies a quantity.
"""

from __future__ import annotations

import hashlib
import math
import re
import xml.etree.ElementTree as ET

from services.qe_pw_input import FILENAME, NUMBER, document, read_pw_input, real, require

VERSION = "qe-pw-native-preflight/1.0.0"
MAX_OUTPUT_BYTES = 8 * 1024 * 1024
MAX_UPF_BYTES = 8 * 1024 * 1024
MAX_XML_ELEMENTS = 200000
MAX_XML_DEPTH = 64
BOHR_ANGSTROM = 0.529177210903
AUTHORITY = {
    "execution_authenticated": False,
    "pseudopotential_execution_bytes_attested": False,
    "candidate_source_association_verified": False,
    "scientific_acceptance": False,
    "ml_training_approved": False,
    "database_write": False,
    "public_release": False,
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def xml_document(raw, limit):
    text = document(raw, limit)
    require(not re.search(r"<!\s*(?:DOCTYPE|ENTITY)", text, re.I), "qe_xml_dtd_or_entity")
    parser = ET.XMLPullParser(("start", "end"))
    count, depth, root = 0, 0, None
    try:
        for offset in range(0, len(text), 65536):
            parser.feed(text[offset : offset + 65536])
            for event, element in parser.read_events():
                if event == "start":
                    depth += 1
                    count += 1
                    if root is None:
                        root = element
                    require(
                        count <= MAX_XML_ELEMENTS and depth <= MAX_XML_DEPTH, "qe_xml_shape_bound"
                    )
                else:
                    depth -= 1
        parser.close()
    except ET.ParseError:
        require(False, "qe_xml_malformed")
    require(root is not None and depth == 0, "qe_xml_incomplete")
    return root


def node(root, path, *, optional=False):
    for part in path.split("/"):
        found = [child for child in root if child.tag == part]
        if not found and optional:
            return None
        require(len(found) == 1, "qe_xml_missing_or_duplicate_node")
        root = found[0]
    return root


def text(root, path):
    item = node(root, path)
    require(len(item) == 0, "qe_xml_scalar_children")
    return (item.text or "").strip()


def number(root, path):
    return real(text(root, path))


def integer(value):
    require(value.is_integer() and 0 <= value <= 2**53 - 1, "qe_xml_nonnegative_integer")
    return int(value)


def boolean(root, path):
    value = text(root, path)
    require(value in {"true", "false"}, "qe_xml_boolean")
    return value == "true"


def equal(actual, expected, code="qe_input_output_mismatch"):
    require(actual == expected, code)


def close(actual, expected, *, relative=1e-10, absolute=0):
    require(
        math.isfinite(actual)
        and math.isfinite(expected)
        and abs(actual - expected) <= max(absolute, relative * abs(expected)),
        "qe_input_output_numeric_mismatch",
    )


def vector(item, count):
    require(len(item) == 0, "qe_xml_vector_children")
    tokens = (item.text or "").split()
    require(len(tokens) == count, "qe_xml_vector_shape")
    return [real(token) for token in tokens]


def inspect_upf(name, raw):
    require(type(name) is str and FILENAME.fullmatch(name), "qe_upf_filename")
    root = xml_document(raw, MAX_UPF_BYTES)
    require(root.tag == "UPF" and re.match(r"2(?:\.|$)", root.get("version", "")), "qe_upf_version")
    header = node(root, "PP_HEADER")

    def attr(key):
        return header.get(key, "").strip()

    require(re.fullmatch(r"[A-Z][a-z]?", attr("element")), "qe_upf_element")
    require(
        " ".join(attr("functional").upper().split()) in {"PBE", "SLA PW PBX PBC"},
        "qe_upf_functional",
    )
    require(
        attr("relativistic").lower() in {"no", "scalar"}
        and attr("has_so").lower() in {"f", "false", ".false."},
        "qe_upf_relativistic_scope",
    )
    require(
        attr("pseudo_type").upper() in {"NC", "US", "USPP", "PAW"}
        and attr("is_coulomb").lower() in {"f", "false", ".false."},
        "qe_upf_type_scope",
    )
    valence = real(attr("z_valence"))
    require(1e-6 <= valence <= 118, "qe_upf_valence_scope")
    return {
        "filename": name,
        "sha256": sha(raw),
        "size_bytes": len(raw),
        "element": attr("element"),
        "functional": "PBE",
        "raw_functional": attr("functional"),
        "valence_electrons": valence,
        "relativistic": attr("relativistic"),
        "pseudo_type": attr("pseudo_type"),
        "scope": "Header inspection only; radial data suitability and redistribution rights are unreviewed.",
    }


def check_species(root, expected, *, spin=False):
    rows = [child for child in root if child.tag == "species"]
    equal(integer(real(root.get("ntyp", ""))), len(expected["species"]))
    equal(len(rows), len(expected["species"]))
    for item, species in zip(rows, expected["species"], strict=True):
        equal(item.get("name"), species["element"])
        equal(text(item, "pseudo_file"), species["filename"])
        close(number(item, "mass"), species["mass_amu"])
        if spin and expected["settings"]["nspin"] == 2:
            close(number(item, "starting_magnetization"), species["starting_magnetization"])


def structure(root, expected, *, match_positions):
    equal(integer(real(root.get("nat", ""))), len(expected["atoms"]))
    basis = [vector(node(root, f"cell/{axis}"), 3) for axis in ("a1", "a2", "a3")]
    for row, wanted in zip(basis, expected["cell_vectors_angstrom"], strict=True):
        for value, target in zip(row, wanted, strict=True):
            close(value * BOHR_ANGSTROM, target, relative=1e-8, absolute=1e-8)
    require(all(basis[i][i] > 0 for i in range(3)), "qe_xml_cell_singular")
    rows = list(node(root, "atomic_positions"))
    equal(len(rows), len(expected["atoms"]))
    output = []
    for index, (item, atom) in enumerate(zip(rows, expected["atoms"], strict=True)):
        equal(item.tag, "atom")
        equal(item.get("name"), atom["element"])
        equal(integer(real(item.get("index", ""))), index + 1)
        cartesian = vector(item, 3)
        z = cartesian[2] / basis[2][2]
        y = (cartesian[1] - z * basis[2][1]) / basis[1][1]
        x = (cartesian[0] - y * basis[1][0] - z * basis[2][0]) / basis[0][0]
        fractional = [x, y, z]
        require(all(math.isfinite(v) for v in fractional), "qe_fractional_nonfinite")
        if match_positions:
            for value, target in zip(fractional, atom["fractional"], strict=True):
                difference = value - target
                require(abs(difference - round(difference)) <= 1e-8, "qe_atom_position_mismatch")
        output.append(
            {
                "input_atom_index": index + 1,
                "element": atom["element"],
                "cartesian_bohr": cartesian,
                "fractional": fractional,
            }
        )
    return output


def scalar(root, path, unit):
    if node(root, path, optional=True) is None:
        return None
    raw = text(root, path)
    return {"raw": raw, "value": real(raw), "unit": unit, "xml_path": "output/" + path}


def read_pw_output(expected, xml_bytes, stdout_bytes, valence_electrons):
    root = xml_document(xml_bytes, MAX_OUTPUT_BYTES)
    equal(root.tag, "{http://www.quantum-espresso.org/ns/qes/qes-1.0}espresso", "qe_xml_namespace")
    equal(root.get("Units"), "Hartree atomic units", "qe_xml_units")
    creator, format_node = node(root, "general_info/creator"), node(root, "general_info/xml_format")
    equal((creator.get("NAME"), creator.get("VERSION")), ("PWSCF", "7.5"), "qe_engine_version")
    equal(
        (format_node.get("NAME"), format_node.get("VERSION")),
        ("QEXSD", "25.05.21"),
        "qe_schema_version",
    )
    node(root, "closed")
    stdin, output = node(root, "input"), node(root, "output")
    settings = expected["settings"]
    stdout = document(stdout_bytes, MAX_OUTPUT_BYTES)
    require(
        len(re.findall(r"Program PWSCF\s+v\.7\.5\s+starts", stdout)) == 1
        and stdout.count("JOB DONE.") == 1
        and not re.search(r"Error in routine|MPI_ABORT", stdout, re.I),
        "qe_stdout_envelope",
    )

    def stdout_number(pattern):
        matches = re.findall(pattern, stdout)
        require(len(matches) == 1, "qe_stdout_inventory")
        return real(matches[0])

    equal(stdout_number(r"number of atoms/cell\s*=\s*(\d+)(?=\s|$)"), len(expected["atoms"]))
    equal(stdout_number(r"number of atomic types\s*=\s*(\d+)(?=\s|$)"), len(expected["species"]))
    close(
        stdout_number(r"number of electrons\s*=\s*(" + NUMBER + r")(?=\s|$)"),
        valence_electrons,
        relative=0,
        absolute=0.005000001,
    )
    control = node(stdin, "control_variables")
    for path, value in (
        ("calculation", settings["calculation"]),
        ("prefix", settings["prefix"]),
        ("restart_mode", "from_scratch"),
        ("pseudo_dir", "./pseudo"),
        ("outdir", "./out"),
    ):
        equal(text(control, path), value)
    close(number(control, "nstep"), settings["nstep"])
    close(number(control, "max_seconds"), settings["max_seconds"])
    equal(boolean(control, "forces"), True)
    equal(boolean(control, "stress"), True)
    check_species(node(stdin, "atomic_species"), expected, spin=True)
    check_species(node(output, "atomic_species"), expected)
    structure(node(stdin, "atomic_structure"), expected, match_positions=True)
    final_atoms = structure(
        node(output, "atomic_structure"),
        expected,
        match_positions=settings["nstep"] == 0 or settings["calculation"] == "scf",
    )
    for item in (stdin, output):
        equal(text(item, "dft/functional"), "PBE")
        require(
            all(child.tag == "functional" for child in node(item, "dft")), "qe_extra_dft_correction"
        )
    for field, flag in (
        ("lsda", settings["nspin"] == 2),
        ("noncolin", False),
        ("spinorbit", False),
    ):
        equal(boolean(stdin, "spin/" + field), flag)
        equal(boolean(output, "magnetization/" + field), flag)
    for path, value in (
        ("basis/ecutwfc", settings["ecutwfc_ry"] / 2),
        ("basis/ecutrho", settings["ecutrho_ry"] / 2),
        ("bands/tot_charge", settings["charge"]),
        ("electron_control/conv_thr", settings["conv_thr_ry"] / 2),
        ("electron_control/max_nstep", settings["electron_maxstep"]),
        ("electron_control/mixing_beta", settings["mixing_beta"]),
    ):
        close(number(stdin, path), value)
    equal(text(stdin, "bands/occupations"), "smearing")
    equal(text(stdin, "bands/smearing"), settings["smearing"])
    close(real(node(stdin, "bands/smearing").get("degauss", "")), settings["degauss_ry"] / 2)
    close(number(output, "basis_set/ecutwfc"), settings["ecutwfc_ry"] / 2)
    close(number(output, "basis_set/ecutrho"), settings["ecutrho_ry"] / 2)
    equal(text(stdin, "electron_control/diagonalization"), "davidson")
    grid = node(stdin, "k_points_IBZ/monkhorst_pack")
    for i in range(3):
        equal(integer(real(grid.get(f"nk{i + 1}", ""))), settings["mesh"][i])
        equal(integer(real(grid.get(f"k{i + 1}", ""))), settings["shifts"][i])
    equal(text(stdin, "cell_control/cell_dynamics"), "none")
    relaxation = settings["calculation"] == "relax"
    equal(text(stdin, "ion_control/ion_dynamics"), "bfgs" if relaxation else "none")
    if relaxation:
        close(number(control, "etot_conv_thr"), settings["etot_conv_thr_ry"] / 2)
        close(number(control, "forc_conv_thr"), settings["forc_conv_thr_ry_bohr"] / 2)
    converged = boolean(output, "convergence_info/scf_conv/convergence_achieved")
    steps = integer(number(output, "convergence_info/scf_conv/n_scf_steps"))
    error = number(output, "convergence_info/scf_conv/scf_error")
    require(
        0 <= error
        and steps <= settings["electron_maxstep"]
        and (not converged or (steps > 0 and error <= settings["conv_thr_ry"] / 2 * (1 + 1e-8))),
        "qe_scf_convergence_conflict",
    )
    exit_status = integer(number(root, "exit_status"))
    ionic = node(output, "convergence_info/opt_conv", optional=True)
    ionic_converged = boolean(ionic, "convergence_achieved") if ionic is not None else None
    ionic_steps = integer(number(ionic, "n_opt_steps")) if ionic is not None else None
    require((ionic is not None) == relaxation, "qe_ionic_status_scope")
    require(ionic_steps is None or ionic_steps <= settings["nstep"], "qe_ionic_step_limit")
    require(not ionic_converged or converged, "qe_ionic_electronic_conflict")
    if ionic_steps == 0:
        # A report of no ionic step cannot silently supply a displaced geometry.
        structure(node(output, "atomic_structure"), expected, match_positions=True)
    initialized = settings["nstep"] == 0
    if initialized:
        require(
            steps == 0 and not converged and not ionic_converged and exit_status in {0, 255},
            "qe_initialization_conflict",
        )
        require(
            node(output, "total_energy", optional=True) is None
            and not re.search(r"!\s+total energy", stdout),
            "qe_initialization_energy_conflict",
        )
    energy = None if initialized else scalar(output, "total_energy/etot", "Hartree/cell")
    fermi = None if initialized else scalar(output, "band_structure/fermi_energy", "Hartree")
    electrons = None if initialized else scalar(output, "band_structure/nelec", "electrons/cell")
    if electrons:
        close(electrons["value"], valence_electrons)
    if converged:
        require(energy is not None and electrons is not None, "qe_converged_values_missing")
        finals = re.findall(r"!\s+total energy\s*=\s*(" + NUMBER + r")\s+Ry", stdout)
        iterations = re.findall(r"convergence has been achieved in\s+(\d+)\s+iterations", stdout)
        require(finals and iterations, "qe_stdout_convergence_missing")
        close(real(finals[-1]), energy["value"] * 2, relative=0, absolute=1e-8)
        equal(int(iterations[-1]), steps)
        if ionic_converged:
            reported = re.findall(
                r"bfgs converged in\s+\d+\s+scf cycles and\s+(\d+)\s+bfgs steps", stdout
            )
            require(reported and int(reported[-1]) == ionic_steps, "qe_stdout_ionic_mismatch")

    def tensor(name, dimensions, unit):
        item = None if initialized else node(output, name, optional=True)
        if item is None:
            return None
        require(
            item.get("rank") == "2" and item.get("dims", "").split() == list(map(str, dimensions)),
            "qe_tensor_dimensions",
        )
        values = vector(item, math.prod(dimensions))
        return {"values": values, "unit": unit, "xml_path": "output/" + name}

    forces = tensor("forces", (3, len(expected["atoms"])), "Hartree/bohr")
    if forces:
        forces["layout"] = "atom-major xyz"
        forces["maximum_atom_norm"] = max(
            math.hypot(*forces["values"][i : i + 3]) for i in range(0, len(forces["values"]), 3)
        )
        require(math.isfinite(forces["maximum_atom_norm"]), "qe_derived_force_nonfinite")
    stress = tensor("stress", (3, 3), "Hartree/bohr^3")
    status = (
        "initialization_only"
        if initialized
        else "incomplete"
        if exit_status != 0
        else "scf_not_converged"
        if not converged
        else "ionic_not_converged"
        if relaxation and not ionic_converged
        else "relaxation_reported_converged"
        if relaxation
        else "scf_reported_converged"
    )
    return {
        "status": status,
        "engine": {
            "name": "PWSCF",
            "version": "7.5",
            "xml_format": "QEXSD 25.05.21",
            "xml_units": "Hartree atomic units",
            "reported_exit_status": exit_status,
            "nprocs": integer(number(root, "parallel_info/nprocs")),
            "nthreads": integer(number(root, "parallel_info/nthreads")),
        },
        "convergence": {
            "electronic_reported": converged,
            "scf_steps": steps,
            "scf_error_hartree": None if initialized else error,
            "electronic_threshold_hartree": settings["conv_thr_ry"] / 2,
            "ionic_reported": ionic_converged,
            "ionic_steps": ionic_steps,
            "basis_sampling_convergence_established": False,
        },
        "observations": {
            "total_energy": energy,
            "fermi_energy": fermi,
            "valence_electrons": electrons,
            "forces": forces,
            "stress": stress,
            "final_atoms": None if initialized else final_atoms,
        },
        "consistency": {
            "input_deck_parsed": True,
            "geometry_checked": True,
            "method_subset_checked": True,
            "pseudopotential_headers_checked": True,
            "stdout_energy_checked": converged,
            "full_xsd_validated": False,
        },
        "interpretation": "Native etot includes the selected smearing contribution; it is not formation energy, hull energy or 300 K thermodynamic free energy.",
        "scientific_scope": {
            "target_temperature_k": None,
            "target_pressure_gpa": None,
            "stable_host_validated": False,
            "phonons_calculated": False,
            "tc_calculated": False,
        },
    }


def preflight_pw(*, input_bytes, xml_bytes, stdout_bytes, pseudopotentials):
    """Pure bounded reading. No manifest, frontend report, network or SQL input."""
    require(
        type(pseudopotentials) is dict and 1 <= len(pseudopotentials) <= 8, "qe_upf_inventory_bound"
    )
    # Reject every over-limit or mutable buffer before decoding any document.
    for raw, limit in [
        (input_bytes, 1024 * 1024),
        (xml_bytes, MAX_OUTPUT_BYTES),
        (stdout_bytes, MAX_OUTPUT_BYTES),
        *((v, MAX_UPF_BYTES) for v in pseudopotentials.values()),
    ]:
        require(type(raw) is bytes and 0 < len(raw) <= limit, "qe_file_size_or_type")
    expected = read_pw_input(input_bytes)
    require(
        set(pseudopotentials) == {s["filename"] for s in expected["species"]},
        "qe_upf_inventory_mismatch",
    )
    pseudos = [
        inspect_upf(s["filename"], pseudopotentials[s["filename"]]) for s in expected["species"]
    ]
    for pseudo, species in zip(pseudos, expected["species"], strict=True):
        equal(pseudo["element"], species["element"], "qe_upf_element_mismatch")
    valence = (
        sum(p["valence_electrons"] * expected["composition"][p["element"]] for p in pseudos)
        - expected["settings"]["charge"]
    )
    require(valence > 0 and math.isfinite(valence), "qe_valence_count")
    reading = read_pw_output(expected, xml_bytes, stdout_bytes, valence)
    inventory = [
        {"role": role, "size_bytes": len(raw), "sha256": sha(raw)}
        for role, raw in (("input", input_bytes), ("xml", xml_bytes), ("stdout", stdout_bytes))
    ]
    inventory.extend(
        {
            "role": "pseudopotential",
            "filename": p["filename"],
            "size_bytes": p["size_bytes"],
            "sha256": p["sha256"],
        }
        for p in pseudos
    )
    return {
        "version": VERSION,
        "files": inventory,
        "input": expected,
        "pseudopotentials": pseudos,
        "expected_valence_electrons": valence,
        **reading,
        "authority": dict(AUTHORITY),
    }
