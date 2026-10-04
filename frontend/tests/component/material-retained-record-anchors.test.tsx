import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import MaterialDetailPage from "@/app/materials/[id]/page";
import { getMaterial, getMaterialEnrichment, getMaterialHydrideParameters, type MaterialDetail } from "@/lib/api";
import { materialVisibility } from "../fixtures/material-visibility";

vi.mock("@/lib/api", async original => ({ ...await original<typeof import("@/lib/api")>(), getMaterial: vi.fn(), getMaterialEnrichment: vi.fn(), getMaterialHydrideParameters: vi.fn() }));
vi.mock("@/components/BookmarkButton", () => ({ BookmarkButton: () => <span>Save control</span> }));
beforeEach(() => { vi.resetAllMocks(); vi.mocked(getMaterialEnrichment).mockImplementation(() => new Promise(() => {})); vi.mocked(getMaterialHydrideParameters).mockResolvedValue([]); });
afterEach(cleanup);
it("keeps deep links on the original raw retained index despite Tc sorting and visibility exclusion", async () => {
  const mat = { id: "synthetic-anchor-material", formula: "TEST", family: null, subfamily: null, visibility: materialVisibility(), records: [
    { tc_kelvin: 10, tc_type: "first-raw-record", paper_id: "synthetic-paper", visibility: materialVisibility() },
    { tc_kelvin: 200, tc_type: "restricted-record", paper_id: "synthetic-paper", visibility: materialVisibility("quarantined") },
    { tc_kelvin: 20, tc_type: "third-raw-record", paper_id: "synthetic-paper", visibility: materialVisibility() },
  ], variants: [], disputed: false, retracted: false, total_papers: 1 } as unknown as MaterialDetail;
  vi.mocked(getMaterial).mockResolvedValue(mat);
  render(await MaterialDetailPage({ params: Promise.resolve({ id: mat.id }) }));
  const rows = within(screen.getByRole("region", { name: "Scrollable retained evidence" })).getAllByRole("row").slice(1);
  expect(rows.map(row => row.id)).toEqual(["retained-record-2", "retained-record-0"]);
  expect(document.getElementById("retained-record-1")).toBeNull();
  expect(document.getElementById("retained-record-2")).toHaveTextContent("third-raw-record");
  expect(document.getElementById("retained-record-2")).toHaveAttribute("tabindex", "-1");
  expect(document.getElementById("retained-record-2")).toHaveAccessibleName("Retained record index 2");
});
