import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AdminAuditPage from "@/app/dashboard/admin/audit/page";
import { ApiError, adminAuditQueue, adminListAuditReports, adminOverview, adminOverrideFlag } from "@/lib/api";

vi.mock("@/lib/api", async importOriginal => ({
  ...await importOriginal<typeof import("@/lib/api")>(),
  adminAuditQueue: vi.fn(), adminListAuditReports: vi.fn(), adminOverview: vi.fn(),
  adminOverrideFlag: vi.fn(), adminConfirmFlag: vi.fn(),
}));
vi.mock("@/components/dashboard/user-context", () => ({ useDashboardUser: () => ({ user: { is_admin: true } }) }));

describe("legacy audit controls do not imply scientific approval", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(adminOverview).mockResolvedValue({ total_users: 1, active_users: 1, admins: 1, total_materials: 1, flagged_materials: 1, flagged_by_reason: {}, last_audit_started: null, last_audit_total_flagged: 1 });
    vi.mocked(adminListAuditReports).mockResolvedValue([]);
    vi.mocked(adminAuditQueue).mockResolvedValue({ total: 1, limit: 50, offset: 0, results: [{ id: "synthetic", formula: "TEST", family: null, tc_max: 60, review_reason: "tc_exceeds_family_cap", total_papers: 1, has_admin_decision: false }] });
    vi.mocked(adminOverrideFlag).mockResolvedValue({ id: "synthetic", needs_review: false, admin_decision: {} } as never);
  });

  it("labels historical thresholds as review triggers and sends a non-approval note", async () => {
    render(<AdminAuditPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Legacy override" }));
    await waitFor(() => expect(adminOverrideFlag).toHaveBeenCalledWith("synthetic", expect.stringContaining("Does not approve anomalous scientific values or source corrections")));
    expect(screen.getByText("historical family threshold review")).toBeInTheDocument();
    expect(screen.getByText(/Historical thresholds are review triggers, not physical upper limits/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Pass/ })).not.toBeInTheDocument();
    expect(screen.queryByTitle(/reappears.*immediately/)).not.toBeInTheDocument();
  });

  it("shows the server's refusal instead of claiming an anomaly was approved", async () => {
    vi.mocked(adminOverrideFlag).mockRejectedValue(new ApiError(409, {}, "Versioned anomaly review cannot be cleared by a legacy flag override."));
    render(<AdminAuditPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Legacy override" }));
    expect(await screen.findByText("Versioned anomaly review cannot be cleared by a legacy flag override.")).toBeInTheDocument();
    expect(screen.getByText("TEST")).toBeInTheDocument();
  });
});
