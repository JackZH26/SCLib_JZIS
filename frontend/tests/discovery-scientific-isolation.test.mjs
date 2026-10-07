import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = path => readFileSync(new URL(`../${path}`, import.meta.url), "utf8");
test("unscored source hypotheses lead, with separate formal scores, coordinate proposals and research tools", () => {
  const page = read("app/discovery/page.tsx");
  assert.match(page, /<DiscoveryTabs candidates=\{/);
  const researchSlot = page.indexOf("research={");
  assert.ok(page.indexOf("<DiscoverySourceCandidates catalogue={sourceCatalogue} />") < researchSlot);
  for (const content of ["<ResearchCandidateBoard />", "<ResearchProposals catalog={researchCatalogue}", 'id="discovery-formal-assessments"', 'id="discovery-coordinate-proposals"', "<ScientificDiscoveryMatrix folded />", 'id="discovery-tools"', 'id="discovery-source-studies"', 'id="discovery-methodology"', "<LegacyDiscovery />"]) {
    assert.ok(page.indexOf(content) > researchSlot, `${content} belongs to the research tab`);
  }
  assert.ok(page.indexOf("<DiscoverySourceCandidates catalogue={sourceCatalogue} />") < page.indexOf("<ScientificDiscoveryMatrix folded />"));
  assert.match(read("components/ScientificDiscoveryMatrix.tsx"), /id="discovery-scientific-companions" summary="Scientific property companions"/);
  assert.doesNotMatch(page, /<ResearchPriorityBoard \/>/);
  assert.match(page, /<LegacyDiscovery \/>/);
  assert.match(page, /process\.env\.NODE_ENV === "development" && \(await searchParams\)\.preview === "layout"/);
});
test("the public matrix never imports fixture/demo data, admin mutations, draft units or a browser scorer", () => {
  for (const path of ["components/DiscoverySourceCandidates.tsx", "components/ResearchCandidateBoard.tsx", "components/ScientificDiscoveryMatrix.tsx", "lib/discovery-scientific.ts"]) {
    const source = read(path);
    assert.doesNotMatch(source, /from ["'][^"']*(?:fixture|discovery-layout-demo|discovery-field-registry|scientific-imports|distribution-rights)/);
    assert.doesNotMatch(source, /DISCOVERY_DEMO_ROWS|localStorage|sessionStorage|dangerouslySetInnerHTML|method: ["'](?:POST|PUT|PATCH|DELETE)/);
    assert.doesNotMatch(source, /[\u3400-\u9fff]/);
  }
  const client = read("lib/discovery-scientific.ts");
  assert.match(client, /credentials: "omit", cache: "no-store", redirect: "error"/);
  assert.match(client, /crypto\.subtle\.digest\("SHA-256", bytes\)/);
  assert.doesNotMatch(client, /JSON\.stringify\(/);
});
test("the planned dictionary explains that native units are independently authoritative", () => {
  const guide = read("components/DiscoveryFieldGuide.tsx");
  assert.match(guide, /native DOS is dos_at_fermi \(states\/eV\/formula_unit\)/);
  assert.match(guide, /native superfluid_stiffness is in K/);
});
