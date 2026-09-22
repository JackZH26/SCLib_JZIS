/** All private-workbench browser cases, with synthetic transports only.
 * This supplements the production-mode public-page suite; it is not backend E2E.
 */
import { lstatSync } from "node:fs";
import path from "node:path";
import { defineConfig } from "@playwright/test";

const artifacts = process.env.SCLIB_RESEARCH_BROWSER_OUTPUT;
if (!artifacts || !path.isAbsolute(artifacts) || !lstatSync(artifacts).isDirectory()
  || lstatSync(artifacts).isSymbolicLink()) {
  throw new Error("Use run-research-workbenches.cjs to prepare one owned output directory.");
}
const port = 32078;
const baseURL = `http://127.0.0.1:${port}`;

export default defineConfig({
  testDir: ".",
  testMatch: "*.visual.ts",
  forbidOnly: Boolean(process.env.CI),
  outputDir: path.join(artifacts, "test-results"),
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 45_000,
  reporter: [
    ["list"],
    ["json", { outputFile: path.join(artifacts, "results.json") }],
    ["html", { outputFolder: path.join(artifacts, "html"), open: "never" }],
  ],
  use: {
    baseURL,
    browserName: "chromium",
    serviceWorkers: "block",
    viewport: { width: 1440, height: 1000 },
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
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
