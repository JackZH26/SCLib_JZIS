import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const reporter = await readFile(
  new URL("../components/WebVitalsReporter.tsx", import.meta.url),
  "utf8",
);
const layout = await readFile(
  new URL("../app/layout.tsx", import.meta.url),
  "utf8",
);

test("browser health reporting is sampled and requires analytics consent", () => {
  assert.match(reporter, /NEXT_PUBLIC_WEB_VITALS_SAMPLE_RATE/);
  assert.match(reporter, /loadConsent\(\)\)\.analytics/);
  assert.match(reporter, /consent-change/);
  assert.match(reporter, /\/telemetry\/client/);
  assert.match(reporter, /credentials: "omit"/);
  assert.match(reporter, /keepalive: true/);
});

test("browser errors are reduced to aggregate signals without payload text", () => {
  assert.match(reporter, /event_type: "js_error", name: "error"/);
  assert.match(
    reporter,
    /event_type: "unhandled_rejection", name: "rejection"/,
  );
  assert.doesNotMatch(reporter, /\.message|\.reason|stack|location\.href/);
});

test("the reporter is mounted once at the application root", () => {
  assert.match(layout, /<WebVitalsReporter\s*\/>/);
});
