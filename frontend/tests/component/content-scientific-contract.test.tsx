import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { ScientificQueryNotice } from "@/components/ScientificQueryNotice";
import { knownScientificLookup, knownScientificQuery, knownScientificResults } from "@/lib/scientific-query";
import { knownScientificMixedResponse } from "@/lib/scientific-mixed";
import { knownAnswerReceipt } from "@/lib/answer-history";
import { historyDetailFixture } from "../fixtures/answer-history";
import searchWire from "../fixtures/content-scientific-search-wire.json";
import mixedWire from "../fixtures/content-scientific-mixed-wire.json";

afterEach(cleanup);
const clone = () => structuredClone(searchWire);
function parsed(body: typeof searchWire) {
  const query = knownScientificQuery(body.scientific_query, body.scientific_query.raw_query);
  const lookup = knownScientificLookup(body.scientific_lookup);
  return query && lookup ? knownScientificResults(body.scientific_results, lookup, body.retrieval_generation, query) : null;
}

describe("explicit content scientific wire, synthetic structural fixtures only", () => {
  it("renders the content, actual native origin and unchanged unreviewed quantities in English", () => {
    expect(parsed(searchWire)).toHaveLength(1);
    render(<ScientificQueryNotice query={searchWire.scientific_query} lookup={searchWire.scientific_lookup}
      results={searchWire.scientific_results} generation={searchWire.retrieval_generation} rawQuery={searchWire.scientific_query.raw_query} />);
    expect(screen.getByText("Content / backend build / activation:")).toBeInTheDocument();
    expect(screen.getByText("Native revision:")).toBeInTheDocument();
    expect(screen.queryByText("Generation / activation:")).not.toBeInTheDocument();
    expect(screen.getByText(/not an original quotation, independent confirmation/)).toBeInTheDocument();
  });

  it("retains a legacy origin inside a distinct content/backend identity", () => {
    const body = clone(), binding = body.scientific_results[0].binding;
    binding.origin_kind = "legacy_v1";
    binding.origin_generation_id = body.retrieval_generation.content_id as never;
    binding.native_revision_id = null as never;
    binding.vector_id = `ig62_${String(binding.origin_generation_id).replaceAll("-", "")}_${binding.chunk_revision_sha256}`;
    expect(parsed(body)).toHaveLength(1);
    render(<ScientificQueryNotice query={body.scientific_query} lookup={body.scientific_lookup} results={body.scientific_results}
      generation={body.retrieval_generation} rawQuery={body.scientific_query.raw_query} />);
    expect(screen.getByText("Retained origin generation:")).toBeInTheDocument();
  });

  it.each(["content_id", "build_id", "activation_event_id", "manifest_sha256", "policy_artifact_sha256"])("rejects a different %s", key => {
    const body = clone();
    (body.scientific_results[0].binding as Record<string, unknown>)[key] = key.endsWith("sha256") ? "0".repeat(64) : "00000000-0000-0000-0000-000000000000";
    expect(parsed(body)).toBeNull();
  });

  it.each([
    { generation_id: searchWire.retrieval_generation.content_id }, { native_revision_id: null },
    { origin_generation_id: searchWire.retrieval_generation.content_id }, { vector_id: `rv2_${"0".repeat(64)}` },
    { scientific_acceptance: true }, { version: "scientific-result-binding/1.0.0" },
    { content_member_record_sha256: "A".repeat(64) },
  ])("rejects mixed or false origin fields %j", change => {
    const body = clone();Object.assign(body.scientific_results[0].binding, change);
    expect(parsed(body)).toBeNull();
  });

  it.each(["version", "origin_generation_id", "native_revision_id", "origin_record_sha256"])("requires explicit %s", key => {
    const body = clone();delete (body.scientific_results[0].binding as Record<string, unknown>)[key];
    expect(parsed(body)).toBeNull();
  });

  it("rejects the generation scope and a same-dimension foreign embedding profile", () => {
    const body = clone();body.scientific_lookup.scope = "declared_generation_derived_extractions";
    expect(parsed(body)).toBeNull();
    const other = clone();other.retrieval_generation.profile.model = "other-768-model";
    expect(parsed(other)).toBeNull();
  });

  it("validates explicit v2 mixed inventories without granting causal or scientific authority", () => {
    expect(knownScientificMixedResponse(mixedWire, mixedWire.scientific_query.raw_query)).toEqual(mixedWire.scientific_mixed);
    for (const change of ["old_version", "changed_source", "restricted", "synthesis", "acceptance"]) {
      const body = structuredClone(mixedWire);
      if (change === "old_version") body.scientific_mixed.version = "scientific-mixed-evidence/1.1.0";
      else if (change === "changed_source") body.scientific_mixed.associations[0].source_vector_id = `rv2_${"0".repeat(64)}`;
      else if (change === "restricted") body.sources[0].evidence_provenance.permission_status = "restricted";
      else if (change === "synthesis") body.answer_mode = "synthesis";
      else body.scientific_mixed.scientific_acceptance = true;
      expect(knownScientificMixedResponse(body, body.scientific_query.raw_query)).toBeNull();
    }
  });

  it("keeps the v1 historical decoder closed to new live response scopes", () => {
    const receipt = historyDetailFixture().evidence.receipt!;
    expect(knownAnswerReceipt(receipt)).not.toBeNull();
    for (const change of ["scope", "read", "mixed"]) {
      const body = structuredClone(receipt);
      if (change === "scope") body.response.scientific_lookup!.scope = "declared_content_derived_extractions";
      else if (change === "read") body.response.retrieval_generation = searchWire.retrieval_generation as never;
      else body.response.scientific_mixed!.version = "scientific-mixed-evidence/2.0.0";
      expect(knownAnswerReceipt(body)).toBeNull();
    }
  });
});
