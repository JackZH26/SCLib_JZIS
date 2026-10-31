import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { defineConfig } from "@playwright/test";

const port = 32042, baseURL = `http://127.0.0.1:${port}`;
export default defineConfig({
  testDir: ".", testMatch: "materials-proposal-review.visual.ts", fullyParallel: false, workers: 1, retries: 0,
  timeout: 60_000, reporter: "list", outputDir: process.env.SCLIB_PROPOSAL_BROWSER_OUTPUT ?? mkdtempSync(path.join(tmpdir(), "sclib-proposal-browser-")),
  use: { baseURL, browserName: "chromium", serviceWorkers: "block", screenshot: "only-on-failure", trace: "retain-on-failure" },
  webServer: {
    command: `${JSON.stringify(process.execPath)} ${JSON.stringify(path.join(__dirname, "scientific-review-server.cjs"))}`,
    url: `${baseURL}/dashboard/research/materials-ner`, reuseExistingServer: false, timeout: 90_000,
    stdout: "pipe", stderr: "pipe", env: { SCLIB_REVIEW_E2E_PORT: String(port) },
  },
});
