from ingestion.extract.materials_aggregator import _derive_summary
from ingestion.nims import classify_family


def test_elemental_superconductors_are_classified_separately() -> None:
    assert classify_family("Hg") == "elemental"
    assert classify_family("Hg1") == "elemental"
    assert classify_family("Pb") == "elemental"
    assert classify_family("Nb") == "elemental"
    assert classify_family("Sn") == "elemental"
    assert classify_family("Li6") == "elemental"
    assert classify_family("Li7") == "elemental"
    assert classify_family("B4") == "elemental"
    assert classify_family("α-Ta") == "elemental"
    assert classify_family("Pb(111)") == "elemental"
    assert classify_family("(√3×√3)-Sn") == "elemental"


def test_elemental_rule_does_not_catch_compounds_or_prose() -> None:
    assert classify_family("HgBa2Ca2Cu3O8") == "cuprate"
    assert classify_family("Nb3Sn") == "conventional"
    assert classify_family("Mercury") is None
    assert classify_family("Pb-doped") is None
    assert classify_family("BI3") != "elemental"
    assert classify_family("RE124") != "elemental"
    assert classify_family("SN1") != "elemental"
    assert classify_family("Al0.3") != "elemental"
    assert classify_family("Sn4") != "elemental"
    assert classify_family("Al37") != "elemental"
    assert classify_family("La214") != "elemental"
    assert classify_family("Bi:2212") != "elemental"
    assert classify_family("Bechgaardsalts") != "elemental"
    assert classify_family("Bernalbilayergraphene") != "elemental"


def test_aggregator_elemental_rule_overrides_ner_conventional_vote() -> None:
    summary = _derive_summary(
        "Hg",
        [{
            "formula": "Hg",
            "family": "conventional",
            "tc_kelvin": 4.15,
            "paper_id": "nims:Hg",
            "confidence": 0.99,
            "evidence_type": "primary_experimental",
            "measurement": "resistivity",
            "year": 1911,
        }],
    )

    assert summary["family"] == "elemental"
    assert summary["is_unconventional"] is False
