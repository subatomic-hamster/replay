import { expect, test } from "@playwright/test";
import { mockCalls } from "./helpers";

// S-02 create game, S-09 sport picker.
test("S-02/S-09 the form creates a game and lands on its upload page", async ({ page }) => {
  await page.goto("/upload");

  // S-09: only sports from GET /sports are offered.
  await expect(page.getByTestId("sport-option-basketball")).toBeVisible();
  await expect(page.getByTestId("sport-option-pickleball")).toBeVisible();
  await expect(page.locator('input[name="sport"]')).toHaveCount(2);

  await page.getByTestId("game-title-input").fill("Tuesday Run");
  await page.getByTestId("sport-option-basketball").check();
  await page.getByTestId("create-game").click();

  await expect.poll(() => new URL(page.url()).pathname).toMatch(/^\/upload\/g_[a-z0-9]+$/);

  const post = (await mockCalls(page)).filter((c) => c.method === "POST" && c.path === "/games");
  expect(post).toHaveLength(1);
  expect(post[0].body).toEqual({ title: "Tuesday Run", sport: "basketball" });
  // The create response's upload_url is carried forward in the query string.
  expect(new URL(page.url()).searchParams.get("upload")).toContain("/__mock_upload/");
});

test("S-02 the create button stays disabled without a title", async ({ page }) => {
  await page.goto("/upload");
  await expect(page.getByTestId("create-game")).toBeDisabled();
  await page.getByTestId("game-title-input").fill("x");
  await expect(page.getByTestId("create-game")).toBeEnabled();
});
