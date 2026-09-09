import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MaterialVisibilityNotice, SourceVisibilityNotice } from "@/components/MaterialVisibilityNotice";
import { RawScientificArchive } from "@/components/ScientificAnomalies";
import { MaterialTable } from "@/components/MaterialTable";
import { ScientificMatches } from "@/components/ScientificMatches";
import { archiveExport, eligibleForScientificSeo, knownOccurrenceVisibility, knownSourceVisibility, knownVisibility, visibilityLabel, visibilityWarning } from "@/lib/material-visibility";
import type { MaterialSummary, MatchingScientificResult } from "@/lib/api";
import { materialVisibility, occurrenceVisibility, sourceScopedMaterialVisibility, sourceVisibility } from "../fixtures/material-visibility";
import { rawArchive } from "../fixtures/scientific-anomalies";

describe("shared visibility contract", () => {
  it.each([undefined, {}, { ...materialVisibility(), version: "future" }, { ...materialVisibility(), scientific_acceptance: true }, { ...materialVisibility(), review_revision: "" }, { ...materialVisibility("pending"), public_catalogue_eligible: true }])("missing or contradictory visibility never enables scientific SEO: %j", value => {
    expect(knownVisibility(value)).toBeNull();
    expect(eligibleForScientificSeo(value)).toBe(false);
    expect(visibilityLabel(value)).toContain("visibility unverified");
  });

  it.each(["pending", "disputed", "corrected", "retracted", "unknown"] as const)("clearly marks %s as Archive and not scientific approval", state => {
    const value = materialVisibility(state);
    render(<MaterialVisibilityNotice visibility={value} />);
    expect(eligibleForScientificSeo(value)).toBe(false);
    expect(screen.getByLabelText("material visibility")).toHaveTextContent("Archive");
    expect(screen.getByLabelText("material visibility")).toHaveTextContent("synthetic-review-revision");
    expect(screen.getByLabelText("material visibility").textContent).not.toMatch(/[\u3400-\u9fff]/);
  });

  it("eligible catalogue is a read policy, not a scientifically verified result", () => {
    render(<MaterialVisibilityNotice visibility={materialVisibility()} />);
    expect(eligibleForScientificSeo(materialVisibility())).toBe(true);
    expect(screen.getByText("Catalogue eligible — not scientific approval")).toBeInTheDocument();
    expect(screen.getByText(/not experimental confirmation/)).toBeInTheDocument();
    expect(eligibleForScientificSeo({ ...materialVisibility(), source_status: "retracted" })).toBe(false);
  });

  it("does not render private notes or arbitrary reason messages", () => {
    render(<MaterialVisibilityNotice visibility={{ ...materialVisibility("pending"), review_reason: "PRIVATE REVIEWER EMAIL", reason_messages: ["PRIVATE NOTE"] }} />);
    expect(screen.queryByText(/PRIVATE/)).not.toBeInTheDocument();
  });

  it("keeps current visibility and warnings attached to downloaded raw records", () => {
    const archive = rawArchive();
    const visibility = materialVisibility("pending");
    render(<RawScientificArchive archive={archive} visibility={visibility} />);
    const href = screen.getByRole("link", { name: /Download authorized Archive/ }).getAttribute("href")!;
    const payload = JSON.parse(decodeURIComponent(href.split(",").slice(1).join(",")));
    expect(payload.visibility).toEqual(visibility);
    expect(payload.scientific_acceptance).toBe(false);
    expect(payload.visibility_warning).toContain("not be treated as an accepted");
    expect(payload.archive.records[0].raw.tc_kelvin).toBe("60 K");
  });

  it("an old Archive response exports explicitly unverified metadata", () => {
    const payload = archiveExport(rawArchive());
    expect(payload.visibility).toBeNull();
    expect(payload.visibility_warning).toContain("metadata is unavailable");
    expect(payload.scientific_acceptance).toBe(false);
  });

  it("a restricted payload cannot be rendered or downloaded even if its flags conflict", () => {
    const visibility = { ...materialVisibility("quarantined"), archive_available: true };
    render(<RawScientificArchive archive={rawArchive()} visibility={visibility} />);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Retained raw scientific fields/)).not.toBeInTheDocument();
  });

  it("list rows carry their own pending warning and explicitly restricted rows are suppressed", () => {
    const row = { id: "pending", formula: "SYNTHETIC", total_papers: 1, variant_count: 0, visibility: materialVisibility("pending") } as MaterialSummary;
    render(<MaterialTable rows={[row, { ...row, id: "secret", formula: "RESTRICTED-FORMULA", visibility: materialVisibility("quarantined") }]} />);
    expect(screen.getByText("Archive — review pending")).toBeInTheDocument();
    expect(screen.queryByText("RESTRICTED-FORMULA")).not.toBeInTheDocument();
  });

  it("an unlinked retracted occurrence remains retracted without inventing a material revision", () => {
    const visibility = occurrenceVisibility("retracted");
    expect(knownVisibility(visibility)).toBeNull();
    expect(knownOccurrenceVisibility(visibility)?.review_revision).toBeNull();
    render(<MaterialVisibilityNotice visibility={visibility} scope="source occurrence" />);
    expect(screen.getByText("Archive — retracted source or claim")).toBeInTheDocument();
    expect(screen.getByText(/no material identity/)).toBeInTheDocument();
    expect(screen.getByText(/No resolved material revision/)).toBeInTheDocument();
  });

  it("numeric source-report matches do not promote unlinked occurrences to catalogue approval", () => {
    const result = { result_id: "result:test", record_index: 0, formula: "TEST", tc_lower_bound_k: 20, pressure_semantics: {}, result_classification: {}, filter_policy_version: "test", visibility: occurrenceVisibility() } as MatchingScientificResult;
    render(<ScientificMatches results={[result]} />);
    expect(screen.getByText(/Tc lower bound 20 K/)).toBeInTheDocument();
    expect(screen.getByText("Archive — visibility unverified")).toBeInTheDocument();
    expect(screen.getByText(/no material identity/)).toBeInTheDocument();
  });

  it.each(["active", "retracted", "corrected", "disputed", "unknown"] as const)("bibliographic %s status is separate from material acceptance", status => {
    render(<SourceVisibilityNotice visibility={sourceVisibility(status)} />);
    expect(screen.getByText(/does not approve extracted materials/)).toBeInTheDocument();
    expect(screen.queryByText("Catalogue eligible — not scientific approval")).not.toBeInTheDocument();
  });
});

