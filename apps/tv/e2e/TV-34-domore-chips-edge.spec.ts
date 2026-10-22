// Player screen polish. Do more's one sub-row left (Highlights' ways) keeps to the
// safe-zone clip; the context chip does not show through Do more. An unknown game id shows
// the error banner, not a blank screen (the mock throws synchronously where the real API
// rejects).
import { expect, test } from "@playwright/test";
import { GAME_ID, menuTo, openWatch } from "./helpers";

test("TV-34 the Highlights row keeps to the safe zone", async ({ page }) => {
  await openWatch(page, GAME_ID, "?t=6");
  await menuTo(page, "way-full");
  await expect(page.getByTestId("domore")).toHaveAttribute(
    "data-row",
    "menu-watch",
  );
  const clip = page.getByTestId("domore-clip");
  expect(
    await clip.evaluate((el) => el.getBoundingClientRect().right),
  ).toBeLessThan(1920 - 96 + 24); // the safe zone (+ ring room)
  const ways = page.locator('[data-testid="domore"] [data-testid^="way-"]');
  expect(await ways.count()).toBeGreaterThanOrEqual(2);
  for (const w of await ways.all()) {
    const b = (await w.boundingBox())!;
    expect(b.x).toBeGreaterThanOrEqual(96 - 12);
    expect(b.x + b.width).toBeLessThanOrEqual(1920 - 96 + 12);
  }
});

test("TV-34 the context chip hides under Do more and comes back after", async ({
  page,
}) => {
  await openWatch(page, GAME_ID, "?t=6");
  const title = page.getByTestId("context-chip");
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
