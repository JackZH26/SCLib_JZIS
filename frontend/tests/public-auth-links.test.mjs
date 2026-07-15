import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const files = {
  api: readFileSync(new URL("../lib/api.ts", import.meta.url), "utf8"),
  login: readFileSync(new URL("../app/login/page.tsx", import.meta.url), "utf8"),
  register: readFileSync(
    new URL("../app/register/page.tsx", import.meta.url),
    "utf8",
  ),
};

test("OAuth links use the public API origin during server rendering", () => {
  assert.match(files.api, /export const PUBLIC_API_BASE\s*=/);
  assert.ok(files.api.includes("https://api.jzis.org/sclib/v1"));

  for (const [page, source] of Object.entries({
    login: files.login,
    register: files.register,
  })) {
    assert.match(
      source,
      /`\$\{PUBLIC_API_BASE\}\/auth\/google\/login`/,
      `${page} must build its OAuth link from PUBLIC_API_BASE`,
    );
    assert.doesNotMatch(
      source,
      /`\$\{API_BASE\}\/auth\/google\/login`/,
      `${page} must not use the SSR-aware API_BASE for browser navigation`,
    );
  }
});

test("OAuth navigation sources contain no internal or loopback host", () => {
  const oauthSources = `${files.login}\n${files.register}`;
  assert.doesNotMatch(oauthSources, /(?:api:8000|localhost|127\.0\.0\.1)/);
});
