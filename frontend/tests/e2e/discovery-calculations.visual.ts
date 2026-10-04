/** Browser downloads against captured synthetic HTTP; no production or solver execution. */
import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import { expect, test, type Page } from "@playwright/test";
import { DESIGN_AUTHORITY } from "../../lib/discovery-designs";
import wire from "../fixtures/discovery-calculations-native.synthetic.json";

async function syntheticOnly(page: Page, baseURL: string) {
  const state = { unexpected: [] as string[], downloaded: [] as number[] };
  const origin = new URL(baseURL).origin, api = "/__synthetic_api/v1";
  const designs = api + "/research/discovery-designs", calculations = api + "/research/discovery-calculations";
  await page.context().route("**/*", async route => {
    const request = route.request(), url = new URL(request.url());
    if (url.origin !== origin) { state.unexpected.push(url.origin); return route.abort("blockedbyclient"); }
    if (!url.pathname.startsWith("/__synthetic_api/")) return route.continue();
    expect(request.method()).toBe("GET");
    const fulfill = (value: unknown, status = 200) => route.fulfill({ status, contentType: "application/json",
      headers: { "cache-control": "private, no-store" }, body: JSON.stringify(value) });
    if (url.pathname === api + "/auth/me") return fulfill({
      id: wire.design_capabilities.actor_user_id, email: "curator@example.invalid", email_verified: true,
      name: "Synthetic Curator", institution: null, country: null, age: null, research_area: null,
      purpose: null, bio: null, orcid: null, created_at: "2026-09-01T00:00:00Z", is_active: true,
      is_admin: false, is_reviewer: false, auth_provider: "local", avatar_url: null, scopes: [],
    });
    if (url.pathname === designs + "/capabilities") return fulfill(wire.design_capabilities);
    if (url.pathname === designs + "/designs") return fulfill({ ...DESIGN_AUTHORITY,
      version: wire.parent.version, actor_user_id: wire.parent.actor_user_id,
      session_version: wire.parent.session_version, offset: 0, limit: 8, total: 1, entries: wire.parent.entries });
    if (url.pathname === designs + "/designs/" + wire.parent.design_id) return fulfill(wire.parent);
    if (url.pathname === api + "/research/discovery-condition-batches/capabilities") return fulfill({ detail: "Synthetic batch scope disabled" }, 404);
    if (url.pathname === calculations + "/capabilities") return fulfill(wire.capabilities);
    if (url.pathname === calculations + "/designs/" + wire.parent.design_id + "/context") return fulfill(wire.context);
    if (url.pathname === calculations + "/designs/" + wire.parent.design_id + "/returns") return fulfill(wire.page);
    const saved = calculations + "/returns/" + wire.commit.receipt_id;
    if (url.pathname === saved) return fulfill(wire.detail);
    for (let i = 0; i < wire.upload.request.files.length; i++) {
      if (url.pathname !== saved + "/files/" + i) continue;
      state.downloaded.push(i);
      return route.fulfill({ status: 200, contentType: "application/octet-stream",
        headers: { "cache-control": "private, no-store" }, body: Buffer.from(wire.upload.files_base64[i], "base64") });
    }
    state.unexpected.push(url.pathname); return fulfill({ detail: "No synthetic fixture available" }, 503);
  });
  return state;
}

for (const viewport of [{ name: "desktop", width: 1280, height: 1000 }, { name: "mobile", width: 320, height: 844 }]) {
  test(`${viewport.name}: saved calculation originals download with exact bytes`, async ({ page, baseURL }, info) => {
    await page.setViewportSize(viewport);
    const state = await syntheticOnly(page, baseURL!), errors: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.goto("/dashboard/research/discovery-designs");
    const reject = page.getByRole("button", { name: /Reject optional|Reject all|Reject/i });
    if (await reject.count()) await reject.first().click();
    await page.getByRole("button", { name: "Load saved designs", exact: true }).click();
    await page.getByRole("button", { name: "Inspect history", exact: true }).click();
    await page.getByRole("button", { name: "Load calculation history", exact: true }).click();
    await page.getByRole("button", { name: "Inspect return", exact: true }).click();
    await expect(page.getByText("Research question: " + wire.parent.entries[0].design.next_action.question, { exact: true })).toBeVisible();
    const detail = page.getByRole("region", { name: "Saved calculation detail", exact: true });
    await expect(detail).toBeVisible();
    const evidence = [];
    for (const [i, file] of wire.upload.request.files.entries()) {
      const label = file.role === "upf" ? file.name : file.role;
      await detail.getByRole("button", { name: "Prepare download " + label, exact: true }).click();
      const link = detail.getByRole("link", { name: "Save verified " + label, exact: true });
      await expect(link).toHaveAttribute("download", file.name);
      const pending = page.waitForEvent("download");
      await link.click();
      const download = await pending;
      expect(download.suggestedFilename()).toBe(file.name);
      const destination = info.outputPath(file.name);
      await download.saveAs(destination);
      expect(await download.failure()).toBeNull();
      const bytes = await readFile(destination), sha256 = createHash("sha256").update(bytes).digest("hex");
      expect(bytes.equals(Buffer.from(wire.upload.files_base64[i], "base64"))).toBe(true);
      expect(bytes.length).toBe(file.size_bytes); expect(sha256).toBe(file.sha256);
      evidence.push({ name: file.name, size_bytes: bytes.length, sha256 });
    }
    await expect(page.locator("html")).toHaveJSProperty("scrollWidth", viewport.width);
    await detail.scrollIntoViewIfNeeded();
    await page.screenshot({ path: info.outputPath(viewport.name + "-calculation-download.png") });
    await writeFile(info.outputPath("verified-downloads.json"), JSON.stringify({ syntheticTransport: true, solverExecuted: false, files: evidence }, null, 2));
    await page.getByRole("button", { name: "Refresh calculation access", exact: true }).click();
    await expect(page.getByRole("link", { name: /^Save verified/ })).toHaveCount(0);
    expect(state.downloaded).toEqual([0, 1, 2, 3, 4]);
    expect(state.unexpected).toEqual([]); expect(errors).toEqual([]);
  });
}
