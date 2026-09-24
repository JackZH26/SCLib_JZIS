import { render, screen, fireEvent } from "@testing-library/react";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { middleware } from "../../middleware";
import { legacyDestination, isPrivatePage } from "@/lib/site-routes";
import { getLibrarySnapshot } from "@/lib/library-snapshot";
import { SearchBar } from "@/components/SearchBar";

const push = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

beforeEach(() => { vi.stubEnv("NEXT_PUBLIC_BASE_PATH", ""); push.mockClear(); });
afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); });

describe("legacy and canonical website routes", () => {
  it.each([
    ["/sclib", "/"], ["/sclib/", "/"], ["/sclib/materials", "/materials"],
    ["/sclib/materials/mat%3AFe%2FSe%252B", "/materials/mat%3AFe%2FSe%252B"],
    ["/sclib/paper/cond-mat%2F123", "/paper/cond-mat%2F123"],
    ["/sclib/auth/verify", "/verify"], ["/auth/verify", "/verify"],
    ["/sclib/api-docs", "/docs/api"], ["/sclib/ask", "/search"],
    ["/sclib/dashboard/history/a", "/dashboard/history/a"],
    ["/sclib/unknown", null], ["/sclibrary", null], ["/materials", null],
  ])("maps %s without decoding IDs", (input, output) => expect(legacyDestination(input)).toBe(output));

  it("combines www and old paths in one redirect without losing encoded queries", () => {
    const response = middleware(new NextRequest("https://www.jzis.org/sclib/materials/mat%3AFe%2FSe?q=Fe%2BSe&page=2"));
    expect(response.status).toBe(308);
    expect(response.headers.get("location")).toBe("https://jzis.org/materials/mat%3AFe%2FSe?q=Fe%2BSe&page=2");
  });

  it.each(["/sclib/auth/verify", "/sclib/verify", "/sclib/auth/callback", "/sclib/reset-password", "/sclib/dashboard/keys"])("keeps %s temporary and private", path => {
    const response = middleware(new NextRequest(`https://jzis.org${path}?token=synthetic%2Btoken&state=synthetic-state`));
    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toContain("?token=synthetic%2Btoken&state=synthetic-state");
    expect(response.headers.get("cache-control")).toContain("no-store");
    expect(response.headers.get("referrer-policy")).toBe("no-referrer");
    expect(response.headers.get("x-robots-tag")).toContain("noindex");
  });

  it("marks current auth and account pages private without redirecting", () => {
    for (const path of ["/verify", "/auth/callback", "/dashboard/history", "/login"]) {
      expect(isPrivatePage(path)).toBe(true);
      const response = middleware(new NextRequest(`https://jzis.org${path}`));
      expect(response.headers.has("location")).toBe(false);
      expect(response.headers.get("cache-control")).toContain("no-store");
    }
    expect(isPrivatePage("/docs/api")).toBe(false);
  });

  it("does not redirect unknown old URLs to the homepage", () => {
    const response = middleware(new NextRequest("https://jzis.org/sclib/not-a-page"));
    expect(response.headers.has("location")).toBe(false);
  });
});

describe("homepage snapshot", () => {
  it("caches only anonymous public aggregates and sets a finite request deadline", async () => {
    const snapshot = { total_papers: 123, total_materials: 45 };
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => snapshot });
    vi.stubGlobal("fetch", fetchMock);
    expect(await getLibrarySnapshot()).toEqual(snapshot);
    const [, options] = fetchMock.mock.calls[0];
    expect(options.credentials).toBe("omit");
    expect(options.next.revalidate).toBe(300);
    expect(options.signal).toBeDefined();
    expect(options.headers).toBeUndefined();
  });
  it.each([null, { total_papers: -1, total_materials: 5 }, { total_papers: "123", total_materials: 5 }])("does not invent counts for invalid snapshots", async body => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => body }));
    expect(await getLibrarySnapshot()).toBeNull();
  });
  it("keeps the homepage usable when the snapshot request fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("unavailable")));
    expect(await getLibrarySnapshot()).toBeNull();
  });
});

it("submits formulas and multilingual queries without changing their meaning", () => {
  render(<SearchBar />);
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: "  FeSe + 超导  " } });
  fireEvent.submit(screen.getByRole("search"));
  expect(push).toHaveBeenCalledWith("/search?q=" + encodeURIComponent("FeSe + 超导"));
});
