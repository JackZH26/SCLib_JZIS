import assert from "node:assert/strict";
import { readFileSync, readdirSync, realpathSync, rmSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const require = createRequire(import.meta.url);
const { childEnvironment, createWorkspace } = require("./e2e/public-site-server.cjs");
const config = readFileSync(new URL("../playwright.config.ts", import.meta.url), "utf8");
const server = readFileSync(new URL("./e2e/public-site-server.cjs", import.meta.url), "utf8");

test("standalone trace destinations contain both copied source and real linked dependencies", async () => {
  const original = realpathSync(fileURLToPath(new URL("../", import.meta.url)));
  const originalBytes = readFileSync(path.join(original, "next.config.js"));
  const isolated = createWorkspace(original);
  try {
    const copied = require(path.join(isolated, "next.config.js"));
    const production = require(path.join(original, "next.config.js"));
    assert.equal(copied.output, "standalone");
    assert.equal(copied.basePath, production.basePath);
    assert.deepEqual(await copied.headers(), await production.headers());
    const output = path.join(isolated, ".next/standalone");
    for (const traced of [path.join(isolated, "package.json"),
      realpathSync(path.join(isolated, "node_modules/next/package.json"))]) {
      const destination = path.resolve(output, path.relative(copied.outputFileTracingRoot, traced));
      assert.ok(destination.startsWith(output + path.sep), destination);
    }
    assert.deepEqual(readFileSync(path.join(original, "next.config.js")), originalBytes);
    assert.notEqual(path.join(isolated, ".next"), path.join(original, ".next"));
  } finally {
    rmSync(isolated, { recursive: true });
  }
});

test("production browser child excludes inherited credentials, env files and font mocks", () => {
  const env = childEnvironment({ PATH: "/synthetic/bin", DATABASE_URL: "do-not-inherit",
    API_BASE_SERVER: "https://do-not-inherit.invalid", NEXT_PUBLIC_GA_ID: "do-not-inherit",
    NEXT_FONT_GOOGLE_MOCKED_RESPONSES: "/do-not-inherit", NODE_OPTIONS: "do-not-inherit" });
  assert.equal(env.PATH, "/synthetic/bin");
  assert.equal(env.NODE_ENV, "production");
  assert.equal(env.API_BASE_SERVER, "http://127.0.0.1:1/inert/v1");
  assert.equal(env.NEXT_PUBLIC_API_BASE, "https://api.jzis.org/sclib/v1");
  assert.equal(env.NEXT_PUBLIC_BASE_PATH, "/sclib");
  for (const key of ["DATABASE_URL", "NEXT_PUBLIC_GA_ID", "NODE_OPTIONS", "NEXT_FONT_GOOGLE_MOCKED_RESPONSES"]) {
    assert.equal(env[key], undefined);
  }
  assert.doesNotMatch(server, /cpSync\([^\n]*\.env|rmSync|pnpm install/);
  assert.match(server, /mkdtempSync/);
  assert.match(server, /symlinkSync/);
  assert.ok(server.includes('"types"'), "The real Plotly declarations must reach the production build");
  assert.match(server, /run\(\["build"\]/);
});

test("public production E2E never reuses a server or permits service worker bypass", () => {
  assert.match(config, /public-site-server\.cjs/);
  assert.match(config, /reuseExistingServer: false/);
  assert.match(config, /serviceWorkers: "block"/);
  assert.match(config, /outputFile: "playwright-results.json"/);
  assert.doesNotMatch(config, /API_BASE_SERVER: "https:/);
});

test("every public browser suite installs the fail-closed network fixture", () => {
  const suites = readdirSync(new URL("./e2e/", import.meta.url)).filter(name => name.endsWith(".spec.ts"));
  assert.ok(suites.length >= 4);
  for (const name of suites) {
    const source = readFileSync(new URL(`./e2e/${name}`, import.meta.url), "utf8");
    assert.match(source, /from "\.\/public-site-fixture"/, name);
    assert.doesNotMatch(source, /from "@playwright\/test"/, name);
  }
  const fixture = readFileSync(new URL("./e2e/public-site-fixture.ts", import.meta.url), "utf8");
  assert.match(fixture, /route\.abort\("blockedbyclient"\)/);
  assert.ok(fixture.includes('url.href === "https://api.jzis.org/sclib/v1/auth/me"'));
  assert.ok(fixture.includes('route.request().method() === "GET"'));
  assert.ok(fixture.includes('route.fulfill({ status: 401'));
  assert.match(fixture, /context\.routeWebSocket/);
  assert.doesNotMatch(fixture, /connectToServer|route\.fetch/);
  assert.match(fixture, /auto: true/);
});
