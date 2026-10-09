"""Small, explicit synthetic initialization fixtures; never solver output.

Ported from the pinned H1813 test generator. No private data or loaders.
"""

import xml.etree.ElementTree as ET


def add(parent, tag, value=None, **attributes):
    node = ET.SubElement(parent, tag, {key: str(value) for key, value in attributes.items()})
    if value is not None:
        node.text = str(value)
    return node


def initialization_outputs(source):
    geometry = source["geometry"]["source"]
    settings = source["derived_settings"]["namelist_literals"]
    assert source["preparation_phase"] == "initialize"
    root = ET.Element("{http://www.quantum-espresso.org/ns/qes/qes-1.0}espresso", {"Units": "Hartree atomic units"})
    root.append(ET.Comment("SYNTHETIC FIXTURE; NOT QE OUTPUT OR EXECUTION EVIDENCE"))
    info = add(root, "general_info")
    add(info, "creator", NAME="PWSCF", VERSION="7.5")
    add(info, "xml_format", NAME="QEXSD", VERSION="25.05.21")
    inp, out = add(root, "input"), add(root, "output")
    for section in [inp, out]:
        add(add(section, "dft"), "functional", "PBESOL")
        structure = add(section, "atomic_structure", nat=4, bravais_index=geometry["ibrav"])
        cell = add(structure, "cell")
        for name, row in zip(["a1", "a2", "a3"], geometry["cell_vectors_bohr_decimal"], strict=True):
            add(cell, name, " ".join(row))
        positions = add(structure, "atomic_positions")
        for atom in geometry["atoms"]:
            add(
                positions,
                "atom",
                " ".join(atom["cartesian_bohr_decimal"]),
                name=atom["element"],
                index=atom["source_atom_index"],
            )
        species = add(section, "atomic_species", ntyp=len(geometry["species_rows"]))
        for row in geometry["species_rows"]:
            element, mass, pseudo = row.split()
            item = add(species, "species", name=element)
            add(item, "mass", mass)
            add(item, "pseudo_file", pseudo)
    for section, group in [(inp, "basis"), (out, "basis_set")]:
        basis = add(section, group)
        for key in ["ecutwfc", "ecutrho"]:
            add(basis, key, float(settings["SYSTEM"][key]) / 2)
    bands = add(inp, "bands")
    for key, value in [("nbnd", source["expected_nbnd"]), ("tot_charge", 0), ("occupations", "smearing")]:
        add(bands, key, value)
    add(bands, "smearing", "mp", degauss=float(settings["SYSTEM"]["degauss"]) / 2)
    ec = add(inp, "electron_control")
    for key, value in [
        ("conv_thr", 5e-13),
        ("mixing_beta", 0.7),
        ("mixing_mode", "plain"),
        ("diagonalization", "davidson"),
        ("max_nstep", settings["ELECTRONS"]["electron_maxstep"]),
    ]:
        add(ec, key, value)
    for section, group in [(inp, "spin"), (out, "magnetization")]:
        spin = add(section, group)
        for key in ["lsda", "noncolin", "spinorbit"]:
            add(spin, key, "false")
    control = add(inp, "control_variables")
    for key, value in [
        ("calculation", "scf"),
        ("prefix", source["derived_settings"]["prefix"]),
        ("restart_mode", "from_scratch"),
        ("forces", "true"),
        ("stress", "true"),
        ("nstep", settings["CONTROL"]["nstep"]),
        ("max_seconds", 600),
    ]:
        add(control, key, value)
    add(add(inp, "ion_control"), "ion_dynamics", "none")
    add(add(inp, "cell_control"), "cell_dynamics", "none")
    attributes = {f"nk{i + 1}": value for i, value in enumerate(source["derived_settings"]["mesh"])}
    attributes.update(k1=0, k2=0, k3=0)
    add(add(inp, "k_points_IBZ"), "monkhorst_pack", **attributes)
    convergence = add(add(out, "convergence_info"), "scf_conv")
    add(convergence, "convergence_achieved", "false")
    add(convergence, "n_scf_steps", 0)
    add(convergence, "scf_error", 0)
    add(root, "exit_status", 255)
    add(root, "closed", "SYNTHETIC-NOT-RUNTIME-TIMESTAMP")
    stdout = (
        f"SYNTHETIC TEST FIXTURE; NOT A MINI CAPTURE\nProgram PWSCF v.7.5 starts\n"
        f"number of atoms/cell = 4\nnumber of atomic types = {len(source['pseudopotentials'])}\n"
        f"number of electrons = {source['expected_valence_electrons']:.2f}\n"
        f"number of Kohn-Sham states = {source['expected_nbnd']}\n"
    )
    return root, (stdout + "JOB DONE.\n").encode()
