import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";

process.env.NODE_ENV = "production";
const require = createRequire(import.meta.url);
const nextConfig = require("../next.config.js");

test("all frontend routes receive the required security headers", async () => {
  const rules = await nextConfig.headers();
  assert.equal(rules.length, 1);
  assert.equal(rules[0].source, "/:path*");

  const headers = Object.fromEntries(
    rules[0].headers.map(({ key, value }) => [key.toLowerCase(), value]),
  );

  assert.match(headers["strict-transport-security"], /max-age=63072000/);
  assert.equal(headers["x-content-type-options"], "nosniff");
  assert.equal(headers["x-frame-options"], "DENY");
  assert.equal(headers["referrer-policy"], "strict-origin-when-cross-origin");
  assert.match(headers["permissions-policy"], /camera=\(\)/);
  assert.match(headers["permissions-policy"], /microphone=\(\)/);
  assert.match(headers["permissions-policy"], /geolocation=\(\)/);
});

test("production CSP is restrictive and permits required integrations", async () => {
  const rules = await nextConfig.headers();
  const csp = rules[0].headers.find(
    ({ key }) => key === "Content-Security-Policy",
  )?.value;

  assert.ok(csp);
  assert.match(csp, /default-src 'self'/);
  assert.match(csp, /object-src 'none'/);
  assert.match(csp, /frame-ancestors 'none'/);
  assert.match(csp, /base-uri 'self'/);
  assert.match(csp, /https:\/\/api\.jzis\.org/);
  assert.match(csp, /https:\/\/www\.googletagmanager\.com/);
  assert.doesNotMatch(csp, /'unsafe-eval'/);
  assert.doesNotMatch(csp, /localhost|127\.0\.0\.1/);
});
