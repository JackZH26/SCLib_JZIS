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
const plotlyFallbackBundle = readFileSync(
  new URL("../components/PlotlyBasic2d.tsx", import.meta.url),
  "utf8",
);
const families = readFileSync(
  new URL("../lib/families.ts", import.meta.url),
  "utf8",
);
const api = readFileSync(new URL("../lib/api.ts", import.meta.url), "utf8");
const display = readFileSync(new URL("../lib/timeline-display.ts", import.meta.url), "utf8");

test("timeline prefers WebGL and falls back to a bounded SVG renderer", () => {
  assert.match(chart, /type:\s*renderer === ["']webgl["']/);
  assert.match(chart, /["']scattergl["'] as const/);
  assert.match(chart, /["']scatter["'] as const/);
  assert.match(chart, /useMemo\(\(\)\s*=>/);
  assert.match(display, /new Map<string, TimelinePoint\[\]>/);
  assert.match(chart, /timelineRenderBudget/);
  assert.match(chart, /All .*received results remain accessible in the table/);
  assert.doesNotMatch(chart, /index % Math.ceil/);
  assert.doesNotMatch(chart, /jitterYear/);
  assert.match(chart, /import\(["']@\/components\/PlotlyGl2d["']\)/);
  assert.match(chart, /import\(["']@\/components\/PlotlyBasic2d["']\)/);
  assert.match(chart, /browserSupportsWebGL/);
  assert.match(chart, /getContext\(["']webgl["'], attributes\)/);
  assert.doesNotMatch(chart, /getContext\(["']webgl2["']/);
  assert.match(chart, /querySelector\(["']\.no-webgl["']\)/);
  assert.match(chart, /onWebGlContextLost/);
  assert.match(chart, /SVG_POINT_LIMIT\s*=\s*3000/);
  assert.match(plotlyBundle, /plotly\.js\/dist\/plotly-gl2d\.min\.js/);
  assert.match(plotlyFallbackBundle, /plotly\.js\/dist\/plotly-basic\.min\.js/);
  assert.doesNotMatch(chart, /import\(["']react-plotly\.js["']\)/);
});

test("timeline names reported results and keeps unsampled summaries separate", () => {
  assert.match(page, /Reported Tc Timeline/);
  assert.match(page, /Observed only/);
  assert.match(page, /Reviewed-only mode is unavailable/);
  assert.doesNotMatch(page, /Displaying a representative sample|Only experimental|Superconductivity discovery timeline/);
  assert.match(chart, /full_filtered_unsampled/);
  assert.match(chart, /not inferred from the display sample/);
  assert.match(chart, /escapePlotlyHtml/);
  assert.match(chart, /scope="col"/);
});

test("all material-family navigation uses an English elemental label", () => {
  assert.match(families, /slug:\s*["']elemental["'],\s*label:\s*["']Elemental["']/);
  assert.doesNotMatch(families, /元素超导体/);
});

test("timeline page requests a bounded compact payload", () => {
  assert.match(page, /maxPoints:\s*expanded\s*\?\s*10000\s*:\s*2000/);
  assert.match(page, /compact:\s*true/);
  const timelineFetch = api.slice(api.indexOf("export function getTimeline("), api.indexOf("export interface DiscoveryFilterRule"));
  assert.match(timelineFetch, /cache:\s*["']no-store["']/);
  assert.doesNotMatch(timelineFetch, /force-cache|revalidate/);
  assert.match(api, /schema_version: opts\.schemaVersion \?\? "1"/);
  assert.match(api, /if \(opts\.offset != null\)/);
  assert.match(api, /if \(opts\.limit != null\)/);
});
