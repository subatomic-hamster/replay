// Do more's chip row (Player POV) runs on off the screen edge like Moments' filter
// chips, instead of being cut at the safe edge mid-label ("P6 Pla" at x 1836); the
// tile rows keep their safe-zone clip.
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
