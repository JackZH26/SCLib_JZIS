import { expect, test } from "@playwright/test";

const routes = [
  "login",
  "register",
  "forgot-password",
  "reset-password?token=abcdefghijklmnopqrstuvwxyz1234567890ABCD",
];

for (const route of routes) {
  test(`${route.split("?")[0]} stays inside the 390px mobile viewport`, async ({ page }) => {
    await page.goto(route);
    await expect(page.locator("main")).toBeVisible();

    const layout = await page.evaluate(() => ({
      viewport: window.innerWidth,
      documentWidth: document.documentElement.scrollWidth,
      controls: Array.from(
        document.querySelectorAll<HTMLElement>("input, textarea, button, main a"),
      ).map((element) => {
        const box = element.getBoundingClientRect();
        return { left: box.left, right: box.right, width: box.width };
      }),
    }));

    expect(layout.viewport).toBe(390);
    expect(layout.documentWidth).toBeLessThanOrEqual(layout.viewport);
    for (const control of layout.controls) {
      expect(control.left).toBeGreaterThanOrEqual(-1);
      expect(control.right).toBeLessThanOrEqual(layout.viewport + 1);
      expect(control.width).toBeGreaterThan(0);
    }
  });
}

test("mobile header opens an accessible navigation menu", async ({ page }) => {
  await page.goto("login");
  await page.getByRole("button", { name: "Open navigation" }).click();

  await expect(page.getByRole("link", { name: "Search" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Discovery" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Account", exact: true })).toBeVisible();
});
