"""Read the explicit PWSCF input subset emitted by Discovery, without a manifest.

Comments, candidate labels and caller-supplied readings confer no authority.
Every namelist key/card in this subset is consumed; additional physics options
require a new adapter. The input is never executed and paths are never opened.
"""

from __future__ import annotations

import math
import re
from collections import Counter

from services.ml_composition import ELEMENTS

MAX_INPUT_BYTES = 1024 * 1024
NUMBER = r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eEdD][+-]?[0-9]+)?"
FILENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}\.upf", re.I)


class QePwImportError(ValueError):
    """Static error codes only; no uploaded source text or file paths."""


def require(condition, code):
    if not condition:
        raise QePwImportError(code)


def document(raw, limit):
    require(type(raw) is bytes and 0 < len(raw) <= limit, "qe_file_size_or_type")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise QePwImportError("qe_utf8_required") from None
    require(not re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", text), "qe_control_character")
    return text


def real(raw):
    require(type(raw) is str and len(raw) <= 80 and re.fullmatch(NUMBER, raw), "qe_numeric_token")
    normalized = raw.replace("D", "e").replace("d", "e")
    value = float(normalized)
    require(math.isfinite(value), "qe_nonfinite_number")
    # Inspect the mantissa lexically: Decimal can itself reject extremely long
    # exponent tokens before we can return this adapter's bounded error code.
    nonzero_mantissa = re.search(r"[1-9]", normalized.lower().split("e", 1)[0])
    require(value != 0 or not nonzero_mantissa, "qe_numeric_underflow")
    return value


def bounded(value, low, high, *, integer=False):
    require(low <= value <= high and (not integer or value.is_integer()), "qe_input_numeric_scope")
    return int(value) if integer else value


def read_pw_input(raw):
    source = document(raw, MAX_INPUT_BYTES)
    require(source.count("\n") + source.count("\r") <= 10000, "qe_input_line_bound")
    # Discovery emits one explicit assignment per line. Quoted exclamation
    # marks, multiple assignments and continuations are outside this adapter.
    lines = [
        line.strip()
        for line in source.splitlines()
        if line.strip() and not line.lstrip().startswith("!")
    ]
    groups, cursor = {}, 0
    for group in ("CONTROL", "SYSTEM", "ELECTRONS", "IONS"):
        if group == "IONS" and (cursor == len(lines) or lines[cursor] != "&IONS"):
            break
        require(cursor < len(lines) and lines[cursor] == "&" + group, "qe_input_namelist_order")
        cursor += 1
        values = {}
        while cursor < len(lines) and lines[cursor] != "/":
            match = re.fullmatch(r"([a-z][a-z0-9_]*(?:\([1-8]\))?)\s*=\s*(.+?),", lines[cursor])
            require(match is not None and match[1] not in values, "qe_input_assignment")
            values[match[1]] = match[2]
            cursor += 1
        require(cursor < len(lines), "qe_input_unterminated_namelist")
        groups[group] = values
        cursor += 1
    control, system, electrons = (groups[key] for key in ("CONTROL", "SYSTEM", "ELECTRONS"))
    calculation = control.get("calculation")
    require(calculation in {"'scf'", "'relax'"}, "qe_calculation_scope")
    relaxation = calculation == "'relax'"
    require(
        set(control)
        == {
            "calculation",
            "restart_mode",
            "prefix",
            "pseudo_dir",
            "outdir",
            "nstep",
            "max_seconds",
            "tprnfor",
            "tstress",
        }
        | ({"etot_conv_thr", "forc_conv_thr"} if relaxation else set()),
        "qe_control_keys",
    )
    require(
        control["restart_mode"] == "'from_scratch'"
        and control["pseudo_dir"] == "'./pseudo'"
        and control["outdir"] == "'./out'"
        and control["tprnfor"] == control["tstress"] == ".true.",
        "qe_control_scope",
    )
    require(re.fullmatch(r"'sclib_[a-f0-9]{16}(?:_check)?'", control["prefix"]), "qe_prefix_scope")
    nstep = bounded(real(control["nstep"]), 0, 1000, integer=True)
    require(relaxation or nstep in {0, 1}, "qe_scf_step_scope")
    require((nstep == 0) == control["prefix"].endswith("_check'"), "qe_initialization_prefix")
    spin = bounded(real(system.get("nspin", "")), 1, 2, integer=True)
    nat = bounded(real(system.get("nat", "")), 1, 96, integer=True)
    ntyp = bounded(real(system.get("ntyp", "")), 1, 8, integer=True)
    seeds = {f"starting_magnetization({i})" for i in range(1, ntyp + 1)} if spin == 2 else set()
    require(
        set(system)
        == {
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
        }
        | seeds,
        "qe_system_keys",
    )
    require(
        real(system["ibrav"]) == 0
        and system["noncolin"] == system["lspinorb"] == ".false."
        and system["occupations"] == "'smearing'"
        and system["smearing"] in {"'mv'", "'gaussian'", "'fd'"},
        "qe_system_scope",
    )
    require(
        set(electrons)
        == {
            "conv_thr",
            "electron_maxstep",
            "mixing_beta",
            "diagonalization",
            "startingpot",
            "startingwfc",
        },
        "qe_electron_keys",
    )
    require(
        electrons["diagonalization"] == "'david'"
        and electrons["startingpot"] == "'atomic'"
        and electrons["startingwfc"] == "'atomic+random'",
        "qe_electron_scope",
    )
    require(
        (groups.get("IONS") == {"ion_dynamics": "'bfgs'"}) if relaxation else "IONS" not in groups,
        "qe_ionic_scope",
    )
    ecutwfc = bounded(real(system["ecutwfc"]), 1, 5000)
    settings = {
        "calculation": calculation.strip("'"),
        "prefix": control["prefix"].strip("'"),
        "nstep": nstep,
        "max_seconds": bounded(real(control["max_seconds"]), 1, 86400),
        "nspin": spin,
        "ecutwfc_ry": ecutwfc,
        "ecutrho_ry": bounded(real(system["ecutrho"]), ecutwfc, 20000),
        "charge": bounded(real(system["tot_charge"]), -96, 96),
        "smearing": system["smearing"].strip("'"),
        "degauss_ry": bounded(real(system["degauss"]), 1e-6, 1),
        "conv_thr_ry": bounded(real(electrons["conv_thr"]), 1e-14, 0.01),
        "electron_maxstep": bounded(real(electrons["electron_maxstep"]), 1, 2000, integer=True),
        "mixing_beta": bounded(real(electrons["mixing_beta"]), 0.001, 1),
        "etot_conv_thr_ry": bounded(real(control["etot_conv_thr"]), 1e-12, 0.1)
        if relaxation
        else None,
        "forc_conv_thr_ry_bohr": bounded(real(control["forc_conv_thr"]), 1e-12, 0.1)
        if relaxation
        else None,
    }

    def card(label, count):
        nonlocal cursor
        require(
            cursor + count < len(lines) and lines[cursor] == label, "qe_input_card_order_or_count"
        )
        values = lines[cursor + 1 : cursor + count + 1]
        cursor += count + 1
        return [line.split() for line in values]

    species = []
    for i, tokens in enumerate(card("ATOMIC_SPECIES", ntyp)):
        require(
            len(tokens) == 3 and tokens[0] in ELEMENTS and FILENAME.fullmatch(tokens[2]),
            "qe_input_species",
        )
        species.append(
            {
                "element": tokens[0],
                "mass_amu": bounded(real(tokens[1]), 0.1, 500),
                "filename": tokens[2],
                "starting_magnetization": bounded(
                    real(system[f"starting_magnetization({i + 1})"]), -0.999999, 0.999999
                )
                if spin == 2
                else None,
            }
        )
    require(
        len({s["element"] for s in species}) == len({s["filename"] for s in species}) == ntyp,
        "qe_distinct_species",
    )
    require(
        spin != 2 or any(s["starting_magnetization"] != 0 for s in species),
        "qe_magnetic_seed_scope",
    )
    basis = card("CELL_PARAMETERS angstrom", 3)
    require(all(len(row) == 3 for row in basis), "qe_input_cell_shape")
    basis = [[real(token) for token in row] for row in basis]
    require(
        basis[0][1] == basis[0][2] == basis[1][2] == 0
        and all(0 < basis[i][i] <= 10000 for i in range(3))
        and all(abs(x) <= 10000 for row in basis for x in row),
        "qe_input_cell_scope",
    )
    atoms = []
    for tokens in card("ATOMIC_POSITIONS crystal", nat):
        require(
            len(tokens) == 4 and tokens[0] in {s["element"] for s in species}, "qe_input_atom_shape"
        )
        fractional = [real(token) for token in tokens[1:]]
        require(all(0 <= x <= 1 for x in fractional), "qe_input_fractional_scope")
        atoms.append({"element": tokens[0], "fractional": fractional})
    composition = dict(Counter(atom["element"] for atom in atoms))
    require(set(composition) == {s["element"] for s in species}, "qe_unused_species")
    mesh = card("K_POINTS automatic", 1)[0]
    require(len(mesh) == 6 and cursor == len(lines), "qe_input_trailing_or_kpoints")
    settings["mesh"] = [bounded(real(value), 1, 64, integer=True) for value in mesh[:3]]
    settings["shifts"] = [bounded(real(value), 0, 1, integer=True) for value in mesh[3:]]
    return {
        "settings": settings,
        "species": species,
        "cell_vectors_angstrom": basis,
        "atoms": atoms,
        "composition": composition,
        "explicit_namelist_tokens": groups,
    }
