import { expect, test } from "@playwright/test";

test("registration minimizes required personal data", async ({ page }) => {
  await page.goto("register");

  await expect(page.getByLabel(/age/i)).toHaveCount(0);
  await expect(page.getByLabel("Institution (optional)")).toHaveCount(0);
  const profileToggle = page.getByRole("checkbox", {
    name: "Add an optional research profile",
  });
  await expect(profileToggle).not.toBeChecked();
  await profileToggle.check();
  await expect(page.getByLabel("Institution (optional)")).toBeVisible();
  await expect(page.getByLabel("Purpose of use (optional)")).not.toHaveAttribute(
    "required",
  );
  const registration = page.getByRole("main");
  await expect(registration.getByRole("link", { name: "Terms" })).toHaveAttribute(
    "href",
    "/sclib/terms",
  );
  await expect(registration.getByRole("link", { name: "Privacy Policy" })).toHaveAttribute(
    "href",
    "/sclib/privacy",
  );
});

for (const route of ["privacy", "terms", "cookies"]) {
  test(`${route} policy is readable without mobile overflow`, async ({ page }) => {
    await page.goto(route);
    await expect(page.locator("article")).toBeVisible();
    const widths = await page.evaluate(() => ({
      viewport: window.innerWidth,
      document: document.documentElement.scrollWidth,
      article: document.querySelector("article")?.getBoundingClientRect().width ?? 0,
    }));
    expect(widths.viewport).toBe(390);
    expect(widths.document).toBeLessThanOrEqual(390);
    expect(widths.article).toBeGreaterThan(0);
    expect(widths.article).toBeLessThanOrEqual(390);
  });
}
