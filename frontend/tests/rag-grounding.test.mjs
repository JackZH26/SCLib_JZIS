import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("search separates scientific excerpt checks from mechanical citation validation", async () => {
  const api = await readFile("lib/api.ts", "utf8");
  const search = await readFile("app/search/page.tsx", "utf8");

  assert.match(api, /citation_valid:\s*boolean/);
  assert.match(api, /citation_warnings:\s*string\[\]/);
  const notice = await readFile("components/AskSupportNotice.tsx", "utf8");
  assert.match(search, /<AskSupportNotice response=\{askData\}/);
  assert.doesNotMatch(search, /!askData\.citation_valid/);
  assert.match(api, /scientific_support_status\?: AskScientificSupportStatus/);
  assert.match(notice, /Valid source references alone do not demonstrate support/);
  assert.match(notice, /generated draft, not a verification of any delivered fallback/);
  assert.match(search, /resolveAskSource/);
  assert.match(search, /askData\.sources\.map/);
});

test("public API documentation describes hybrid retrieval and citation fields", async () => {
  const docs = await readFile("app/docs/api/page.tsx", "utf8");

  assert.match(docs, /citation_valid/);
  assert.match(docs, /citation_warnings/);
  assert.match(docs, /scientific_support_status/);
  assert.match(docs, /assessment_scope=generated_draft/);
  assert.match(docs, /deprecated and mechanical/);
  assert.match(docs, /PostgreSQL full-text/);
});
