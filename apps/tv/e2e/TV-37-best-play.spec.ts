// TV-37 the game's best play (GET /games/{id}/best-play): a ★ on the court line at its
// time, "★ Best play" on its moment card, and the Highlights reel ends on it under a
// "★ Best play of the game" banner. SYNTHETIC mock g_mock01 (20 s): makes at 3 s (Marcus),
// 14 s (Marcus) and 17 s (p3, unnamed); hype plays 0.5–4.5 s and 11.5–15.5 s. With no
// pick the last make (17 s) is in the final 30 s: the game winner, played from 13 s and
// joined with the 11.5–15.5 s play it overlaps. The phone's "Make this the best play" wins
// over that, and names come from the roster (set here as the phone's Names tab would).
import { expect, test, type Page } from "@playwright/test";
import { GAME_ID, menuTo, media, openWatch } from "./helpers";

const card = (page: Page, id: string) =>
  page.locator(`[data-testid="moment-card"][data-moment-id="${id}"]`);

type MockApi = {
  setBestPlay: (id: string, pick: Record<string, unknown>) => Promise<unknown>;
  patchPlayer: (id: string, pid: string, body: object) => Promise<unknown>;
};

test("TV-37 the game winner: ★ on the line, on its moment, and last in Highlights", async ({
  page,
}) => {
  await openWatch(page);
  const mark = page.getByTestId("best-play-mark");
  await expect(mark).toHaveAttribute("data-t", "17");
  await expect(mark).toHaveText("★");

  await page.keyboard.press("Space"); // pause: the row stays put
  await page.keyboard.press("ArrowDown");
  await expect(page.getByTestId("moments-layer")).toBeVisible();
  await expect(card(page, "e_0004")).toHaveAttribute("data-best", "true");
  await expect(card(page, "e_0004")).toContainText("★ Best play");
  await expect(page.getByTestId("moment-best")).toHaveCount(1);
  await expect(card(page, "e_0001")).toHaveAttribute("data-best", "false");
  await page.keyboard.press("Escape");

  await menuTo(page, "way-highlights");
  await expect(page.getByTestId("way-highlights")).toContainText("Top 2 plays");
  await page.keyboard.press("Enter");
  const ind = page.getByTestId("way-indicator");
  await expect(ind).toHaveText("Highlights · 1 of 2");
  await expect(page.getByTestId("best-play-card")).toHaveCount(0);
  await page.keyboard.press("]"); // the next play: the last, the best
  await expect(ind).toHaveText("Highlights · 2 of 2");
  const banner = page.getByTestId("best-play-card");
  await expect(banner).toBeVisible();
  await expect(banner).toHaveAttribute("data-source", "auto:last_make");
  await expect(banner).toContainText("★ Best play of the game");
  await expect(page.getByTestId("best-play-sub")).toHaveText("Game winner");
  await expect
    .poll(async () => (await media(page)).t)
    .toBeGreaterThanOrEqual(11.4);
  await page.screenshot({ path: test.info().outputPath("best-play.png") });
  // the reel ends after it: the full game, no banner
  await expect(ind).toHaveCount(0, { timeout: 12_000 });
  await expect(page.getByTestId("best-play-card")).toHaveCount(0);
});

test("TV-37 the phone's pick wins, even early in the game; names come from the roster", async ({
  page,
}) => {
  // as the phone does it: Names tab (p3 → "Cyd") and "Make this the best play" on the
  // 3 s basket; then Home → Highlights
  await page.goto("/tv/settings");
  await expect(page.getByTestId("settings")).toBeVisible();
  await page.evaluate(async (gid) => {
    const m = (window as unknown as { __replayMock: { api: MockApi } })
      .__replayMock.api;
    await m.patchPlayer(gid, "p3", { name: "Cyd" });
    await m.setBestPlay(gid, {
      t_start: 0.5,
      t_end: 4.5,
      t: 3,
      moment_id: "e_0001",
    });
  }, GAME_ID);
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("home")).toBeVisible();
  await page.keyboard.press("ArrowUp");
  await page.keyboard.press("ArrowRight");
  await expect(page.getByTestId("hero-highlights")).toHaveAttribute(
    "data-focused",
    "true",
  );
  await page.keyboard.press("Enter");

  // the 11.5–15.5 s play first, then the picked 0.5–4.5 s one: out of time order, last
  const ind = page.getByTestId("way-indicator");
  await expect(ind).toHaveText("Highlights · 1 of 2");
  await expect
    .poll(async () => (await media(page)).t, { timeout: 15_000 })
    .toBeGreaterThanOrEqual(11.4);
  await page.keyboard.press("]");
  await expect(ind).toHaveText("Highlights · 2 of 2");
  await expect.poll(async () => (await media(page)).t).toBeLessThan(5);
  const banner = page.getByTestId("best-play-card");
  await expect(banner).toHaveAttribute("data-source", "user");
  await expect(page.getByTestId("best-play-sub")).toHaveText("Basket, Marcus");

  await page.keyboard.press("Escape"); // out of the reel, into the full game
  await expect(page.getByTestId("watch")).toHaveAttribute("data-way", "full");
  await expect(page.getByTestId("best-play-mark")).toHaveAttribute(
    "data-t",
    "3",
  );
  await page.keyboard.press("Space");
  await page.keyboard.press("ArrowDown");
  await expect(card(page, "e_0001")).toHaveAttribute("data-best", "true");
  await expect(card(page, "e_0004")).toHaveAttribute("data-best", "false");
  // the label sits under the card, in its slot
  await expect(card(page, "e_0004").locator("xpath=..")).toContainText(
    "Basket, Cyd",
  );
});
