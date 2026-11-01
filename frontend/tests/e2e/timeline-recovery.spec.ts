import { expect, test } from "./public-site-fixture";

test("an unavailable NER timeline offers recovery without legacy substitution or a page crash", async ({ page }) => {
  await page.goto("/timeline");
  await expect(page.getByRole("heading", { name: "TcTimeline", exact: true })).toBeVisible();
  await expect(page.getByRole("main").getByRole("alert")).toContainText("TcTimeline could not be loaded");
  await page.getByRole("button", { name: "Open navigation", exact: true }).click();
  await expect(page.getByRole("navigation", { name: "Mobile navigation" }).getByRole("link", { name: "TcTimeline", exact: true })).toHaveAttribute("aria-current", "page");
  await expect(page.getByRole("navigation", { name: "Mobile navigation" }).getByRole("link", { name: "Discovery", exact: true })).not.toHaveAttribute("aria-current", "page");
  await page.getByRole("button", { name: "Close navigation", exact: true }).click();
  const retry=page.getByRole("button",{name:"Try again",exact:true});
  await expect(retry).toBeVisible();
  await retry.click();
  await expect(page.getByRole("main").getByRole("alert")).toBeVisible();
  await expect(page.getByRole("navigation",{name:"Discovery"})).toHaveCount(0);
  await expect(page.getByText(/Application error:/)).toHaveCount(0);
});
