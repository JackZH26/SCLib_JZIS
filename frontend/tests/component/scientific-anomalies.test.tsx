import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { JointEpcNotice, PropertyEvidenceValue } from "@/components/PropertyEvidence";
import { RawScientificArchive, RecordAnomalyReview, ScientificAnomalyNotice } from "@/components/ScientificAnomalies";
import { MaterialTable } from "@/components/MaterialTable";
import type { MaterialPropertyEvidence, MaterialSummary } from "@/lib/api";
import { propertyJsonLd, selectedProperty, supportedPropertyDescription } from "@/lib/property-evidence";
import { anomalyStatus, hasRawArchive } from "@/lib/scientific-anomalies";
import { atomicItem, propertyEnvelope } from "../fixtures/property-evidence";
import { anomalyAssessment, materialAnomalyReview, rawArchive } from "../fixtures/scientific-anomalies";

describe("scientific anomaly display", () => {
  it("fails closed for pre-anomaly property caches and unknown policy versions", () => {
    const old = { ...propertyEnvelope(atomicItem("tc_max", 60)), version: "property-evidence/1.0.0" } as unknown as MaterialPropertyEvidence;
    expect(selectedProperty(old, "tc_max")).toBeNull();
    expect(propertyJsonLd(old, "tc_max")).toBeNull();
    const wrong = propertyEnvelope(atomicItem("tc_max", 60));
    wrong.anomaly_policy_version = "unknown" as never;
    expect(supportedPropertyDescription(wrong, "tc_max")).toBeNull();
  });

  it("does not turn a source 60 K with a 45 K reference into a 45 K headline", () => {
    const item = atomicItem("tc_max", 60, { anomaly_review: anomalyAssessment() });
    const envelope = propertyEnvelope(item);
    expect(selectedProperty(envelope, "tc_max")).toBeNull();
    expect(propertyJsonLd(envelope, "tc_max")).toBeNull();
    envelope.properties.tc_max = { ...envelope.properties.tc_max, selected: null, status: "untraceable", evidence: [item], warnings: ["anomaly_review_required"] };
    render(<PropertyEvidenceValue evidence={envelope} field="tc_max" />);
    expect(screen.getAllByText("Anomaly review required").length).toBeGreaterThan(0);
    expect(screen.getByText(/60 K · record origin/)).toHaveTextContent("not the headline selection");
    expect(screen.queryByText("45 K")).not.toBeInTheDocument();
    expect(screen.getByText(/retained proposals, not public-eligible/)).toBeInTheDocument();
  });

  it("uses field-scoped review without declaring every property of a record invalid", () => {
    const item = atomicItem("lambda_eph", 2);
    item.anomaly_review = anomalyAssessment(item.result_id, "tc_max");
    expect(selectedProperty(propertyEnvelope(item), "lambda_eph")).not.toBeNull();
    item.anomaly_review.review_required_properties = ["*"];
    expect(selectedProperty(propertyEnvelope(item), "lambda_eph")).toBeNull();
  });

  it("keeps an unresolved state anomaly out of the displayed EPC association", () => {
    const lambda = atomicItem("lambda_eph", 2);
    lambda.anomaly_review = anomalyAssessment(lambda.result_id, "pressure_gpa");
    const omega = atomicItem("omega_log_k", 800);
    const envelope = propertyEnvelope(lambda, omega);
    envelope.joint_epc = { status: "eligible", selected: { pair_id: "synthetic-pair", lambda, omega_log: omega, eligible_meaning: "association_complete_only" }, pairs: [], warnings: [] };
    expect(selectedProperty(envelope, "lambda_eph")).not.toBeNull();
    render(<JointEpcNotice evidence={envelope} />);
    expect(screen.queryByText("Inspect the linked EPC pair")).not.toBeInTheDocument();
    expect(screen.getByText(/No association-complete EPC input is established here/)).toBeInTheDocument();
  });

  it.each(["missing", "wrong_result", "unknown_version"])("does not accept an incomplete or mismatched item assessment: %s", mutation => {
    const item = atomicItem("tc_max", 20);
    if (mutation === "missing") delete item.anomaly_review;
    if (mutation === "wrong_result") item.anomaly_review!.result_id = "different-record";
    if (mutation === "unknown_version") item.anomaly_review!.version = "future" as never;
    expect(selectedProperty(propertyEnvelope(item), "tc_max")).toBeNull();
  });

  it("states no findings is not scientific acceptance, including parser limitations", () => {
    const review = atomicItem("tc_max", 20).anomaly_review!;
    render(<RecordAnomalyReview assessment={review} />);
    expect(screen.getByText("No findings under this policy")).toBeInTheDocument();
    expect(screen.getByText(/No findings is not scientific acceptance/)).toBeInTheDocument();
    expect(anomalyStatus({ ...review, status: "format_invalid" })).toBe("Format or parser review required");
    expect(anomalyStatus({ ...review, version: "future" })).toBe("Review status unavailable");
  });

  it("shows policy and counts without multiplying a material into several table rows", () => {
    const material = { id: "synthetic", formula: "TEST", anomaly_review: materialAnomalyReview(), total_papers: 1, variant_count: 0 } as MaterialSummary;
    render(<MaterialTable rows={[material]} />);
    expect(screen.getAllByRole("row")).toHaveLength(2);
    expect(screen.getByText("Scientific anomaly review required")).toBeInTheDocument();
    expect(screen.getByText(/Retained records assessed: 1/)).toBeInTheDocument();
    expect(screen.getByText(/not independent experiments/)).toBeInTheDocument();
  });

  it("does not label a contradictory or partial summary as no findings", () => {
    const review = { ...materialAnomalyReview(), needs_review: false };
    render(<ScientificAnomalyNotice review={review} />);
    expect(screen.getByText("Anomaly policy unavailable")).toBeInTheDocument();
    expect(screen.queryByText("Operational policy: no findings")).not.toBeInTheDocument();
  });

  it("exposes only the authorized retained Archive as escaped text, without claiming full history", () => {
    const archive = rawArchive();
    const { container } = render(<RawScientificArchive archive={archive} />);
    expect(screen.getByLabelText("Retained raw scientific fields for synthetic-result:tc_max")).toHaveTextContent('"tc_kelvin": "60 K"');
    expect(container.querySelector("script")).toBeNull();
    expect(screen.getByText(/not a full historical archive/)).toBeInTheDocument();
    expect(screen.getByText(/not necessarily a verbatim source quotation/)).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("does not use missing, unknown-version or differently scoped Archive payloads", () => {
    const archive = rawArchive();
    expect(hasRawArchive({ ...archive, version: "future" })).toBe(false);
    expect(hasRawArchive({ ...archive, scope: "quarantine" })).toBe(false);
    expect(hasRawArchive({ ...archive, raw_field_policy: "all_private_data" })).toBe(false);
    render(<RawScientificArchive archive={undefined} />);
    expect(screen.getByText(/Archive unavailable in this response/)).toBeInTheDocument();
    expect(screen.queryByText("60 K")).not.toBeInTheDocument();
  });

  it("discloses bounded findings and Archive truncation without pretending omitted records are absent", () => {
    const archive = rawArchive();
    archive.truncated = true;
    archive.total = 101;
    archive.records[0].assessment.findings_truncated = true;
    render(<RawScientificArchive archive={archive} />);
    expect(screen.getByText(/Archive response is truncated/)).toBeInTheDocument();
    expect(screen.getByText(/absence from this list does not mean a rule did not fire/)).toBeInTheDocument();
  });
});
