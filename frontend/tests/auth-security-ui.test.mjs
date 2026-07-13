import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("password reset UI uses generic request copy and a one-time token", async () => {
  const api = await readFile("lib/api.ts", "utf8");
  const forgot = await readFile("app/forgot-password/page.tsx", "utf8");
  const reset = await readFile("app/reset-password/page.tsx", "utf8");

  assert.match(api, /auth\/password-reset\/request/);
  assert.match(api, /auth\/password-reset\/confirm/);
  assert.match(forgot, /whether or not an account exists/i);
  assert.match(reset, /useSearchParams\(\)\.get\(["']token["']\)/);
  assert.doesNotMatch(reset, /localStorage|sessionStorage/);
});

test("dashboard exposes server-side session revocation separately from API keys", async () => {
  const api = await readFile("lib/api.ts", "utf8");
  const security = await readFile(
    "components/dashboard/SessionSecurityCard.tsx",
    "utf8",
  );

  assert.match(api, /auth\/sessions\/revoke-all/);
  assert.match(security, /API keys are managed separately/);
  assert.match(security, /notifyAuthChange\(\)/);
});
