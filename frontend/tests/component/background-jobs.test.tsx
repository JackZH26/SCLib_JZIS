import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import BackgroundJobsPage from "@/app/dashboard/admin/jobs/page";
import { adminBackgroundJobs, ApiError, type BackgroundCycle, type BackgroundJobsResponse } from "@/lib/api";

const actor = vi.hoisted(() => ({ is_admin: true }));
vi.mock("@/components/dashboard/user-context", () => ({ useDashboardUser: () => ({ user: actor }) }));
vi.mock("@/lib/api", async importOriginal => ({
  ...await importOriginal<typeof import("@/lib/api")>(), adminBackgroundJobs: vi.fn(),
}));

function cycle(changes: Partial<BackgroundCycle> = {}): BackgroundCycle {
  return { cycle_id: "synthetic-cycle", status: "succeeded", scheduled_for: "2026-09-07T20:00:00Z",
    started_at: "2026-09-07T20:00:30Z", completed_at: "2026-09-07T20:00:32Z", duration_ms: 2000,
    attempts: 1, recovered: false, result: {}, error_code: null, next_retry_at: null,
    completion_scope: "database_effects_only", ...changes };
}

function fixture(): BackgroundJobsResponse {
  return { version: "background-cycle/1.0.0", scope: "database_cycles_not_external_cache_delivery", jobs: [
    { job_name: "stats_refresh", active_owner_id: "synthetic-owner", lock_observation: "current_query_only", last_success: null,
      oldest_unfinished: cycle({ status: "running", duration_ms: null, completed_at: null }), recent_cycles: [] },
    { job_name: "timeline_projection", active_owner_id: null, lock_observation: "current_query_only", last_success: null,
      oldest_unfinished: cycle({ status: "failed", error_code: "timeout", attempts: 2, next_retry_at: "2026-09-07T20:02:00Z" }), recent_cycles: [] },
    { job_name: "formula_audit", active_owner_id: null, lock_observation: "current_query_only", oldest_unfinished: null,
      last_success: cycle({ result: { flagged: 5, rule_count: 4, private_note: "MUST_NOT_DISPLAY" } }), recent_cycles: [cycle()] },
    { job_name: "nightly_audit", active_owner_id: null, lock_observation: "current_query_only", last_success: null,
      oldest_unfinished: cycle({ status: "running", duration_ms: null, completed_at: null }), recent_cycles: [] },
    { job_name: "ask_history_prune", active_owner_id: null, lock_observation: "current_query_only", last_success: null,
      oldest_unfinished: null, recent_cycles: [] },
  ] };
}

describe("administrator background job inspection", () => {
  beforeEach(() => {
    actor.is_admin = true;
    vi.resetAllMocks();
    vi.mocked(adminBackgroundJobs).mockResolvedValue(fixture());
  });

  it("shows all five jobs and distinguishes durable SQL completion from external delivery", async () => {
    render(<BackgroundJobsPage />);
    expect(await screen.findByText("Ask history retention")).toBeVisible();
    expect(screen.getByText("Running")).toBeVisible();
    expect(screen.getByText("Failed · retry pending")).toBeVisible();
    expect(screen.getByText("Interrupted / no owner observed")).toBeVisible();
    expect(screen.getByText("Not run")).toBeVisible();
    expect(screen.getByText(/not external cache delivery or scientific acceptance/)).toBeVisible();
    expect(screen.getByText(/All times are UTC/)).toBeVisible();
    expect(screen.queryByRole("button", { name: /execute|retry now|approve|publish/i })).not.toBeInTheDocument();
    expect(screen.queryByText("MUST_NOT_DISPLAY")).not.toBeInTheDocument();
  });

  it("shows observed owner, failure codes, retry time and committed counters in details", async () => {
    render(<BackgroundJobsPage />);
    fireEvent.click(await screen.findByText("Dashboard statistics · cycle details"));
    expect(screen.getByText("synthetic-owner")).toBeVisible();
    fireEvent.click(screen.getByText("Timeline projection · cycle details"));
    expect(screen.getByText("timeout")).toBeVisible();
    expect(screen.getByText("Sep 7, 2026, 8:02:00 PM")).toBeVisible();
    fireEvent.click(screen.getByText("Formula audit · cycle details"));
    expect(screen.getByText("Last committed counters: 5 newly flagged · 4 rules")).toBeVisible();
  });

  it("keeps authorization authoritative and removes previously displayed status after refusal", async () => {
    render(<BackgroundJobsPage />);
    await screen.findByText("Ask history retention");
    vi.mocked(adminBackgroundJobs).mockRejectedValue(new ApiError(403, {}, "PRIVATE SERVER DETAILS"));
    fireEvent.click(screen.getByRole("button", { name: "Refresh status" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Administrator access required.");
    expect(screen.queryByText("Ask history retention")).not.toBeInTheDocument();
    expect(screen.queryByText("PRIVATE SERVER DETAILS")).not.toBeInTheDocument();
    await waitFor(() => expect(adminBackgroundJobs).toHaveBeenCalledTimes(2));
  });

  it("does not query operational data for a non-administrator", async () => {
    actor.is_admin = false;
    render(<BackgroundJobsPage />);
    expect(screen.getByRole("alert")).toHaveTextContent("Administrator access required.");
    expect(adminBackgroundJobs).not.toHaveBeenCalled();
  });

  it("shows an English unavailable state rather than an empty successful queue", async () => {
    vi.mocked(adminBackgroundJobs).mockRejectedValue(new ApiError(503, {}, "PRIVATE DATABASE DETAILS"));
    render(<BackgroundJobsPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Background job status is unavailable. Try again later.");
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.queryByText("PRIVATE DATABASE DETAILS")).not.toBeInTheDocument();
  });
});
