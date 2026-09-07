import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MaterialVisibilityNotice, SourceVisibilityNotice } from "@/components/MaterialVisibilityNotice";
import { RawScientificArchive } from "@/components/ScientificAnomalies";
import { MaterialTable } from "@/components/MaterialTable";
import { ScientificMatches } from "@/components/ScientificMatches";
import { archiveExport, eligibleForScientificSeo, knownOccurrenceVisibility, knownVisibility, visibilityLabel } from "@/lib/material-visibility";
import type { MaterialSummary, MatchingScientificResult } from "@/lib/api";
import { materialVisibility, occurrenceVisibility, sourceVisibility } from "../fixtures/material-visibility";
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
