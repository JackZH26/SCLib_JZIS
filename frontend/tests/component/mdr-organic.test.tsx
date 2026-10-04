import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { cleanup, render, screen, within, fireEvent } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { OrganicReferenceBrowser } from "@/components/OrganicReferenceBrowser";
import { ORGANIC_FILE, ORGANIC_SHA256, organicCell, organicCode, organicExport, organicHref, organicQuery, organicSnapshot, organicStructures } from "@/lib/mdr-organic";
import { GET } from "@/app/materials/source-references/organic/export/route";

afterEach(() => { cleanup(); vi.unstubAllEnvs(); });
const sha = (bytes: string | Buffer) => createHash("sha256").update(bytes).digest("hex");
describe("Complete Organic source reference reader", () => {
  it("pins all 568 nonempty rows and retains raw pressure and isotope distinctions", () => {
    const data = organicSnapshot();
    expect(sha(readFileSync(`public/research-pilots/${ORGANIC_FILE}`))).toBe(ORGANIC_SHA256);
    expect(sha(readFileSync("public/research-pilots/240322_MDR_Organic.txt"))).toBe(data.source.sha256);
    expect(data.rows).toHaveLength(568); expect(data.columns).toHaveLength(49); expect(data.excluded_rows).toHaveLength(1);
    expect(new Set(data.rows.map(row => row.id)).size).toBe(568);
    expect(data.rows.every(row => row.values.length === 49)).toBe(true);
    const [a, b] = ["2", "3"].map(row => organicQuery({ row }).rows[0]);
    expect(organicCell(a, "fullname")).toBe(organicCell(b, "fullname"));
    expect(organicCell(a, "commt")).toContain("hydrogenated"); expect(organicCell(b, "commt")).toContain("deuterated");
    expect(organicCell(b, "pcrit")).toBe("0.044"); expect(organicCell(b, "pmax")).toBe("0.045");
    expect(organicCell(b, "commt")).toContain("0.05 GPa");
    b.values[0] = "changed"; expect(organicQuery({ row: "3" }).rows[0].values[0]).toBe("3");
  });

  it("filters the complete table, retaining zero values, exact source labels and every page", () => {
    expect(organicQuery({ field: "tc" }).rows).toHaveLength(517);
    expect(organicQuery({ field: "tcmax" }).rows).toHaveLength(83);
    expect(organicQuery({ field: "pcrit" }).rows).toHaveLength(484);
    expect(organicQuery({ structure: "TMTSF" }).rows).toHaveLength(46);
    expect(organicQuery({ structure: "picene" }).rows).toHaveLength(4);
    expect(organicQuery({ structure: "Picene" }).rows).toHaveLength(11);
    expect(organicStructures()).toContain("[Pd(dmit)2");
    expect(organicCell(organicQuery({ row: "1" }).rows[0], "pcrit")).toBe("0");
    expect(organicQuery({ q: "deuterated" }).rows.length).toBeGreaterThan(1);
    const all = organicQuery({}); const ids = [];
    for (let page = 0; page < all.pages; page++) ids.push(...all.rows.slice(page * 20, (page + 1) * 20).map(row => row.id));
    expect(ids).toEqual(organicSnapshot().rows.map(row => row.id)); expect(new Set(ids).size).toBe(568);
    expect(organicCode("shape", "2")).toBe("Multiphase bulk (code 2)");
    expect(organicCode("tcmeth", "RM")).toBe("Unresolved code RM");
  });

  it("rejects ambiguous filters rather than showing unrelated rows", () => {
    for (const params of [{ q: ["Mg", "B"] }, { q: "x".repeat(129) }, { q: "\n" }, { field: "bogus" }, { structure: "unknown" }, { row: "0" }, { page: "1.5" }, { page: "-1" }, { page: "1e2" }, { extra: "x" }]) {
      const result = organicQuery(params); expect(result.errors.length).toBeGreaterThan(0); expect(result.rows).toHaveLength(0);
      expect(() => organicExport(params)).toThrow();
    }
    expect(organicQuery({ row: "99999" }).rows).toHaveLength(0);
    expect(organicQuery({ q: "<script>alert(1)</script>" }).rows).toHaveLength(0);
  });

  it("exports all matches independent of page with complete raw cells and source scope", async () => {
    const payload = organicExport({ structure: "TMTSF", page: "1" });
    expect(payload).toBe(organicExport({ structure: "TMTSF", page: "0" }));
    const value = JSON.parse(payload); expect(value.rows).toHaveLength(46); expect(value.matches).toBe(46);
    expect(value.source_snapshot_sha256).toBe(ORGANIC_SHA256);
    expect(value.source_dataset.scope.canonical_properties_modified).toBe(false);
    expect(value.source_dataset.scope.catalogue_association).toBe("unestablished");
    const response = GET(new Request("https://example.test/materials/source-references/organic/export?structure=TMTSF&page=1"));
    expect(response.status).toBe(200); expect(await response.text()).toBe(payload);
    expect(response.headers.get("X-Content-SHA256")).toBe(sha(payload));
    expect(response.headers.get("Content-Disposition")).toContain(sha(payload).slice(0, 12));
    for (const search of ["q=a&q=b", "__proto__=x&__proto__=y", "field=bad"]) expect(GET(new Request(`https://example.test/export?${search}`)).status).toBe(400);
  });

  it("rejects unknown export keys before accepting filters and preserves repeated-value rejection", async () => {
    for (const key of ["__proto__", "constructor", "prototype", "toString", "extra", "q[0]"]) {
      const response = GET(new Request(`https://example.test/export?structure=TMTSF&${encodeURIComponent(key)}=x`));
      expect(response.status).toBe(400);
      expect(await response.json()).toEqual({ error: "Invalid Organic source filters. Clear the filters and try again." });
      expect(response.headers.get("Content-Disposition")).toBeNull();
    }
    for (const key of ["q", "structure", "field", "row", "page"]) {
      expect(GET(new Request(`https://example.test/export?${key}=&${key}=`)).status).toBe(400);
    }
    const response = GET(new Request("https://example.test/export?q=&structure=TMTSF&field=tc&row=54&page=0"));
    expect(response.status).toBe(200);
    expect(await response.text()).toBe(organicExport({ q: "", structure: "TMTSF", field: "tc", row: "54", page: "0" }));
  });

  it("renders useful source distinctions without adding K or GPa to unspecified units", () => {
    render(<OrganicReferenceBrowser params={{ row: "3" }} />);
    const table = screen.getByRole("table");
    expect(table).toHaveTextContent("0.044 GPa"); expect(table).not.toHaveTextContent("0.045 GPa");
    expect(screen.getAllByText("13", { selector: "span" })).toHaveLength(2);
    screen.getAllByText("13", { selector: "span" }).forEach(value => expect(value).toHaveTextContent(/^13$/));
    const details = screen.getByText("Inspect row 3: properties, remarks and source").closest("details")!;
    fireEvent.click(within(details).getByText("Inspect row 3: properties, remarks and source"));
    expect(details).toHaveAttribute("open"); expect(details).toHaveTextContent("deuterated BEDT-TTF");
    expect(details).toHaveTextContent("Tc(S to M)=7.2");
    expect(screen.getByRole("region", { name: "Scrollable Organic reference table" })).toHaveAttribute("tabindex", "0");
    expect(screen.getByText(/Only/)).toHaveTextContent("other numeric columns lack unit fields");
    expect(screen.getByRole("form", { name: "Filter Organic source rows" })).toHaveAttribute("method", "get");
  });

  it("keeps non-SC limits distinct and supplies recoverable empty, invalid and last-page states", () => {
    const firstNonSc = organicQuery({ field: "tcn" }).rows[0];
    const view = render(<OrganicReferenceBrowser params={{ row: firstNonSc.id }} />);
    expect(screen.getByRole("table")).toHaveTextContent("Non-SC test limit");
    expect(screen.getByRole("table")).not.toHaveTextContent("Tc = 0");
    view.rerender(<OrganicReferenceBrowser params={{ page: "28" }} />);
    expect(screen.getByRole("status")).toHaveTextContent("561–568 shown");
    expect(screen.queryByRole("link", { name: "Next", exact: true })).not.toBeInTheDocument();
    view.rerender(<OrganicReferenceBrowser params={{ page: "29" }} />);
    expect(screen.getByRole("alert")).toHaveTextContent("outside the current results");
    view.rerender(<OrganicReferenceBrowser params={{ q: "no-such-source-name" }} />);
    expect(screen.getByText(/No source rows match/)).toBeInTheDocument();
    view.rerender(<OrganicReferenceBrowser params={{ field: "bad" }} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Unknown property");
  });

  it("preserves filters in pagination, escapes text and supports a site prefix", () => {
    expect(organicHref({ q: "a&b", structure: "TMTSF", field: "tc", row: "", page: 0 }, 1)).toBe("/materials/source-references/organic?q=a%26b&structure=TMTSF&field=tc&page=1");
    vi.stubEnv("NEXT_PUBLIC_BASE_PATH", "/sclib");
    render(<OrganicReferenceBrowser params={{ q: "<img src=x>" }} />);
    expect(screen.getByRole("textbox", { name: "Names, remarks or reference" })).toHaveValue("<img src=x>");
    expect(document.querySelectorAll("img")).toHaveLength(0);
    expect(screen.getByRole("form")).toHaveAttribute("action", "/sclib/materials/source-references/organic");
    expect(screen.getByRole("link", { name: "Original table bytes" })).toHaveAttribute("href", "/sclib/research-pilots/240322_MDR_Organic.txt");
  });

  it("restores form controls from URL props after clear or back navigation", () => {
    const view = render(<OrganicReferenceBrowser params={{ structure: "TMTSF", q: "ClO4" }} />);
    fireEvent.change(screen.getByRole("textbox", { name: "Names, remarks or reference" }), { target: { value: "unsent edit" } });
    view.rerender(<OrganicReferenceBrowser params={{}} />);
    expect(screen.getByRole("textbox", { name: "Names, remarks or reference" })).toHaveValue("");
    expect(screen.getByRole("combobox", { name: "Source structure label" })).toHaveValue("");
    view.rerender(<OrganicReferenceBrowser params={{ structure: "TMTSF", q: "ClO4" }} />);
    expect(screen.getByRole("textbox", { name: "Names, remarks or reference" })).toHaveValue("ClO4");
    expect(screen.getByRole("combobox", { name: "Source structure label" })).toHaveValue("TMTSF");
  });
});
