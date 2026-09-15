import { expect, test as base, type BrowserContext } from "@playwright/test";

/** Browser-only HTTP restriction, not an OS sandbox or backend integration test. */
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
    if (!baseURL || new URL(baseURL).origin !== "http://127.0.0.1:3102") {
      throw new Error("Public browser tests require the owned loopback server.");
    }
    const blocked = await restrictToLocalOrigin(context, new URL(baseURL).origin);
    await use();
    expect(blocked, "Public-page tests must not depend on external HTTP or WebSockets").toEqual([]);
  }, { auto: true }],
});

export { expect };
