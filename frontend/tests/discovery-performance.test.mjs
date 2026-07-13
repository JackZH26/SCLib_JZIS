import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const api = readFileSync(new URL("../lib/api.ts", import.meta.url), "utf8");
const page = readFileSync(new URL("../app/discovery/page.tsx", import.meta.url), "utf8");
const feed = readFileSync(new URL("../components/DiscoveryFeed.tsx", import.meta.url), "utf8");

test("discovery server render uses bounded summary pages", () => {
  assert.match(page, /const PAGE_SIZE = 24/);
  assert.match(page, /getDiscoveryMetadata\(\)/);
  assert.match(page, /getDiscoveryCandidates\(\{ limit: PAGE_SIZE \}\)/);
  assert.match(api, /\/discovery\/candidates\?\$\{qs\}/);
  assert.match(api, /schema_version: "1"/);
  assert.match(api, /next:\s*\{ revalidate: 60 \}/);
});

test("discovery cards virtualize offscreen work and lazy-load dossiers", () => {
  assert.match(feed, /\[content-visibility:auto\]/);
  assert.match(feed, /data-virtualized="true"/);
  assert.match(feed, /if \(event\.currentTarget\.open\) void loadDetail\(\)/);
  assert.match(feed, /getDiscoveryCandidate\(candidate\.candidate_id\)/);
  assert.match(feed, /Load \$\{Math\.min\(PAGE_SIZE, total - items\.length\)\} more/);
});
