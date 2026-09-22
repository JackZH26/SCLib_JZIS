import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("classification filter UI explicitly separates source reports, qualified false and same-state data", async () => {
  const page = await readFile("app/materials/page.tsx", "utf8");
  assert.match(page, /Reported true/);
  assert.match(page, /Qualified reported false/);
  assert.match(page, /not a joint Tc\/state result/);
  assert.match(page, /family priors/);
});

test("public API documents material summary classification scope and nonindependent count basis", async () => {
  const docs = await readFile("app/docs/api/page.tsx", "utf8");
  for (const term of ["material_reported_summary_not_joint_state", "has_competing_order", "material-semantics/1.0.0", "support.count_basis", "support.legacy_total_papers", "parent rollups", "independent works or replications"]) assert.ok(docs.includes(term), term);
  assert.match(docs, /Unknown or missing values never mean false/);
});
