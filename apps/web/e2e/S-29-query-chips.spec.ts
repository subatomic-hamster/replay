import { expect, test } from "@playwright/test";
import { GAME_ID, mockCalls } from "./helpers";

// S-29 query chips (deterministic), S-27 per-player reel, E-20 zero results.
test("S-29 a chip runs POST /query and builds a playlist", async ({ page }) => {
  await page.goto(`/tv/${GAME_ID}/highlights`);
  const chips = page.getByTestId("query-chip");
  await expect(chips).toHaveCount(4); // 1 per-player reel + 3 sport_ui chips
  expect(await chips.nth(0).textContent()).toContain("Marcus");

  // "Makes" is the third chip.
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowRight");
  await expect(chips.nth(2)).toHaveAttribute("data-focused", "true");
  await page.keyboard.press("Enter");

  await expect(page.getByTestId("query-interpretation")).toBeVisible();
  await expect(page.getByTestId("reel-clip")).toHaveCount(3);
  await expect(page.getByTestId("clip-counter")).toHaveText("clip 1/3");

  const calls = await mockCalls(page);
  const q = calls.filter((c) => c.path.endsWith("/query"));
  expect(q.length).toBe(1);
  expect(q[0].method).toBe("POST");
  expect(q[0].body).toEqual({ text: "Makes" });
});

test("S-29 the same chip twice returns an identical clip list", async ({ page }) => {
  await page.goto(`/tv/${GAME_ID}/highlights`);
  await expect(page.getByTestId("query-chip")).toHaveCount(4);
  const read = async () =>
    page.locator('[data-testid="reel-clip"]').evaluateAll((els) =>
      els.map((e) => `${e.getAttribute("data-event-id")}@${e.getAttribute("data-t-start")}`),
    );

  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("reel-clip")).toHaveCount(3);
  const first = await read();

  await page.keyboard.press("ArrowUp");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("reel-clip")).toHaveCount(3);
  expect(await read()).toEqual(first);
});

test("S-27 the per-player reel holds only that player's shots", async ({ page }) => {
  await page.goto(`/tv/${GAME_ID}/highlights`);
  await expect(page.getByTestId("query-chip")).toHaveCount(4);
  await page.keyboard.press("Enter"); // chip 0 — "Marcus — all shots"
  await expect(page.getByTestId("reel-clip")).toHaveCount(2);
  const ids = await page
    .locator('[data-testid="reel-clip"]')
    .evaluateAll((els) => els.map((e) => e.getAttribute("data-event-id")));
  expect(ids).toEqual(["e_0001", "e_0003"]);
  await expect(page.getByTestId("clip-counter")).toHaveText("clip 1/2");
});

test("E-20 a query with no matches shows the no-clips state", async ({ page }) => {
  // g_mock02 has no events at all.
  await page.goto("/tv/g_mock02/highlights");
  await expect(page.getByTestId("query-chip").first()).toBeVisible();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("no-clips")).toBeVisible();
  await expect(page.getByTestId("reel-clip")).toHaveCount(0);
});
