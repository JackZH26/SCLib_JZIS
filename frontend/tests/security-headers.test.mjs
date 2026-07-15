import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";

process.env.NODE_ENV = "production";
const require = createRequire(import.meta.url);
const nextConfig = require("../next.config.js");

test("all frontend routes receive the required security headers", async () => {
  const rules = await nextConfig.headers();
  assert.ok(rules.length > 1);
  const securityRule = rules.find(({ source }) => source === "/:path*");
  assert.ok(securityRule);

  const headers = Object.fromEntries(
    securityRule.headers.map(({ key, value }) => [key.toLowerCase(), value]),
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
  const securityRule = rules.find(({ source }) => source === "/:path*");
  const csp = securityRule?.headers.find(
    ({ key }) => key === "Content-Security-Policy",
  )?.value;

  assert.ok(csp);
  assert.match(csp, /default-src 'self'/);
  assert.match(csp, /object-src 'none'/);
  assert.match(csp, /frame-ancestors 'none'/);
  assert.match(csp, /base-uri 'self'/);
  assert.ok(csp.includes("https://api.jzis.org"));
  assert.ok(csp.includes("https://www.googletagmanager.com"));
  assert.doesNotMatch(csp, /'unsafe-eval'/);
  assert.doesNotMatch(csp, /localhost|127\.0\.0\.1/);
});

test("private and authentication routes instruct crawlers not to index", async () => {
  const rules = await nextConfig.headers();
  for (const path of [
    "/auth/:path*",
    "/dashboard/:path*",
    "/forgot-password",
    "/login",
    "/register",
    "/reset-password",
    "/verify",
  ]) {
    const rule = rules.find(({ source }) => source === path);
    assert.ok(rule, `missing noindex rule for ${path}`);
    assert.deepEqual(rule.headers, [
      { key: "X-Robots-Tag", value: "noindex, nofollow" },
    ]);
  }
});
