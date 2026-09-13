/** Isolated local browser QA with synthetic adapters, never the production API. */
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { defineConfig } from "@playwright/test";
const port = 32066, baseURL = `http://127.0.0.1:${port}`;
export default defineConfig({
  testDir: ".", testMatch: "ml-pilot-reviews.visual.ts", outputDir: mkdtempSync(path.join(tmpdir(), "sclib-ml-review-browser-artifacts-")),
  fullyParallel: false, workers: 1, retries: 0, timeout: 45000, reporter: "list",
  use: { baseURL, browserName: "chromium", serviceWorkers: "block", screenshot: "only-on-failure", trace: "retain-on-failure" },
  webServer: { command: `${JSON.stringify(process.execPath)} ${JSON.stringify(path.join(__dirname, "scientific-review-server.cjs"))}`,
    url: `${baseURL}/dashboard/research/ml-pilot-reviews`, reuseExistingServer: false, timeout: 90000,
    stdout: "pipe", stderr: "pipe", env: { SCLIB_REVIEW_E2E_PORT: String(port) } },
});
