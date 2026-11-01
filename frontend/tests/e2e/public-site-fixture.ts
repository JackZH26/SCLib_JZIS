import { expect, test as base, type BrowserContext } from "@playwright/test";

/** One canonical loopback origin only. No additional host or external origin is allowed.
 * Browser-only HTTP restriction, not an OS sandbox or backend integration test. */
export async function restrictToLocalOrigin(context: BrowserContext, origin: string) {
  const blocked: string[] = [];
  await context.route("**/*", async route => {
    const url = new URL(route.request().url());
    if (url.origin === origin) await route.continue();
    else if (url.href === "https://api.jzis.org/sclib/v1/auth/me"
      && route.request().method() === "GET") {
      // Public pages check cookie-session state on mount. Supply only an
      // anonymous synthetic response in memory; never forward it upstream.
      await route.fulfill({ status: 401, contentType: "application/json",
        headers: { "access-control-allow-origin": origin, "access-control-allow-credentials": "true",
          "cache-control": "no-store", "x-sclib-test-response": "synthetic-anonymous" },
        body: JSON.stringify({ detail: "Not authenticated" }) });
    }
    else if (url.origin === "https://api.jzis.org"
      && url.pathname === "/sclib/v1/materials/timeline"
      && url.searchParams.size === 1
      && ["2000", "5000", "20000"].includes(url.searchParams.get("max_points") ?? "")
      && route.request().method() === "GET") {
      // Exercise public recovery without forwarding a NER request to production.
      await route.fulfill({ status: 503, contentType: "application/json",
        headers: { "access-control-allow-origin": origin, "cache-control": "no-store",
          "x-sclib-test-response": "synthetic-timeline-unavailable" },
        body: JSON.stringify({ detail: "Timeline unavailable in the offline public-page test" }) });
    }
    else if (["https://api.jzis.org/sclib/v1/discovery/rps/releases",
      "https://api.jzis.org/sclib/v1/discovery/scientific"].includes(url.href)
      && route.request().method() === "GET") {
      // The unified Discovery page mounts the existing public research panels.
      // Keep their unavailable state explicit and never contact production.
      await route.fulfill({ status: 503, contentType: "application/json",
        headers: { "access-control-allow-origin": origin, "access-control-allow-credentials": "true",
          "cache-control": "no-store", "x-sclib-test-response": "synthetic-discovery-unavailable" },
        body: JSON.stringify({ detail: "Research API unavailable in the offline public-page test" }) });
    }
    else {
      blocked.push(url.href);
      await route.abort("blockedbyclient");
    }
  });
  // A production build needs no WebSocket. Refuse it without opening upstream.
  await context.routeWebSocket("**/*", socket => {
    blocked.push(socket.url());
    socket.close();
  });
  return blocked;
}

export const test = base.extend<{ publicNetworkGuard: void }>({
  publicNetworkGuard: [async ({ context, baseURL }, use) => {
    if (!baseURL || new URL(baseURL).origin !== "http://localhost:3102") {
      throw new Error("Public browser tests require the owned loopback server.");
    }
    const blocked = await restrictToLocalOrigin(context, new URL(baseURL).origin);
    await use();
    expect(blocked, "Public-page tests must not depend on external HTTP or WebSockets").toEqual([]);
  }, { auto: true }],
});

export { expect };
