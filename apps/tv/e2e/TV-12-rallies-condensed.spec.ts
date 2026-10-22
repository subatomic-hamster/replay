// The Rallies screen folded into the player's Condensed way to watch (D-46). Mock fixture:
// g_pickle4 has three rallies (1–6, 8–16.5, 17–19.5 s) and no condensed render until it
// is asked for; g_mock01 has none, so it offers no Condensed (data-driven, never a
// sport-name branch).
import { expect, test } from "@playwright/test";
import { media, menuTo, mockCalls, openWatch } from "./helpers";

test("TV-12 Condensed is offered only for a game with rallies", async ({
  page,
}) => {
  await openWatch(page);
  await menuTo(page, "menu-watch");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("way-full")).toBeAttached();
  await expect(page.getByTestId("way-condensed")).toHaveCount(0);

  await openWatch(page, "g_pickle4");
  await menuTo(page, "way-condensed");
  await expect(page.getByTestId("way-condensed")).toContainText("3 rallies");
});

test("TV-12 while it renders, Condensed plays the rallies back to back and asks for the render", async ({
  page,
}) => {
  await page.goto("/tv/g_pickle4/rallies"); // the old route opens the player in this way
  const ind = page.getByTestId("way-indicator");
  await expect(ind).toHaveText("Condensed · 1 of 3");
  await expect(page.getByTestId("watch")).toHaveAttribute(
    "data-way",
    "condensed",
  );
  await expect
    .poll(async () =>
      (await mockCalls(page)).some(
        (c) => c.method === "POST" && c.path === "/games/g_pickle4/condensed",
      ),
    )
    .toBe(true);
  await expect
    .poll(async () => (await media(page)).t, { timeout: 15_000 })
    .toBeGreaterThan(1);
  // r1 ends at 6 s; the reel cuts straight to r2 at 8 s.
  await expect(ind).toHaveText("Condensed · 2 of 3", { timeout: 10_000 });
  expect((await media(page)).t).toBeGreaterThanOrEqual(7.9);
  // Next skips to the following rally.
  await page.keyboard.press("]");
  await expect(ind).toHaveText("Condensed · 3 of 3");
  await expect
    .poll(async () => (await media(page)).t)
    .toBeGreaterThanOrEqual(17);
});

test("TV-12 once rendered, Condensed plays the condensed video with the rally counter in sync", async ({
  page,
}) => {
  await page.goto("/tv/g_pickle4/rallies"); // asks for the render (the mock finishes in 0.6 s)
  await expect(page.getByTestId("way-indicator")).toHaveText(
    "Condensed · 1 of 3",
  );
  await page.waitForTimeout(800);

  await menuTo(page, "way-condensed");
  await page.keyboard.press("Enter");
  await expect
    .poll(async () => (await media(page)).src)
    .toContain("rendition=condensed");
  await expect(page.getByTestId("way-indicator")).toHaveText(
    "Condensed · rally 1 of 3",
  );
  // r2 starts 6.5 s into the condensed video; no stop between rallies.
  await expect(page.getByTestId("way-indicator")).toHaveText(
    "Condensed · rally 2 of 3",
    { timeout: 15_000 },
  );
  await expect.poll(async () => (await media(page)).paused).toBe(false);

  // Full game again: back on the wide shot, at the same point of the rally in game time.
  await menuTo(page, "way-full");
  await page.keyboard.press("Enter");
  await expect
    .poll(async () => (await media(page)).src)
    .toMatch(/\/mock\/wide\.mp4$/);
  await expect(page.getByTestId("way-indicator")).toHaveCount(0);
  await expect.poll(async () => (await media(page)).t).toBeGreaterThan(8);
});
