import { expect, test } from "./public-site-fixture";

for (const [path, heading] of [
  ["", "Superconductivity Research Library"], ["about", "About JZ Institute of Science"],
  ["about/join", "Join & contribute"], ["research", "Superconductivity research"],
  ["scwiki", "SCWiki"], ["scwiki/using-sclib", "Using SCLib"], ["docs/data", "Data & methodology"],
]) {
  test(`unified page ${path || "home"} is accessible and free of retired product content`, async ({ page }) => {
    await page.goto(path || "/");
    await expect(page.getByRole("heading", { name: heading, exact: true })).toBeVisible();
    expect(await page.locator("body").innerText()).not.toMatch(/ASRP|Agent Science Research Platform/i);
    expect(await page.locator('a[href*="asrp"], a[href*="www.jzis.org"]').count()).toBe(0);
    expect(new URL((await page.locator('link[rel="canonical"]').getAttribute("href"))!).href).toBe(`https://jzis.org/${path}`);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  });
}

test("root navigation links reach resources and the institution", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("searchbox")).toBeVisible();
  await page.getByRole("button", { name: "Open navigation" }).click();
  const menu = page.getByRole("navigation", { name: "Mobile navigation" });
  await menu.getByRole("link", { name: "SCWiki", exact: true }).click();
  await expect(page).toHaveURL(/\/scwiki$/);
  await expect(page.getByRole("button", { name: "Open navigation" })).toHaveAttribute("aria-expanded", "false");
  await page.goto("/#about");
  await expect(page).toHaveURL(/\/about$/);
});

test("legacy routes preserve query parameters, encoded IDs and private response headers", async ({ request }) => {
  for (const [path, expectedPath, status] of [
    ["/sclib/materials?page=2&family=cuprate", "/materials?page=2&family=cuprate", 308],
    ["/sclib/materials/mat%3AFe%2FSe%252B", "/materials/mat%3AFe%2FSe%252B", 308],
    ["/sclib/auth/verify?token=synthetic%2Btoken", "/verify?token=synthetic%2Btoken", 307],
    ["/sclib/auth/callback?error=oauth_failed", "/auth/callback?error=oauth_failed", 307],
    ["/sclib/api-docs", "/docs/api", 308],
  ] as const) {
    const response = await request.get(path, { maxRedirects: 0 });
    expect(response.status()).toBe(status);
    expect(new URL(response.headers().location, "http://localhost:3102").pathname + new URL(response.headers().location, "http://localhost:3102").search).toBe(expectedPath);
    if (status === 307) {
      expect(response.headers()["cache-control"]).toContain("no-store");
      expect(response.headers()["referrer-policy"]).toBe("no-referrer");
    }
  }
  expect((await request.get("/sclib/not-a-real-page")).status()).toBe(404);
});

test("authentication pages cannot be shared-cached or leak referrers", async ({ request }) => {
  const response = await request.get("/verify?token=synthetic-only");
  expect(response.headers()["cache-control"]).toContain("no-store");
  expect(response.headers()["referrer-policy"]).toBe("no-referrer");
  expect(response.headers()["x-robots-tag"]).toContain("noindex");
});

test("proxy Host determines the public redirect destination, never the loopback upstream", async ({ request }) => {
  for (const host of ["www.jzis.org", "jzis.org"]) {
    const response = await request.get("/sclib/materials?page=2", { headers: { Host: host }, maxRedirects: 0 });
    expect(response.status()).toBe(308);
    expect(response.headers().location).toBe("https://jzis.org/materials?page=2");
  }
});

test("desktop header stays on one line and the search remains in the first viewport", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  const navigation = page.getByRole("navigation", { name: "Primary", exact: true });
  await expect(navigation).toBeVisible();
  expect((await page.locator("header").boundingBox())!.height).toBeLessThanOrEqual(80);
  expect((await page.getByRole("searchbox").boundingBox())!.y).toBeLessThan(600);
  await page.getByRole("button", { name: "Reject all", exact: true }).click();
  await page.screenshot({ path: "test-results/integration-desktop.png", fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: "test-results/integration-mobile.png", fullPage: true });
});

