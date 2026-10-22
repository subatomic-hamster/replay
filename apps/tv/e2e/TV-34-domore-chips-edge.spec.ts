// Player screen polish. Do more's chip row (Player POV) runs on off the screen edge like
// Moments' filter chips, instead of being cut at the safe edge mid-label ("P6 Pla" at
// x 1836); the tile rows keep their safe-zone clip. The game title does not show through
// Do more. An unknown game id shows the error banner, not a blank screen (the mock throws
// synchronously where the real API rejects).
import { expect, test } from "@playwright/test";
import { GAME_ID, menuTo, openWatch } from "./helpers";

test("TV-34 Do more chips are not cut at the safe edge; tiles are", async ({
  page,
}) => {
  await openWatch(page, GAME_ID, "?t=6");
  await menuTo(page, "action-pov");
  const clip = page.getByTestId("domore-clip");
  const tilesRight = await clip.evaluate(
    (el) => el.getBoundingClientRect().right,
  );
  expect(tilesRight).toBeLessThan(1920 - 96 + 24); // the safe zone (+ ring room)
  await page.keyboard.press("Enter"); // Player POV: the chips
  await expect(page.getByTestId("domore")).toHaveAttribute(
    "data-row",
    "action-pov",
  );
  await expect
    .poll(() => clip.evaluate((el) => el.getBoundingClientRect().right))
    .toBeGreaterThanOrEqual(1920);
});

test("TV-34 the title hides under Do more and comes back after", async ({
  page,
}) => {
  await openWatch(page, GAME_ID, "?t=6");
  const title = page.getByTestId("watch-title");
  const opacity = () =>
    title.evaluate((el) => {
      let o = 1;
      for (let e: Element | null = el; e; e = e.parentElement)
        o *= Number(getComputedStyle(e).opacity);
      return o;
    });
  await menuTo(page, "action-follow");
  await expect.poll(opacity).toBe(0);
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("domore")).toHaveCount(0);
  await expect.poll(opacity).toBeGreaterThan(0.5);
});

test("TV-34 an unknown game id shows the error banner", async ({ page }) => {
  await page.goto("/tv/g_nope404");
  await expect(page.getByTestId("api-error")).toBeVisible();
});
