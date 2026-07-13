import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("API client preserves request correlation and unified quota fields", async () => {
  const api = await readFile("lib/api.ts", "utf8");

  assert.match(api, /public requestId\?: string/);
  assert.match(api, /res\.headers\.get\("x-request-id"\)/);
  assert.match(api, /interface SearchResponse[\s\S]*remaining: number \| null/);
  assert.match(api, /interface AskResponse[\s\S]*remaining: number \| null/);
});