test("redesigned search has a visible label and retains the query contract", async ({ page }) => {
  const queries: string[] = [];
  // This one request receives a synthetic empty result entirely in memory.
  // The public fixture still denies every other external request.
  await page.route("https://api.jzis.org/sclib/v1/search", async route => {
    expect(route.request().method()).toBe("POST");
    queries.push(route.request().postDataJSON().query);
    await route.fulfill({ status: 200, contentType: "application/json",
      headers: { "access-control-allow-origin": "http://localhost:3102", "access-control-allow-credentials": "true" },
      body: JSON.stringify({ results: [], query_time_ms: 0 }) });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Reject all", exact: true }).click();
  // React streaming may temporarily retain a second form in a hidden segment.
  // Assert the accessible form and its actual label association, not every
  // label in the document (which also includes that invisible staging DOM).
  const form = page.getByRole("search", { name: "Library search", exact: true });
  await expect(form).toHaveCount(1);
  const label = form.locator("label[for]");
  await expect(label).toBeVisible();
  await expect(label).toHaveText("Search the library");
  const input = form.getByRole("searchbox");
  await expect(input).toBeVisible();
  await expect(label).toHaveAttribute("for", (await input.getAttribute("id"))!);
  await expect(input).toHaveAttribute("name", "q");
  await input.fill("FeSe + FeTe");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  // A pre-hydration GET form uses "+" for spaces; client navigation uses
  // "%20". Both must retain the literal plus and the exact decoded query.
  await expect(page).toHaveURL(url =>
    url.pathname === "/" && url.searchParams.get("q") === "FeSe + FeTe");
  expect([...new URL(page.url()).searchParams.keys()]).toEqual(["q"]);
  await expect(page.getByRole("heading", { name: "Results for “FeSe + FeTe”", exact: true })).toBeVisible();
  await expect(page.getByRole("searchbox")).toHaveValue("FeSe + FeTe");
  await expect.poll(() => queries).toEqual(["FeSe + FeTe"]);
});

for (const width of [1440, 390]) {
  test(`Home combines literature and Wiki independently at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    // Deliberately fail only the synthetic literature service; Wiki uses the real local index.
    await page.route("https://api.jzis.org/sclib/v1/search", route => route.fulfill({
      status:503, contentType:"application/json",
      headers:{"access-control-allow-origin":"http://localhost:3102","access-control-allow-credentials":"true"},
      body:JSON.stringify({detail:"Synthetic literature outage"}),
    }));
    await page.goto("/scwiki");
    if (width === 390) await page.getByRole("button",{name:"Open navigation"}).click();
    const nav=page.getByRole("navigation",{name:width===390?"Mobile navigation":"Primary",exact:true});
    await expect(nav.getByRole("link",{name:"Search",exact:true})).toHaveCount(0);
    await nav.getByRole("link",{name:"Home",exact:true}).click();
    await expect(page).toHaveURL(/\/$/);
    await page.getByRole("button",{name:"Reject all",exact:true}).click();
    await page.getByRole("searchbox").fill("Meissner");
    await page.getByRole("button",{name:"Search",exact:true}).click();
    const literature=page.getByRole("region",{name:"Literature",exact:true});
    const wiki=page.getByRole("region",{name:"SCWiki",exact:true});
    await expect(wiki.getByRole("link",{name:"The Meissner effect and magnetic evidence",exact:true})).toBeVisible();
    const left=(await literature.boundingBox())!,right=(await wiki.boundingBox())!;
    if(width===1440) { expect(right.x).toBeGreaterThan(left.x+left.width); expect(Math.abs(left.y-right.y)).toBeLessThan(2); }
    else { expect(right.y).toBeGreaterThan(left.y+left.height); expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(width); }
    await wiki.scrollIntoViewIfNeeded();
    await page.screenshot({path:`test-results/home-unified-${width}.png`,fullPage:true});
    await page.goto("/search?q=Meissner&tag=a&tag=b");
    await expect(page).toHaveURL(/\/\?q=Meissner&tag=a&tag=b$/);
    await expect(page.getByRole("searchbox")).toHaveValue("Meissner");
  });
}

test("keyboard navigation skips the shell and restores focus after menu escape", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Reject all", exact: true }).click();
  await page.getByRole("link", { name: "Skip to content" }).focus();
  await page.keyboard.press("Enter");
  await expect(page.locator("#main-content")).toBeFocused();
  const headingBox = (await page.getByRole("heading", { level: 1 }).boundingBox())!;
  const headerBox = (await page.locator("header").boundingBox())!;
  expect(headingBox.y).toBeGreaterThanOrEqual(headerBox.y + headerBox.height);
  const toggle = page.getByRole("button", { name: "Open navigation" });
  await toggle.click();
  await page.getByRole("navigation", { name: "Mobile navigation" }).getByRole("link", { name: "SCWiki", exact: true }).focus();
  await page.keyboard.press("Escape");
  await expect(toggle).toBeFocused();
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
});

test("information-page contents reach preserved anchors without covering the heading", async ({ page }) => {
  await page.goto("about");
  await page.getByRole("button", { name: "Reject all", exact: true }).click();
  const contents = page.getByRole("navigation", { name: "On this page" });
  await contents.getByRole("link", { name: "Contact", exact: true }).click();
  await expect(page).toHaveURL(/\/about#contact$/);
  const contact = page.locator("h2#contact");
  await expect(contact).toBeInViewport();
  expect((await contact.boundingBox())!.y).toBeGreaterThanOrEqual(73);
  await page.setViewportSize({ width: 1440, height: 900 });
  await expect(page.getByRole("navigation", { name: "Primary", exact: true }).getByRole("link", { name: "About JZIS", exact: true })).toHaveAttribute("aria-current", "page");
});

test("hero asset is local, bounded and labelled as conceptual at every layout size", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Reject all", exact: true }).click();
  const artwork = page.getByRole("img", { name: /Conceptual illustration of a magnet levitating/ });
  await expect(artwork).toBeVisible();
  await expect(artwork).toHaveJSProperty("complete", true);
  expect(await artwork.evaluate(img => (img as HTMLImageElement).naturalWidth)).toBeGreaterThan(0);
  await page.evaluate(() => document.fonts.ready);
  for (const width of [320, 390, 768, 1024, 1280, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    const layout = await page.evaluate(() => {
      const heading = document.querySelector("h1")!;
      return { width: document.documentElement.scrollWidth,
        lines: heading.getBoundingClientRect().height / parseFloat(getComputedStyle(heading).lineHeight),
        searchBottom: document.querySelector('button[type="submit"]')!.getBoundingClientRect().bottom };
    });
    expect(layout.width).toBeLessThanOrEqual(width);
    expect(layout.lines, `Heading at ${width}px`).toBeLessThanOrEqual(2.01);
    expect(layout.searchBottom).toBeLessThan(700);
    if ([320, 390, 1440].includes(width)) await page.screenshot({ path: `test-results/approved-home-${width}.png`, fullPage: true });
  }
  await page.emulateMedia({ reducedMotion: "reduce" });
  const arrow = page.locator(".entry-arrow").first();
  await arrow.hover();
  expect(await arrow.evaluate(el => getComputedStyle(el).transform)).toBe("none");
});

test("the preserved light theme and image budget do not depend on OS preferences", async ({ page, request }) => {
  await page.emulateMedia({ colorScheme: "dark", reducedMotion: "reduce" });
  await page.goto("/");
  expect(await page.evaluate(() => getComputedStyle(document.documentElement).colorScheme)).toBe("light");
  expect(await page.locator("body").evaluate(el => getComputedStyle(el).backgroundColor)).toBe("rgb(247, 245, 239)");
  for (const width of [640, 1120]) {
    const response = await request.get(`/images/superconductivity-hero-${width}.webp`);
    expect(response.status()).toBe(200);
    expect(response.headers()["content-type"]).toContain("image/webp");
    expect((await response.body()).length).toBeLessThan(100_000);
  }
});

test("Materials formula lookup submits its GET form with existing filters and resets pagination", async ({ page }) => {
  // The owned SSR API is inert. This proves form navigation and URL state,
  // not native database matches, scientific values or source associations.
  await page.goto("/materials?q=NbN&family=conventional&tc_min=20&pressure_max=150&knowledge_origin=Computed&page=9&per_page=100&sort=tc_ambient");
  await page.getByRole("button", { name: "Reject all", exact: true }).click();
  const formula = page.getByRole("searchbox", { name: "Formula contains", exact: true });
  await expect(formula).toHaveValue("NbN");
  await expect(formula).toHaveAttribute("placeholder", "e.g. NbN or BiTeCl");
  // HTML counts UTF-16 units; the API admits at most 200 Unicode code points.
  await expect(formula).toHaveAttribute("maxlength", "400");
  const form = page.locator("#materials-filter-form");
  await expect(form).toHaveAttribute("method", "get");
  await expect(form).toHaveAttribute("action", "/materials");
  await expect(form.locator('[name="q"]')).toHaveCount(1);
  await expect(form.locator('input[type="hidden"][name="q"]')).toHaveCount(0);
  await expect(form.locator('[name="page"]')).toHaveCount(0);
  await formula.fill("BiTeCl");
  await formula.press("Enter");
  await expect.poll(() => new URL(page.url()).searchParams.get("q")).toBe("BiTeCl");
  const query = new URL(page.url()).searchParams;
  expect(query.getAll("q")).toEqual(["BiTeCl"]);
  expect(query.has("page")).toBe(false);
  expect(query.get("family")).toBe("conventional");
  expect(query.get("tc_min")).toBe("20");
  expect(query.get("pressure_max")).toBe("150");
  expect(query.get("knowledge_origin")).toBe("Computed");
  expect(query.get("per_page")).toBe("100");
  expect(query.get("sort")).toBe("tc_ambient");
  await expect(formula).toHaveValue("BiTeCl");
  await expect(page.getByLabel("Tc ≥ (K)", { exact: true })).toHaveValue("20");
  await expect(page.getByLabel("Pressure ≤ (GPa)", { exact: true })).toHaveValue("150");
  await expect(page.getByRole("combobox", { name: "Result origin", exact: true })).toHaveValue("Computed");
  const clear = page.getByRole("link", { name: "Clear filters", exact: true });
  await expect(clear).toHaveAttribute("href", "/materials");
  await clear.click();
  await expect(page).toHaveURL(/\/materials$/);
  await expect(formula).toHaveValue("");
});

test("Clear filters discards unsubmitted Materials edits even at the unfiltered URL", async ({ page }) => {
  await page.goto("/materials");
  await page.getByRole("button", { name: "Reject all", exact: true }).click();
  for (const width of [1280, 320]) {
    await page.setViewportSize({ width, height: 900 });
    await page.getByRole("searchbox", { name: "Formula contains", exact: true }).fill("BiTeCl");
    await page.getByLabel("Tc ≥ (K)", { exact: true }).fill("120");
    await page.getByLabel("Pressure ≤ (GPa)", { exact: true }).fill("200");
    await page.getByRole("combobox", { name: "Result origin", exact: true }).selectOption("Observed");
    await page.getByRole("button", { name: "All families", exact: true }).click();
    await page.getByRole("checkbox", { name: "Hydride", exact: true }).check();
    await page.getByRole("checkbox", { name: "Hydride", exact: true }).press("Escape");
    const family = page.getByRole("button", { name: "Hydride", exact: true });
    await expect(family).toBeFocused();
    await family.press("Tab");
    await expect(page.getByLabel("Tc ≥ (K)", { exact: true })).toBeFocused();
    await page.locator("summary").filter({ hasText: "Advanced filters" }).click();
    await page.getByRole("combobox", { name: "Reported pairing", exact: true }).selectOption("d-wave");
    await page.getByLabel("Only APS data", { exact: true }).check();
    await expect(page).toHaveURL(/\/materials$/);

    await page.getByRole("link", { name: "Clear filters", exact: true }).click();
    await expect(page.getByRole("searchbox", { name: "Formula contains", exact: true })).toHaveValue("");
    await expect(page.getByRole("button", { name: "All families", exact: true })).toBeVisible();
    await expect(page.getByLabel("Tc ≥ (K)", { exact: true })).toHaveValue("");
    await expect(page.getByLabel("Pressure ≤ (GPa)", { exact: true })).toHaveValue("");
    await expect(page.getByRole("combobox", { name: "Result origin", exact: true })).toHaveValue("");
    await expect(page.locator('select[name="pairing_symmetry"]')).toHaveValue("");
    await expect(page.getByLabel("Only APS data", { exact: true })).not.toBeChecked();
    await expect(page.locator('[name="experimental_only"]')).toHaveCount(0);
    await expect(page).toHaveURL(/\/materials$/);
  }
});
