import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";

const config = readFileSync(new URL("./e2e/research-workbenches.config.ts", import.meta.url), "utf8");
const workflow = readFileSync(new URL("../../.github/workflows/test.yml", import.meta.url), "utf8");
const require = createRequire(import.meta.url);
const { prepareOutput } = require("./e2e/run-research-workbenches.cjs");
const launcher = readFileSync(new URL("./e2e/run-research-workbenches.cjs", import.meta.url), "utf8");

test("private browser CI collects all visual TypeScript suites, without replacing public E2E", () => {
  assert.match(config, /testMatch: "\*\.visual\.ts"/);
  const suites = readdirSync(new URL("./e2e/", import.meta.url)).filter(name => name.endsWith(".visual.ts"));
  for (const name of ["ml-pilot-reviews", "ml-pilot-participation", "ml-use-rights", "ml-use-runs",
    "scientific-review", "scientific-imports", "source-task-operations", "answer-history", "distribution-rights"]) {
    assert.ok(suites.includes(`${name}.visual.ts`), name);
  }
  const job = workflow.split("\n  frontend-e2e:")[1].split("\n  operations-config:")[0];
  assert.ok(job.includes("run: pnpm test:e2e"));
  assert.ok(job.includes("run: node tests/e2e/run-research-workbenches.cjs"));
  assert.ok(job.includes("research-browser-attempt-${{ github.run_attempt }}"));
  const artifact = job.split("- name: Upload private research browser evidence")[1].split("- name:")[0];
  assert.ok(artifact.includes("if-no-files-found: error"));
});

test("private browser CI never reuses a server and keeps each output root exclusive", () => {
  assert.match(config, /127\.0\.0\.1/);
  assert.match(config, /reuseExistingServer: false/);
  assert.match(config, /serviceWorkers: "block"/);
  assert.match(config, /forbidOnly: Boolean\(process\.env\.CI\)/);
  assert.match(config, /workers: 1/);
  assert.match(config, /retries: 0/);
  assert.match(config, /path\.isAbsolute\(artifacts\)/);
  assert.match(config, /lstatSync\(artifacts\)\.isSymbolicLink\(\)/);
  assert.doesNotMatch(config, /reuseExistingServer: true|rmSync|mkdirSync|mkdtempSync/);
  assert.match(launcher, /mkdirSync\(requested, \{ mode: 0o700 \}\)/);
  assert.ok(config.includes('outputFile: path.join(artifacts, "results.json")'));
});

test("output preparation runs once in the launcher and cannot replace any earlier artifact", () => {
  const parent = mkdtempSync(path.join(tmpdir(), "sclib-browser-output-test-"));
  try {
    const fresh = path.join(parent, "fresh");
    assert.equal(prepareOutput(fresh), fresh);
    writeFileSync(path.join(fresh, "retained.txt"), "preserve prior evidence");
    assert.throws(() => prepareOutput(fresh), /EEXIST/);
    assert.throws(() => prepareOutput("relative"), /absolute new directory/);
    const target = path.join(parent, "target"), link = path.join(parent, "link");
    mkdirSync(target); symlinkSync(target, link, "dir");
    assert.throws(() => prepareOutput(link), /EEXIST/);
    assert.equal(readFileSync(path.join(fresh, "retained.txt"), "utf8"), "preserve prior evidence");
  } finally {
    rmSync(parent, { recursive: true }); // Only this test's freshly created directory.
  }
});

test("the shared research browser server keeps source intake synthetic and copies no env file", () => {
  const server = readFileSync(new URL("./e2e/scientific-review-server.cjs", import.meta.url), "utf8");
  assert.ok(server.includes("/__synthetic_api/v1"));
  assert.ok(server.includes('API_BASE_SERVER: "http://127.0.0.1:1/inert/v1"'));
  assert.ok(server.includes('NEXT_PUBLIC_BASE_PATH: ""'));
  assert.ok(server.includes("scientific-review-offline-fonts.cjs"));
  assert.doesNotMatch(server, /cpSync\([^\n]*\.env|https:\/\/api\.jzis\.org/);
});
