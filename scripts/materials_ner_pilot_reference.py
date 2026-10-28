#!/usr/bin/env python3
"""Freeze a small assistant-read reference before the empirical Luna run.

These numeric/method anchors are incomplete and not independent human Gold.
Reference anchors are never supplied to the extraction worker.
"""
import json
from pathlib import Path
import sys

root = Path(sys.argv[1])
anchors = []


def add(aid, formula, value, method, page, **extra):
    anchors.append(dict(id=f"A{len(anchors)+1:03d}", work_id="arxiv:"+aid,
                        formula=formula, value=value, method=method, source_page=page,
                        kind="tc", **extra))


for val, pressure in ((4.6, 10.0), (6.0, 37.5)):
    add("2301.01120", "(PbSe)5(Bi2Se3)6", val, "resistivity", 7, pressure_gpa=pressure)
add("2504.00662", "TaIr2B2", 5.1, None, "HTML", note="Bulk Tc; do not force criterion from this anchor")
add("2504.00662", "TaIr2B2", 5.2, "resistivity", "HTML", criterion="onset")
formulas = ["Re3.5Os3.5Ta0.5Hf0.5Nb3", "Re3Os3Ta0.5Hf0.5Nb3",
            "Re3.5Os3.5Mo0.5Hf0.5Nb3", "Re3Os3Mo0.5Hf0.5Nb3", "Re3.5Os3.5Mo0.5W0.5Nb3"]
for method, page, values in [
    ("resistivity", 7, [4.52, 4.20, 4.94, 4.77, 5.11]),
    ("magnetization", 10, [3.91, 3.42, 4.39, 4.14, 4.45]),
    ("specific_heat", 14, [3.44, 2.88, 3.88, 3.39, 4.06]),
]:
    for formula, value in zip(formulas, values):
        add("2508.05010", formula, value, method, page)
for label, value, err in [("HSC2", 6.610, .007), ("HSC4", 6.63, .01), ("Nb", 8.897, .001)]:
    add("2509.22278", "Nb" if label=="Nb" else "HfNbTaTiZr", value, "magnetization", 4,
        sample_label=label, uncertainty=err,
        note="Nb is a comparison film; prior-sample versus reanalysis requires attribution review" if label=="Nb" else "reported parenthetical uncertainty")
for label, values in [("A", [(42., "onset"), (15.5, "unspecified"), (6., "zero_resistance")]),
                       ("B", [(45., "onset"), (19.5, "unspecified"), (10., "zero_resistance")])]:
    for value, criterion in values:
        add("2604.07807", "La2PrNi2O7", value, "resistivity", 2,
            sample_label=label, criterion=criterion,
            note="Secondary-transition feature must retain stage, not become bulk primary Tc" if criterion=="unspecified" else "Approximate value")
add("2012.05654", "La7Ni3", 2.3, "magnetization", 2, uncertainty=.1)
add("2012.05654", "La7Ni3", 2.6, "resistivity", 9, criterion="onset")
for formula, values in [("BC5", [34.6, 41.5, 41.2]), ("B2C3N", [29.3, 37.3, 38.2]),
                        ("B4C5N3", [16.9, 17.9, 22.9]), ("MgB2", [22.5, 22.9, 40.7])]:
    for model, value in zip(["Allen-Dynes", "isotropic_Migdal_Eliashberg", "anisotropic_Migdal_Eliashberg"], values):
        add("2410.02104", formula, value, model, 4, origin="computed", mu_star=.1,
            note="Version 2 Table I; separate calculation protocols")
payload = {"schema": "materials-pilot-anchors/1", "reviewer_type": "assistant_source_read",
           "independent_gold": False, "complete_inventory": False,
           "matching_policy": "Same paper, normalized raw formula and numeric value are only a preliminary hit. Method, sample, state, origin and criterion need separate adjudication. A numeric hit is never scientific acceptance.",
           "anchors": anchors,
           "negative_checks": [
               {"work_id": "arxiv:2508.05010", "rule": "No 4.655 K point derived from the abstract interval"},
               {"work_id": "arxiv:2504.00662", "rule": "2.4/2.5 K surface BCS parameter is not unqualified bulk Tc"},
               {"work_id": "arxiv:2509.22278", "rule": "HSC1 and HSC3 non-detection down to 1.9 K; never Tc=0"},
               {"work_id": "arxiv:2604.07807", "rule": "150 mTorr is deposition pressure; do not attach it to ambient transport"}]}
path = root / "reference_anchors.json"
if path.exists():
    raise ValueError("reference already frozen")
path.write_text(json.dumps(payload, indent=2) + "\n")
print(json.dumps({"anchors": len(anchors), "independent_gold": False, "path": str(path)}))
