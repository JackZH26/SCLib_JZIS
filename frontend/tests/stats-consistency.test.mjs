import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const api = readFileSync(new URL("../lib/api.ts", import.meta.url), "utf8");
const page = readFileSync(new URL("../app/stats/page.tsx", import.meta.url), "utf8");
const cron = readFileSync(new URL("../../scripts/cron_daily_ingest.sh", import.meta.url), "utf8");

test("stats UI distinguishes aggregate refresh, data snapshot, and pipeline run", () => {
  assert.match(api, /stats_refreshed_at\?: string \| null/);
  assert.match(api, /data_pipeline\?:/);
  assert.match(page, /Statistics snapshot/);
  assert.match(page, /Data snapshot/);
  assert.match(page, /Data pipeline/);
  assert.match(page, /Pipeline stages/);
  assert.match(page, /stats\.stats_refreshed_at \?\? stats\.updated_at/);
});

test("daily cron reports each data stage without changing ingest cadence", () => {
  assert.match(cron, /pipeline_status="partial"/);
  assert.match(cron, /"incremental":\{"status":"%s","exit_code":%d\}/);
  assert.match(cron, /"retry":\{"status":"%s","exit_code":%d\}/);
  assert.match(cron, /"aggregate":\{"status":"%s","exit_code":%d\}/);
  assert.match(cron, /--data-binary "\$\{stats_refresh_payload\}"/);
});