describe("conditional source-scoped material visibility", () => {
  it("retains the complete detached source scope without inventing independent support", () => {
    const value = sourceScopedMaterialVisibility();
    const parsed = knownVisibility(value);
    expect(parsed).toEqual(value);
    expect(parsed).not.toBe(value);
    if (parsed?.version !== "material-visibility/2.0.0") throw new Error("Expected source-scoped visibility");
    expect(parsed.source_scope).not.toBe(value.source_scope);
    parsed.source_scope.eligible_records = 999;
    parsed.warning_codes.push("changed");
    expect(value.source_scope.eligible_records).toBe(2);
    expect(value.warning_codes).not.toContain("changed");
    expect(value.source_scope.independent_support_count).toBeNull();
  });

  it.each(["active", "unknown", "mixed", "retracted", "corrected"] as const)("does not infer source-scoped eligibility from the aggregate %s status", source_status => {
    const value = { ...sourceScopedMaterialVisibility(), source_status };
    expect(knownVisibility(value)).toEqual(value);
    expect(eligibleForScientificSeo(value)).toBe(false);
  });

  it("accepts the closed 5,000-record boundary with explicit English number formatting", () => {
    const value = sourceScopedMaterialVisibility();
    value.source_scope = { ...value.source_scope, total_records: 5000, eligible_records: 4999,
      excluded_records: 1, eligible_source_count: 4999 };
    expect(knownVisibility(value)).toEqual(value);
    render(<MaterialVisibilityNotice visibility={value} compact />);
    expect(screen.getByLabelText("material visibility")).toHaveTextContent("4,999 of 5,000 reported records eligible");
  });

  it("requires controlled messages to match their unique, sorted codes and all three mandatory warnings", () => {
    const original = sourceScopedMaterialVisibility();
    const values = [
      { ...original, warning_codes: [...original.warning_codes].reverse(), warning_messages: [...original.warning_messages].reverse() },
      { ...original, warning_codes: [...original.warning_codes, "unrecognized_claim"].sort(), warning_messages: [...original.warning_messages, "Scientific approval asserted"] },
      { ...original, warning_messages: [...original.warning_messages].reverse() },
      ...["catalogue_is_not_scientific_acceptance", "source_scoped_reported_records_only", "excluded_records_retained_in_archive"].map(removed => ({ ...original,
        warning_codes: original.warning_codes.filter(code => code !== removed),
        warning_messages: original.warning_messages.filter((_, index) => original.warning_codes[index] !== removed) })),
    ];
    for (const value of values) expect(knownVisibility(value)).toBeNull();
  });

  it.each([
    { version: "material-visibility/3.0.0" }, { state: "pending" },
    { public_catalogue_eligible: false }, { archive_available: false },
    { scientific_acceptance: true }, { scientific_acceptance: 0 },
    { reason_codes: ["source_retracted"] }, { warning_codes: [] },
    { warning_codes: ["source_scoped_reported_records_only", "source_scoped_reported_records_only"] },
    { source_status: ["active"] }, { source_status: "published" }, { source_scope: null },
    { source_scope: undefined }, { private_notes: "PRIVATE SOURCE CANARY" },
    { reason_messages: "PRIVATE SOURCE CANARY" }, { warning_messages: [false] },
    { reason_messages: ["Unexpected reason"] }, { warning_messages: ["x".repeat(2001)] }, { scope: null },
    { review_revision: "not-an-exact-revision" },
  ])("rejects invalid v2 outer fields without falling back to v1: %j", patch => {
    const value = { ...sourceScopedMaterialVisibility(), ...patch };
    expect(knownVisibility(value)).toBeNull();
    expect(eligibleForScientificSeo(value)).toBe(false);
    expect(visibilityLabel(value)).toContain("unverified");
  });

  it.each([
    { version: "material-source-scope/2.0.0" }, { status: "all_records" },
    { total_records: 4 }, { total_records: 0 }, { total_records: "3" },
    { total_records: Number.MAX_SAFE_INTEGER + 1 }, { total_records: Infinity },
    { total_records: 5001, eligible_records: 5000 },
    { eligible_records: 0 }, { eligible_records: true }, { eligible_records: 1.5 },
    { excluded_records: 0 }, { excluded_records: -1 }, { excluded_records: NaN },
    { eligible_source_count: 0 }, { eligible_source_count: 3 }, { eligible_source_count: false },
    { fingerprint: "A".repeat(64) }, { fingerprint: "a".repeat(63) },
    { fingerprint: "g".repeat(64) }, { independent_support_count: 0 },
    { independent_support_count: 1 }, { independent_support_count: false },
    { independent_support_count: undefined }, { source_ids: ["PRIVATE SOURCE ID"] },
  ])("rejects malformed source counts, hashes or authority: %j", patch => {
    const value = sourceScopedMaterialVisibility();
    const broken = { ...value, source_scope: { ...value.source_scope, ...patch } };
    expect(knownVisibility(broken)).toBeNull();
    expect(eligibleForScientificSeo(broken)).toBe(false);
  });

  it("requires every field of the closed v2 and source-scope shapes", () => {
    const value = sourceScopedMaterialVisibility();
    for (const key of Object.keys(value)) {
      const broken = { ...value } as Record<string, unknown>;
      delete broken[key];
      expect(knownVisibility(broken)).toBeNull();
    }
    for (const key of Object.keys(value.source_scope)) {
      const broken = { ...value.source_scope } as Record<string, unknown>;
      delete broken[key];
      expect(knownVisibility({ ...value, source_scope: broken })).toBeNull();
    }
  });

  it("preserves v1 source and occurrence versions rather than broadening historical validators", () => {
    const value = sourceScopedMaterialVisibility();
    expect(knownOccurrenceVisibility({ ...value, material_link_status: "resolved", reported_claim_filter_eligible: true })).toBeNull();
    expect(knownSourceVisibility({ ...sourceVisibility(), version: value.version, source_scope: value.source_scope })).toBeNull();
    expect(knownOccurrenceVisibility(occurrenceVisibility())).not.toBeNull();
    expect(knownSourceVisibility(sourceVisibility())).not.toBeNull();
    expect(knownVisibility({ ...materialVisibility(), private_extra: true })).toEqual(materialVisibility());
  });

  it.each([false, true])("always displays English source limits, including compact=%s", compact => {
    const value = sourceScopedMaterialVisibility();
    render(<MaterialVisibilityNotice visibility={value} compact={compact} />);
    const notice = screen.getByLabelText("material visibility");
    expect(notice).toHaveTextContent("Catalogue — eligible source records only");
    expect(notice).toHaveTextContent("Only eligible reported source records");
    expect(notice).toHaveTextContent("Excluded records remain in the Archive");
    expect(notice).toHaveTextContent("not scientific approval or evidence of independent replication");
    expect(notice).toHaveTextContent("2 of 3 reported records eligible; 1 excluded. Eligible sources: 1");
    expect(notice).toHaveTextContent("Independent support has not been established");
    expect(notice.textContent).not.toMatch(/[\u3400-\u9fff]/);
  });

  it("rejects substituted private prose instead of rendering or exporting it as governance", () => {
    const source = sourceScopedMaterialVisibility();
    const value = { ...source, warning_messages: source.warning_messages.map(() => "PRIVATE MESSAGE") };
    render(<MaterialVisibilityNotice visibility={value} />);
    expect(screen.queryByText(/PRIVATE/)).not.toBeInTheDocument();
    const output = archiveExport(rawArchive(), value);
    expect(output.visibility).toBeNull();
    expect(JSON.stringify(output)).not.toContain("PRIVATE");
    expect(output.scientific_acceptance).toBe(false);
  });

  it("exports validated source scope with the original authorized archive", () => {
    const value = sourceScopedMaterialVisibility();
    const output = archiveExport(rawArchive(), value);
    expect(output.visibility).toEqual(value);
    expect(output.visibility_warning).toEqual(visibilityWarning(value));
    expect(output.archive.visibility).toEqual(sourceScopedMaterialVisibility());
    expect(output.scientific_acceptance).toBe(false);
  });

  it("shows the source-range warning in an existing catalogue list row", () => {
    const row = { id: "mixed", formula: "SYNTHETIC", total_papers: 2, variant_count: 0,
      visibility: sourceScopedMaterialVisibility() } as MaterialSummary;
    render(<MaterialTable rows={[row]} />);
    expect(screen.getByText("SYNTHETIC")).toBeInTheDocument();
    expect(screen.getByText(/Only eligible reported source records/)).toBeInTheDocument();
    expect(screen.queryByText("Catalogue eligible — not scientific approval")).not.toBeInTheDocument();
  });
});
