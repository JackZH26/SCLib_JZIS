import { afterEach, describe, expect, it, vi } from "vitest";
import { ask, search } from "@/lib/api";

describe("query cancellation reaches the fetch boundary", () => {
  afterEach(() => vi.unstubAllGlobals());
  it.each(["search", "ask"] as const)("forwards the exact %s AbortSignal without dropping authenticated transport", async operation => {
    const controller = new AbortController();
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({}), { status: 200 }));
    vi.stubGlobal("fetch", fetch);
    if (operation === "search") await search({ query: "中文 MgB₂" }, { signal: controller.signal });
    else await ask({ question: "中文 MgB₂" }, { signal: controller.signal });
    expect(fetch).toHaveBeenCalledOnce();
    const [url, init] = fetch.mock.calls[0];
    expect(url).toMatch(new RegExp(`/${operation}$`));
    expect(init.signal).toBe(controller.signal);
    expect(init.credentials).toBe("include");
    expect(init.body).toContain("中文 MgB₂");
    controller.abort();
    expect(init.signal.aborted).toBe(true);
  });
});
