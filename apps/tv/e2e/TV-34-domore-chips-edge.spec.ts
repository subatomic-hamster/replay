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

test("TV-34 an unknown game id says it is gone, not that Replay can't connect", async ({
  page,
}) => {
  await page.goto("/tv/g_nope404");
  const banner = page.getByTestId("api-error");
  await expect(banner).toBeVisible();
  await expect(banner).toHaveAttribute("data-kind", "not-found");
  await expect(page.getByTestId("api-error-title")).toHaveText(
    "This game isn't here any more",
  );
  await expect(banner).not.toContainText(/can't connect|internet|Settings/);
  await expect(page.getByTestId("api-error-retry")).toHaveCount(0);
  await expect(page.getByTestId("api-error-home")).toHaveAttribute(
    "data-focused",
    "true",
  );
  await page.keyboard.press("Enter"); // Back to Home
  await expect(page.getByTestId("home")).toBeVisible();

  // a game screen off a missing game (Clips) says the same; Back goes Home too
  await page.goto("/tv/g_nope404/clips");
  await expect(page.getByTestId("api-error-title")).toHaveText(
    "This game isn't here any more",
  );
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("home")).toBeVisible();
});

test("TV-34 a network failure still says Replay can't connect", async ({
  page,
}) => {
  await page.goto("/tv/settings");
  await expect(page.getByTestId("settings")).toBeVisible();
  await page.evaluate(() => {
    const m = (
      window as unknown as {
        __replayMock: { api: { getGame: () => Promise<unknown> } };
      }
    ).__replayMock.api;
    m.getGame = () => Promise.reject(new Error("Network request failed"));
  });
  await page.keyboard.press("Escape"); // Home
  await expect(page.getByTestId("home")).toBeVisible();
  await page.keyboard.press("Enter"); // open the focused game
  await expect(page.getByTestId("api-error-title")).toHaveText(
    "Replay can't connect",
  );
  await expect(page.getByTestId("api-error-retry")).toBeVisible();
});
