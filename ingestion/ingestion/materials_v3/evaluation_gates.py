"""Field metrics and independently reviewed evidence gates; never manufacture gold."""

from collections import defaultdict

from .contract import digest

CORE = {"tc", "superconductivity_outcome"}
SEVERE = {
    "wrong_material",
    "wrong_sample_or_point",
    "wrong_condition_role",
    "primary_cited_confusion",
    "observed_computed_confusion",
    "negative_as_zero_tc",
    "unrelated_parameter_bundle",
    "wrong_unit_order_of_magnitude",
}


def _slots(by_work, works):
    slots = defaultdict(list)
    for work in works:
        for claim in by_work[work]:
            anchor = claim.get("anchor_id") or digest(claim["point"])
            slots[(work, anchor, claim["property"])].append(claim)
    return slots


def _macro(pairs, field):
    labels = sorted({c[field] for pair in pairs for c in pair if c is not None})
    result = {}
    for label in labels:
        tp = sum(
            p is not None and g is not None and p[field] == g[field] == label for p, g in pairs
        )
        fp = sum(
            p is not None and p[field] == label and (g is None or g[field] != label)
            for p, g in pairs
        )
        fn = sum(
            g is not None and g[field] == label and (p is None or p[field] != label)
            for p, g in pairs
        )
        result[label] = {"tp": tp, "fp": fp, "fn": fn, "f1": 2 * tp / (2 * tp + fp + fn)}
    return {
        "by_class": result,
        "macro_f1": sum(r["f1"] for r in result.values()) / len(result) if result else None,
    }


def field_metrics(predicted, gold, works, count_tuples):
    ps, gs = _slots(predicted, works), _slots(gold, works)
    pairs, ambiguous = [], []
    for slot in sorted(ps.keys() | gs.keys()):
        pp, gg = ps[slot], gs[slot]
        if len(pp) == len(gg) == 1:
            pairs.append((pp[0], gg[0]))
        else:
            # Duplicated or ambiguous anchors cannot receive a guessed alignment.
            pairs.extend((p, None) for p in pp)
            pairs.extend((None, g) for g in gg)
            if len(pp) > 1 or len(gg) > 1:
                ambiguous.append(list(slot))
    numeric = [
        (p, g)
        for p, g in pairs
        if p
        and (
            "relation" in p["quantity"]
            or isinstance(p["quantity"].get("unresolved_raw"), dict)
            and "relation" in p["quantity"]["unresolved_raw"]
        )
    ]
    correct = sum(g is not None and p["quantity"] == g["quantity"] for p, g in numeric)
    keys = sorted(
        {c["property"] for by_work in (predicted, gold) for w in works for c in by_work[w]} - CORE
    )
    extensions = {
        k: count_tuples(
            [c for w in works for c in predicted[w] if c["property"] == k],
            [c for w in works for c in gold[w] if c["property"] == k],
        )
        for k in keys
    }
    f1s = [m["f1"] for m in extensions.values() if m["f1"] is not None]
    return {
        "numeric_unit_accuracy": {
            "correct": correct,
            "denominator": len(numeric),
            "accuracy": correct / len(numeric) if numeric else None,
        },
        "knowledge_origin": _macro(pairs, "knowledge_origin"),
        "source_role": _macro(pairs, "source_role"),
        "extension_properties": {
            "by_property": extensions,
            "macro_f1": sum(f1s) / len(f1s) if f1s else None,
        },
        "ambiguous_alignment_slots": ambiguous,
    }


def evidence_audit(output, audit, works, annotators, adjudicator):
    claims = [c for w in works for c in output["claims_by_work"][w]]
    required = {digest(c) for c in claims}
    if (
        not isinstance(audit, dict)
        or audit.get("status") != "adjudicated"
        or audit.get("manifest_sha256") != output["manifest_sha256"]
        or not output.get("config_sha256")
        or audit.get("config_sha256") != output["config_sha256"]
        or audit.get("annotators") != annotators
        or audit.get("adjudicator") != adjudicator
    ):
        return {"status": "independent_prediction_audit_required"}
    items = audit.get("items", {})
    if not required <= items.keys():
        return {
            "status": "prediction_audit_incomplete",
            "missing_claims": sorted(required - items.keys()),
        }
    for item in (items[key] for key in required):
        if (
            type(item.get("evidence_support")) is not bool
            or type(item.get("locator_resolves")) is not bool
            or not isinstance(item.get("severe_errors"), list)
            or any(e not in SEVERE for e in item["severe_errors"])
        ):
            raise ValueError("prediction_audit_label_invalid")
    support = sum(items[digest(c)]["evidence_support"] for c in claims)
    locators = sum(items[digest(c)]["locator_resolves"] for c in claims)
    severe = sum(len(items[digest(c)]["severe_errors"]) for c in claims)
    return {
        "status": "assessed" if claims else "insufficient_denominator",
        "denominator": len(claims),
        "evidence_support_precision": support / len(claims) if claims else None,
        "locator_resolves_rate": locators / len(claims) if claims else None,
        "severe_error_count": severe,
    }


def null_recovery(predicted, gold, works, baseline, tuple_key):
    if not isinstance(baseline, dict) or not set(works) <= baseline.keys():
        return {"status": "adjudicated_recoverable_baseline_required", "recall": None}
    recovered = total = 0
    for work in works:
        eligible = baseline[work]
        truth = {tuple_key(c) for c in gold[work]}
        if (
            not isinstance(eligible, list)
            or len(eligible) != len(set(eligible))
            or not set(eligible) <= truth
        ):
            raise ValueError("null_recovery_baseline_not_gold_confirmed")
        total += len(eligible)
        recovered += len(set(eligible) & {tuple_key(c) for c in predicted[work]})
    return {
        "status": "assessed" if total else "insufficient_denominator",
        "recovered": recovered,
        "recoverable_null_claims": total,
        "recall": recovered / total if total else None,
    }
