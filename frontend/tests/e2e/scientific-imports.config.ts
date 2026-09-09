/** Isolated offline UI QA; no original .next, existing server or real import. */
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { defineConfig } from "@playwright/test";

const port = 32045;
const baseURL = `http://127.0.0.1:${port}`;

export default defineConfig({
  testDir: ".", testMatch: "scientific-imports.visual.ts",
  outputDir: mkdtempSync(path.join(tmpdir(), "sclib-scientific-import-browser-artifacts-")),
  fullyParallel: false, workers: 1, retries: 0, timeout: 45_000, reporter: "list",
  use: { baseURL, browserName: "chromium", serviceWorkers: "block", screenshot: "only-on-failure",
    trace: "retain-on-failure", viewport: { width: 1440, height: 1000 } },
  webServer: {
    command: `${JSON.stringify(process.execPath)} ${JSON.stringify(path.join(__dirname, "scientific-review-server.cjs"))}`,
    url: `${baseURL}/dashboard/research/imports`, reuseExistingServer: false, timeout: 90_000,
    stdout: "pipe", stderr: "pipe", env: { SCLIB_REVIEW_E2E_PORT: String(port) },
  },
});
