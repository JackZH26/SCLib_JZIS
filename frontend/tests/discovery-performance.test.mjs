import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const api = readFileSync(new URL("../lib/api.ts", import.meta.url), "utf8");
const page = readFileSync(new URL("../app/discovery/page.tsx", import.meta.url), "utf8");
const feed = readFileSync(new URL("../components/DiscoveryFeed.tsx", import.meta.url), "utf8");

test("discovery server render uses bounded summary pages", () => {
  assert.match(page, /const PAGE_SIZE = 24/);
  assert.match(page, /getDiscoveryMetadata\(\)/);
  assert.match(page, /getDiscoveryCandidates\(\{ limit: PAGE_SIZE, dataVersion: metadata\.data_version \}\)/);
  assert.match(page, /verifyDiscoveryPage\(page, metadata\.data_version/);
  assert.doesNotMatch(page, /getDiscovery\(\)/);
  assert.match(api, /\/discovery\/candidates\?\$\{qs\}/);
  assert.match(api, /schema_version: "1"/);
  assert.match(api, /next:\s*\{ revalidate: 60 \}/);
});

test("discovery cards virtualize offscreen work and lazy-load dossiers", () => {
  assert.match(feed, /\[content-visibility:auto\]/);
  assert.match(feed, /data-virtualized="true"/);
  assert.match(feed, /if \(event\.currentTarget\.open\) void loadDetail\(\)/);
  assert.match(feed, /getDiscoveryCandidate\(candidate\.candidate_id, dataVersion\)/);
  assert.match(feed, /verifyDiscoveryDetail\(result, dataVersion, candidate\.candidate_id\)/);
  assert.match(feed, /Load \$\{Math\.min\(PAGE_SIZE, total - items\.length\)\} more/);
});

test("legacy feed rejects mixed-version pages and uses explicit English recovery copy", () => {
  assert.match(feed, /verifyDiscoveryPage\(page, dataVersion, items\.length, items, selectedRole, total\)/);
  assert.match(feed, /mixed-version records have been cleared/);
  assert.match(feed, /Reload latest feed/);
  assert.match(feed, /not evidence of an experimental negative outcome/);
  assert.match(api, /data_version: opts\.dataVersion/);
});
