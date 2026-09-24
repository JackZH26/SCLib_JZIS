import { defineConfig } from "@playwright/test";
import path from "node:path";

const port = 3102;
const baseURL = `http://127.0.0.1:${port}/`;

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI
    ? [["line"], ["json", { outputFile: "playwright-results.json" }], ["html", { open: "never" }]]
    : "line",
  use: {
    baseURL,
    browserName: "chromium",
    serviceWorkers: "block",
    viewport: { width: 390, height: 844 },
    deviceScaleFactor: 1,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  webServer: {
    command: `${JSON.stringify(process.execPath)} ${JSON.stringify(path.join(__dirname, "tests/e2e/public-site-server.cjs"))}`,
    url: `${baseURL}login`,
    reuseExistingServer: false,
    timeout: 180_000,
  },
});
