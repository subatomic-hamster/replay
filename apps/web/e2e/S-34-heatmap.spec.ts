import { expect, test } from "@playwright/test";
import { GAME_ID } from "./helpers";

// S-34 / R2 position heatmap on the Review screen.
test("S-34 the heatmap cells are monotonic in the stats grid values", async ({ page }) => {
  await page.goto(`/tv/${GAME_ID}/review`);
  const heat = page.getByTestId("heatmap");
  await expect(heat).toBeVisible();
  await expect(heat).toHaveAttribute("data-player-id", "p1");

  const cells = await page
    .locator('[data-testid="heatmap-cell"]')
    .evaluateAll((els) =>
      els.map((e) => ({
        value: Number(e.getAttribute("data-value")),
        opacity: Number(getComputedStyle(e).fillOpacity),
      })),
    );
  expect(cells.length).toBeGreaterThan(0);
  // higher value => visually denser cell, and the hottest cell is fully opaque
  const byValue = [...cells].sort((a, b) => a.value - b.value);
  for (let i = 1; i < byValue.length; i++) {
    expect(byValue[i].opacity).toBeGreaterThanOrEqual(byValue[i - 1].opacity - 1e-6);
  }
  expect(Math.max(...cells.map((c) => c.opacity))).toBeCloseTo(1, 2);
});

test("S-34 the D-pad player row switches the heatmap without a reload", async ({ page }) => {
  await page.goto(`/tv/${GAME_ID}/review`);
  await expect(page.getByTestId("heatmap")).toHaveAttribute("data-player-id", "p1");
  const before = await page.locator('[data-testid="heatmap-cell"]').count();

  await page.keyboard.press("ArrowDown"); // focus the player row
  await expect(page.getByTestId("heatmap-player-p1")).toHaveAttribute("data-focused", "true");
  await page.keyboard.press("ArrowRight");
  await expect(page.getByTestId("heatmap-player-p2")).toHaveAttribute("data-focused", "true");
  await expect(page.getByTestId("heatmap")).toHaveAttribute("data-player-id", "p2");
  expect(await page.locator('[data-testid="heatmap-cell"]').count()).toBeGreaterThan(0);
  expect(before).toBeGreaterThan(0);

  // Back up to the review answers: the queue is still driveable (NF-03).
  await page.keyboard.press("ArrowUp");
  // (the 0.55 shot is a GET /review/queue low-confidence question: Yes / No)
  await expect(page.getByTestId("review-action-yes")).toHaveAttribute("data-focused", "true");
});
