import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";

async function sourceFiles(dir) {
  const entries = await readdir(dir, { withFileTypes: true });
  const nested = await Promise.all(entries.map(async (entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return sourceFiles(full);
    return /\.(?:ts|tsx)$/.test(entry.name) ? [full] : [];
  }));
  return nested.flat();
}

test("browser auth uses credentialed HttpOnly-cookie requests", async () => {
  const apiClient = await readFile("lib/api.ts", "utf8");
  const callback = await readFile("app/auth/callback/page.tsx", "utf8");
  const backendAuth = await readFile("../api/routers/auth.py", "utf8");

  assert.match(apiClient, /credentials:\s*init\.credentials\s*\?\?\s*["']include["']/);
  assert.match(apiClient, /["']\/auth\/session\/login["']/);
  assert.doesNotMatch(apiClient, /authorization["']?,\s*`Bearer/);
  assert.match(callback, /\bme\(\)/);
  assert.doesNotMatch(callback, /params\.get\(["']token["']\)/);
  assert.doesNotMatch(backendAuth, /frontend_callback_url[^\n]*\?token=/);
});

test("application source contains no browser-stored JWT fallback", async () => {
  const files = [
    ...(await sourceFiles("app")),
    ...(await sourceFiles("components")),
    ...(await sourceFiles("lib")),
  ];
  const source = (await Promise.all(files.map((file) => readFile(file, "utf8")))).join("\n");

  assert.doesNotMatch(source, /sclib_jwt|sclib_token|auth-storage/);
  assert.doesNotMatch(
    source,
    /localStorage\.(?:getItem|setItem|removeItem)\([^\n]*(?:jwt|token)/i,
  );
});
