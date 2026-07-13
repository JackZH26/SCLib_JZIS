import { defineConfig } from "@playwright/test";

const port = 3102;
const baseURL = `http://127.0.0.1:${port}/sclib/`;

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? [["line"], ["html", { open: "never" }]] : "line",
  use: {
    baseURL,
    browserName: "chromium",
    viewport: { width: 390, height: 844 },
    deviceScaleFactor: 1,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  webServer: {
    command: `pnpm build && pnpm start --hostname 127.0.0.1 --port ${port}`,
    url: baseURL,
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
    env: {
      ...process.env,
      NEXT_PUBLIC_BASE_PATH: "/sclib",
      NEXT_PUBLIC_API_BASE: "https://api.jzis.org/sclib/v1",
      API_BASE_SERVER: "https://api.jzis.org/sclib/v1",
    },
  },
});
