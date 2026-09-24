import { expect, test } from "./public-site-fixture";

test("an unavailable timeline keeps filters and offers a document retry without crashing", async ({ page }) => {
  // The owned production test server uses an unreachable inert API, never the live service.
  const query = "family=iron_based&experimental_only=true&only_aps=true&display=expanded";
  await page.goto(`/timeline?${query}`);
  await expect(page.getByRole("heading", { name: "Reported Tc Timeline", exact: true })).toBeVisible();
  await expect(page.getByRole("main").getByRole("alert")).toContainText("Timeline data could not be loaded completely");
  await expect(page.getByText("No eligible reported Tc results match this filter.")).toHaveCount(0);
  const retry = page.getByRole("link", { name: "Retry timeline", exact: true });
  await expect(retry).toHaveAttribute("href", `/timeline?${query}`);
  await retry.click();
  await expect(page).toHaveURL(new RegExp("/timeline\\?" + query + "$"));
  await expect(page.getByRole("main").getByRole("alert")).toBeVisible();
  await expect(page.getByRole("link", { name: "Up to 10,000 results" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByText(/Application error:/)).toHaveCount(0);
});
