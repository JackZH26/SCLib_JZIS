/** Offline, isolated visual QA. Never starts or reuses the normal .next server.
 * Run: pnpm exec playwright test --config tests/e2e/scientific-review.config.ts
 */
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { defineConfig } from "@playwright/test";

const port = 32032;
const baseURL = `http://127.0.0.1:${port}`;
const outputDir = mkdtempSync(path.join(tmpdir(), "sclib-review-browser-artifacts-"));

export default defineConfig({
  testDir: ".",
  testMatch: "scientific-review.visual.ts",
  outputDir,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 45_000,
  reporter: "list",
  use: { baseURL, browserName: "chromium", serviceWorkers: "block", screenshot: "only-on-failure",
    trace: "retain-on-failure", viewport: { width: 1440, height: 1000 } },
  webServer: {
    command: `${JSON.stringify(process.execPath)} ${JSON.stringify(path.join(__dirname, "scientific-review-server.cjs"))}`,
    url: `${baseURL}/dashboard/research/review`,
    reuseExistingServer: false,
    timeout: 90_000,
    stdout: "pipe",
    stderr: "pipe",
    env: { SCLIB_REVIEW_E2E_PORT: String(port) },
  },
});
