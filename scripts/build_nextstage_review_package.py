"""Prepare metadata-only review queues; do not manufacture adjudication or gold labels."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEED = "api/services/resources/material_recovery_batch_20261008_seed.json"
BENCH = "docs/data/discovery-batches-20261008/benchmark-suite-v1.json"
CAT = "frontend/public/research-hypotheses/source-computed-candidates-2026-10-07.json"

# Different questions on one source remain one leakage group, never independent tests.
# Insertion order binds prompts to the frozen sixteen-row seed inventory by formula.
PROMPTS = {
    "(La,Y)H6": ("What transition is assigned to (La,Y)H6 in arXiv:2012.04787v1, including uncertainty?", "Can the H10 pressure and 253 K transition be assigned to the H6 occurrence?", "(La,Y)H6 的 La:Y 比例、相纯度、压力和判据是否已经明确？"),
    "Nb4C3O2": ("Which unstrained and 2% strained Tc values does arXiv:2403.06380 report for Nb4C3O2?", "Does a catalogue value of 23 K identify the same Nb4C3O2 state as the source's 25 or 29 K calculations?", "Nb4C3O2 的这些 Tc 是实验测量还是计算结果，能否跨应变状态合并？"),
    "MgH26": ("What Tc methods, pressure, lambda and omega-log qualify the MgH26 row in arXiv:2308.15031?", "Can MgH26's computed table row be replaced with a LaMg3H28 result from the same paper?", "MgH26 的 22、23、23 K 分别属于哪些求解方法，是否表示三次独立实验？"),
    "CaFe0.93Co0.07AsH": ("What Co fraction and Tc are paired in arXiv:1312.5818 for CaFe0.93Co0.07AsH?", "Is synthesis pressure in this paper a measurement pressure for the retained Tc occurrence?", "CaFe0.93Co0.07AsH 的 x=0.07 与 x=0.09 是否属于同一样品状态？"),
    "CaFe0.95Ni0.05AsF": ("What nominal Ni fraction and pellet Tc does arXiv:0811.1147 report?", "Does the inspected source window establish onset, midpoint or zero-resistance Tc for CaFe0.95Ni0.05AsF?", "CaFe0.95Ni0.05AsF 的名义组成能否直接作为已审核的实际样品组成？"),
    "Re6Se8Cl2": ("What transition and treatment context are retained for Re6Se8Cl2 in arXiv:1906.10785?", "Can a transition after annealing identify the untreated Re6Se8Cl2 bulk phase without a post-treatment sample association?", "Re6Se8Cl2 的退火薄片与原始材料身份是否已经对应，缺少哪些核查？"),
    "SmFe0.80Co0.20AsO": ("How do Tc values differ at x=0.1, 0.15 and 0.2 in arXiv:1007.5121?", "Do duplicate records of SmFe0.80Co0.20AsO establish independent replication?", "SmFe0.80Co0.20AsO 的 9 K 能否与其他 Co 掺杂比例的 14 或 15.5 K 合并？"),
    "Ba3Rh4Ge16": ("What sample form and transition does arXiv:2112.00644 report for Ba3Rh4Ge16?", "Is the retained lambda for Ba3Rh4Ge16 inferred from reported measurements or a native DFPT result?", "Ba3Rh4Ge16 的方法推断与第一性原理计算应如何区分，来源定位在哪里？"),
    "CrB2": ("What pressure range and superconducting transition are inspected in arXiv:2109.15213 for CrB2?", "Is 88.5 K a superconducting Tc, and does the 12 GPa AF substudy define the maximum pressure of the entire paper?", "CrB2 的常压反铁磁结果能否直接证明约 100 GPa 下同一状态的磁序？"),
    "(Mo0.96Ti0.04)0.8B2": ("What transition is reported for carbon-free (Mo0.96Ti0.04)0.8B2 in arXiv:2302.14272?", "Does no observed transition down to 1.8 K in the carbon-doped sample mean Tc equals zero?", "碳掺杂与未掺杂的 (Mo0.96Ti0.04)0.8B2 能否共享同一个超导标签？"),
    "Nb2P5": ("What Tc is inspected for Nb2P5 in arXiv:2010.05737?", "Can Nb2P5 synthesis or pressing pressure be treated as superconducting measurement pressure?", "Nb2P5 的 Tc 判据和实际测量压力是否已完成样品级对应？"),
    "Be0.024Al0.976": ("What model and Tc qualify Be0.024Al0.976 in arXiv:1907.07597?", "Do bracketed elemental-metal experiments independently validate the virtual-crystal Be-Al alloy calculation?", "Be0.024Al0.976 的 VCA 结果能否标注为实测超导转变？"),
    "Nb4Cu0.2SiSb2": ("How are the approximately 1.2 K and 1.16 K transitions described in arXiv:2208.04834?", "Does the inspected paper explicitly print a 50% criterion, and can a parent heat-capacity result be transferred to Nb4Cu0.2SiSb2?", "Nb4Cu0.2SiSb2 与母体材料的热容、输运结果是否属于同一实验样品？"),
    "NbScTiZr": ("What Tc values belong to the cast, 800 C and 1000 C NbScTiZr states in arXiv:2311.00195?", "Can the 7.9, 9 and 8.7 K values be collapsed into one state-independent NbScTiZr training label?", "NbScTiZr 的退火温度是不是超导测量温度，来源中如何区分？"),
    "Re7Ta3": ("Which Re7Ta3 structural states and transition descriptions appear in arXiv:2402.07580?", "Does an onset transition establish time-reversal-symmetry breaking or validate an unrelated model input?", "Re7Ta3 的 alpha-Mn I-43m 与六方相能否合并为同一个材料状态？"),
    "Ta2PdSe5": ("Which susceptibility and transport transition criteria qualify Ta2PdSe5 in arXiv:1412.6983?", "Are 2.6, 2.5, 2.2 and 2.0 K interchangeable Tc measurements, and is the impurity association resolved?", "Ta2PdSe5 的起始、中点、零电阻与磁化率判据应如何分别保留？"),
}


def load(relative):
    data = (ROOT / relative).read_bytes()
    return json.loads(data), {"path": relative, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def build(seed, benchmark, catalogue, pins):
    if any(seed.get(k) is not False for k in ("human_reviewed", "scientific_acceptance", "ml_training_approved", "database_changed")):
        raise ValueError("seed_authority_changed")
    if any(c["human_scientific_review"] is not None for c in catalogue["candidates"]):
        raise ValueError("hypothesis_review_state_changed")
    if {r["formula"] for r in seed["rows"]} != set(PROMPTS):
        raise ValueError("prompt_inventory_does_not_match_seed")
    for row in seed["rows"]:
        if any(row.get(k) is not False for k in ("human_reviewed", "scientific_acceptance", "database_changed")):
            raise ValueError("seed_review_state_changed; prepare_a_new_protocol")
    candidates = [c for report in seed["reports"] for c in report["candidates"]]
    ledger, questions = [], []
    for row in seed["rows"]:
        references = [{"observation_id": o["id"], "field": o["field"], "value": o["value"],
                       "knowledge_origin": o["knowledge_origin"], "scope": o["scope"], "source": o["source"]}
                      for o in row["observations"]]
        paper_ids = sorted({o["source"]["paper_id"] for o in row["observations"]})
        proposals = [c for c in candidates if c["material_id"] == row["material_id"]]
        ledger.append({"material_id": row["material_id"], "formula": row["formula"],
                       "summary": row["summary"], "observations": references,
                       "pending_candidate_ids": [c["candidate_id"] for c in proposals],
                       "retained_result_refs": row["retained_result_refs"], "unknowns": row["unknowns"],
                       "source_scope": "inherited_AI_inspection_metadata; no_new_original_document_adjudication",
                       "review_status": "awaiting_independent_human_review", "reviewers": [], "resolver": None,
                       "decision": None, "scientific_acceptance": False, "ml_training_approved": False,
                       "next_action": "Inspect original pages, resolve sample/state/criterion and source rights; append review decisions without replacing retained records."})
        for index, prompt in enumerate(PROMPTS[row["formula"]]):
            questions.append({"id": f"review-question:{row['material_id']}:{index + 1}",
                              "query": prompt, "language": "zh" if index == 2 else "en",
                              "task": ("numerical", "comparison_or_clarification", "mixed_source_context")[index],
                              "material_ids": [row["material_id"]], "source_group_ids": paper_ids,
                              "source_observation_ids": [o["observation_id"] for o in references],
                              "source_reference_basis": "material_review.rows[].observations by exact observation_id; conditions remain attached there",
                              "draft_answer_context": row["summary"], "unresolved_conditions": row["unknowns"],
                              "annotation_status": "unadjudicated_acquisition_draft", "split": "unassigned",
                              "held_out_eligible": False, "scientific_support_label": None,
                              "execution_status": "not_run", "judgments": []})
    for index, case in enumerate(benchmark["cases"]):
        anchor = case["kind"] == "experimental_identity_anchor"
        prompt = (f"What source-state limitations and counterexamples qualify the proposed {case['formula']} comparison?"
                  if not anchor else f"Does the cited experimental {case['formula']} prior establish the same sample and structure as the ordered calculation?")
        if index >= 8:
            prompt = f"{case['formula']} 的来源结果、结构状态与对照是否支持实验超导或室温超导结论？请保留未解决条件。"
        questions.append({"id": "review-question:" + case["id"], "query": prompt,
                          "language": "zh" if index >= 8 else "en", "task": "comparison_or_mechanism",
                          "material_ids": [], "composition_label": case["formula"],
                          "source_group_ids": ([case["url"]] if anchor else ["doi:10.24435/materialscloud:qv-bq"]),
                          "benchmark_case_id": case["id"], "benchmark_file": BENCH,
                          "draft_answer_context": case.get("risk_summary", case.get("acceptance_rule")),
                          "source_pointer": case.get("source_pointer", case.get("locator")),
                          "selection_outcomes_known": True, "annotation_status": "unadjudicated_acquisition_draft",
                          "split": "unassigned", "held_out_eligible": False,
                          "scientific_support_label": None, "execution_status": "not_run", "judgments": []})
    if len(questions) != 60:
        raise ValueError("expected_60_questions")
    authority = {"human_reviewed": False, "scientific_acceptance": False, "ml_training_approved": False,
                 "database_changed": False}
    return {
        "schema_version": "sclib-nextstage-review-preparation/1.0.0", "version": "2026-10-09-v1",
        **authority, "input_pins": pins, "seed_id": seed["seed_id"], "seed_sha256": seed["seed_sha256"],
        "material_review": {"counts": seed["counts"], "count_relationship": "55 observations and 34 candidate facts can overlap; do not sum as independent facts", "rows": ledger},
        "retrieval_acquisition": {"count": len(questions), "language_counts": dict(Counter(q["language"] for q in questions)),
                                  "task_counts": dict(Counter(q["task"] for q in questions)),
                                  "protocol": "docs/SCIENTIFIC_EVALUATION_PROTOCOL.md; inventory is not an executable RG04c corpus package",
                                  "gold_set": False, "live_provider_calls": 0,
                                  "split_status": "No train/test split assigned. Connect shared Work, original experiment, composition/state and translations before freezing a split.",
                                  "coverage_gaps": ["cuprates", "nickelates", "heavy_fermions", "organics", "interfaces", "withdrawn_sources"],
                                  "target_120_question_protocol_complete": False, "questions": questions},
        "ml_readiness": {"scope": "these16_source_recovery_rows_and103_source_hypotheses_only; not_a_database_wide_eligibility_audit",
                         "material_rows_checked": len(ledger), "source_hypotheses_checked": len(catalogue["candidates"]),
                         "eligible_labels_established": 0, "source_hypotheses_license": catalogue["dataset_source"]["license"],
                         "hypothesis_human_review_count": sum(c["human_scientific_review"] is not None for c in catalogue["candidates"]),
                         "blockers": ["source_status_and_use_rights_not_adjudicated_for16", "sample_state_association_pending_for16", "no_independent_human_adjudication", "no_task_specific_label_approval", "whole_corpus_Work_root_composition_time_leakage_audit_not_executed"],
                         "training_executed": False, "next_action": "Resolve scientific labels and task-specific permissions before membership, connected splits or baseline training."},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--markdown-output", type=Path)
    args = parser.parse_args()
    with args.output.open("x", encoding="utf-8") as handle:
        seed, seed_pin = load(SEED)
        benchmark, bench_pin = load(BENCH)
        catalogue, cat_pin = load(CAT)
        # Bind the prompts and generator implementation as well as inherited inputs.
        script = Path(__file__).read_bytes()
        package = build(seed, benchmark, catalogue, [seed_pin, bench_pin, cat_pin,
                        {"path": "scripts/build_nextstage_review_package.py", "bytes": len(script), "sha256": hashlib.sha256(script).hexdigest()}])
        json.dump(package, handle, indent=2, ensure_ascii=False, allow_nan=False)
        handle.write("\n")
    if args.markdown_output:
        with args.markdown_output.open("x", encoding="utf-8") as handle:
            handle.write(render_markdown(package))
    print(json.dumps({"material_review_rows": 16, "acquisition_questions": 60, "scientific_acceptance": False}))


def render_markdown(package):
    lines = ["# Source review queue and retrieval question inventory", "",
             "Version: 2026-10-09-v1. Generated from pinned public metadata.", "",
             "All decisions remain pending. This is an AI-assisted acquisition draft, not human adjudication,",
             "a gold set, an executed retrieval benchmark or an approved training dataset.", "",
             "The [machine-readable package](review-preparation-v1.json) retains original source revisions,",
             "page/span hashes, Result references, input pins and every unresolved condition.", "",
             "## Sixteen material reviews", ""]
    for row in package["material_review"]["rows"]:
        lines.extend(["### " + row["formula"], "", "Material: `" + row["material_id"] + "`. Reviewers: unassigned. Decision: pending.", "", row["summary"], "", "Inspected source windows:", ""])
        for observation in row["observations"]:
            source = observation["source"]
            lines.append(f"- {observation['field']}: {observation['value']}. Scope: {observation['scope']}. [{source['source_revision']}, p. {source['locator']['page']}]({source['source_url']}#page={source['locator']['page']}).")
        lines.extend(["", "Resolve before accepting a label:", ""])
        lines.extend("- " + unknown for unknown in row["unknowns"])
        lines.extend(["", "Append two independent source/state judgments and a resolver decision where needed; check source-use permission separately.", ""])
    lines.extend(["## Sixty draft retrieval questions", "",
                  "40 English and 20 Chinese questions. All are unassigned to a split and not run.",
                  "Related source questions and known retrospective cases must not be treated as independent held-out examples.", ""])
    for i, question in enumerate(package["retrieval_acquisition"]["questions"], 1):
        lines.extend([f"{i}. {question['query']} (`{question['id']}`; {question['language']}; {question['task']})", ""])
    return "\n".join(lines)


if __name__ == "__main__":
    main()
