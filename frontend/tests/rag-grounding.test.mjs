import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("search surfaces citation validation without hiding the source links", async () => {
  const api = await readFile("lib/api.ts", "utf8");
  const search = await readFile("app/search/page.tsx", "utf8");

  assert.match(api, /citation_valid:\s*boolean/);
  assert.match(api, /citation_warnings:\s*string\[\]/);
  assert.match(search, /!askData\.citation_valid/);
  assert.match(search, /Verify each claim/);
  assert.match(search, /askData\.sources\.map/);
});

test("public API documentation describes hybrid retrieval and citation fields", async () => {
  const docs = await readFile("app/docs/api/page.tsx", "utf8");

  assert.match(docs, /citation_valid/);
  assert.match(docs, /citation_warnings/);
  assert.match(docs, /PostgreSQL full-text/);
});
