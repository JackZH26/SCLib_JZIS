import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const chart = readFileSync(
  new URL("../components/TcTimeline.tsx", import.meta.url),
  "utf8",
);
const page = readFileSync(
  new URL("../app/timeline/page.tsx", import.meta.url),
  "utf8",
);
const plotlyBundle = readFileSync(
  new URL("../components/PlotlyGl2d.tsx", import.meta.url),
  "utf8",
);
const api = readFileSync(new URL("../lib/api.ts", import.meta.url), "utf8");

test("timeline uses WebGL traces and memoizes its point transformation", () => {
  assert.match(chart, /type:\s*["']scattergl["']/);
  assert.match(chart, /useMemo\(\(\)\s*=>/);
  assert.match(chart, /new Map<string, TimelinePoint\[\]>/);
  assert.match(chart, /import\(["']@\/components\/PlotlyGl2d["']\)/);
  assert.match(plotlyBundle, /plotly\.js\/dist\/plotly-gl2d\.min\.js/);
  assert.doesNotMatch(chart, /import\(["']react-plotly\.js["']\)/);
});

test("timeline page requests a bounded compact payload", () => {
  assert.match(page, /maxPoints:\s*10000/);
  assert.match(page, /compact:\s*true/);
  assert.match(api, /next:\s*\{\s*revalidate:\s*60\s*\}/);
  assert.match(api, /cache:\s*["']force-cache["']/);
  assert.match(api, /schema_version: opts\.schemaVersion \?\? "1"/);
  assert.match(api, /if \(opts\.offset != null\)/);
  assert.match(api, /if \(opts\.limit != null\)/);
});
