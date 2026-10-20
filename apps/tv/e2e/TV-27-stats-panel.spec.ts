// Do more → Stats: an X-Ray-like panel on the right third while the game keeps playing on
// the left: the score, a short box score and the shot chart (auto-detected, D-48), and the
// way on to the review queue and the tips. Back closes it.
import { expect, test } from "@playwright/test";
import { GAME_ID, media, menuTo, openWatch, smallText } from "./helpers";

test("TV-27 Stats panel: right third, video plays on, box score and shots, review queue", async ({
  page,
}) => {
  await openWatch(page, GAME_ID, "?t=2");
  await expect.poll(async () => (await media(page)).paused).toBe(false);
  await menuTo(page, "nav-review");
  await expect(page.getByTestId("nav-review")).toContainText("Stats");
  await page.keyboard.press("Enter");

  const panel = page.getByTestId("stats-panel");
  await expect(panel).toBeVisible();
  await expect(page.getByTestId("watch")).toHaveAttribute(
    "data-layer",
    "stats",
  );
  const b = (await panel.boundingBox())!;
  expect(b.x + b.width).toBeCloseTo(1920, 0);
  expect(b.width).toBeGreaterThan(1920 / 4);
  expect(b.width).toBeLessThan(1920 / 2.5);
  expect(b.height).toBeCloseTo(1080, 0);
  // The transport steps aside; the game goes on.
  await expect(page.getByTestId("transport")).toHaveAttribute(
    "data-hidden",
    "true",
  );
  const t0 = (await media(page)).t;
  await expect
    .poll(async () => (await media(page)).t, { timeout: 5_000 })
    .toBeGreaterThan(t0 + 0.5);

  await expect(page.getByTestId("auto-detected-label")).toContainText(
    "Auto-detected",
  );
  await expect(page.getByTestId("stats-score")).toBeVisible();
  await expect(page.getByTestId("box-score-row")).toHaveCount(4);
  await expect(page.getByTestId("box-score-row").first()).toContainText(
    "Marcus",
  );
  await expect(page.getByTestId("shot-chart")).toBeVisible();
  await expect(page.getByTestId("shot-marker")).toHaveCount(4);
  // everything inside the panel and the bottom safe edge
  for (const id of ["shot-chart", "stats-review", "stats-advice"]) {
    const x = (await page.getByTestId(id).boundingBox())!;
    expect(x.x, id).toBeGreaterThanOrEqual(b.x);
    expect(x.x + x.width, id).toBeLessThanOrEqual(1920 - 96 + 1);
    expect(x.y + x.height, id).toBeLessThanOrEqual(1080 - 54 + 1);
  }
  expect(await smallText(page)).toEqual([]);

  // Back closes the panel; the transport is back.
  await page.keyboard.press("Escape");
  await expect(panel).toHaveCount(0);
  await expect(page.getByTestId("transport")).toHaveAttribute(
    "data-hidden",
    "false",
  );

  // The review queue: Select on "Review N plays" opens the Review screen.
  await menuTo(page, "nav-review");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("stats-review")).toHaveAttribute(
    "data-focused",
    "true",
  );
  await expect(page.getByTestId("stats-review")).toContainText(
    /Review \d+ plays?/,
  );
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("review-item")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("watch")).toBeVisible();
});
