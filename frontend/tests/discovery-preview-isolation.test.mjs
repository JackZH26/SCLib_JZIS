import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("synthetic material preview requires an explicit query and development mode", () => {
  const source = readFileSync(new URL("../app/discovery/page.tsx", import.meta.url), "utf8");
  assert.match(source, /process\.env\.NODE_ENV === "development" && \(await searchParams\)\.preview === "layout"/);
  assert.match(source, /await import\("@\/components\/DiscoveryLayoutPreview"\)/);
});

test("demo rows never enter the live RPS board or call the real detail API", () => {
  const board = readFileSync(new URL("../components/ResearchPriorityBoard.tsx", import.meta.url), "utf8");
  const preview = readFileSync(new URL("../components/DiscoveryLayoutPreview.tsx", import.meta.url), "utf8");
  assert.doesNotMatch(board, /DISCOVERY_DEMO_ROWS|discovery-layout-demo/);
  assert.doesNotMatch(preview, /getRpsDetail|getRpsPage|fetch\(/);
  const guide = readFileSync(new URL("../components/DiscoveryFieldGuide.tsx", import.meta.url), "utf8");
  assert.doesNotMatch(guide, /DISCOVERY_DEMO_ROWS|discovery-layout-demo/);
});
