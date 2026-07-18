import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const header = readFileSync(
  new URL("../components/Header.tsx", import.meta.url),
  "utf8",
);
const layout = readFileSync(
  new URL("../app/layout.tsx", import.meta.url),
  "utf8",
);
const cookieConsent = readFileSync(
  new URL("../components/CookieConsent.tsx", import.meta.url),
  "utf8",
);

test("desktop navigation collapses into an accessible mobile menu", () => {
  assert.match(header, /hidden items-center[^\n]*md:flex/);
  assert.match(header, /aria-controls="mobile-navigation"/);
  assert.match(header, /aria-expanded=\{menuOpen\}/);
  assert.match(header, /aria-label="Mobile navigation"/);
  assert.match(header, /event\.key === "Escape"/);
});

test("mobile shells use compact gutters and stack consent actions", () => {
  assert.match(layout, /px-4 py-6 sm:px-6 sm:py-8/);
  assert.match(cookieConsent, /flex flex-col gap-2 sm:flex-row/);
});
