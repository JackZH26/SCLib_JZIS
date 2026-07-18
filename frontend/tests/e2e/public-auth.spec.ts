import { expect, test } from "@playwright/test";

const internalHost = /(?:^|\/\/)(?:api(?::\d+)?|localhost|127\.0\.0\.1)(?:[/:]|$)/i;

test("production auth navigation exposes only public or same-origin links", async ({ page }) => {
  const requests: string[] = [];
  page.on("request", (request) => requests.push(request.url()));

  await page.goto("login");
  await expect(page.getByRole("heading", { name: "Sign in to JZIS" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Continue with Google" })).toHaveAttribute(
    "href",
    "https://api.jzis.org/sclib/v1/auth/google/login",
  );

  await page.getByRole("link", { name: "Forgot password?" }).click();
  await expect(page).toHaveURL(/\/sclib\/forgot-password$/);
  await expect(page.getByRole("heading", { name: "Reset your password" })).toBeVisible();

  await page.goto("register");
  const links = await page.locator("a[href]").evaluateAll((anchors) =>
    anchors.map((anchor) => anchor.getAttribute("href") ?? ""),
  );
  expect(links.filter((href) => internalHost.test(href))).toEqual([]);

  const forbiddenRequests = requests.filter((requestURL) => {
    const url = new URL(requestURL);
    return (
      url.hostname === "api" ||
      url.hostname === "localhost" ||
      (url.hostname === "127.0.0.1" && url.port !== "3102")
    );
  });
  expect(forbiddenRequests).toEqual([]);
});

test("password reset forms expose the expected accessible controls", async ({ page }) => {
  await page.goto("forgot-password");
  await expect(page.getByLabel("Email")).toBeVisible();
  await expect(page.getByRole("button", { name: "Send reset link" })).toBeEnabled();

  await page.goto("reset-password?token=abcdefghijklmnopqrstuvwxyz1234567890ABCD");
  await expect(page.getByLabel("New password", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Confirm new password", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Update password" })).toBeEnabled();
});
