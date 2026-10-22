// Angles / Player POV / Free view evidence: the RN TV app (web build) against a running
// services/api (REPLAY_TV_API=<base>) serving a game the worker processed with the default
// opt-in stages (replays, scene, tierc_manifest: real pipeline output). Every step is a
// remote key; a 1080p screenshot per step goes to REPLAY_TV_EVIDENCE_DIR. Assertions are
// structural: the pipeline decides which plays, angles and players there are.
//
//   REPLAY_TV_EVIDENCE_GAME  the processed game (e.g. the CC BY g_c8b6186280ac, local only)
import { expect, test, type Page } from "@playwright/test";
import path from "node:path";
import { media, menuTo, openWatch } from "../e2e/helpers";

const API = process.env.REPLAY_TV_API ?? "mock";
const OUT =
  process.env.REPLAY_TV_EVIDENCE_DIR ?? "test-results/evidence-angles";
const GAME = process.env.REPLAY_TV_EVIDENCE_GAME ?? "g_mock01";
const replay = (page: Page) => page.getByTestId("replay");

async function shot(page: Page, name: string) {
  await page.waitForTimeout(700);
  await page.screenshot({ path: path.join(OUT, `${name}.png`) });
}

/** The first play with angles (GET /games/{id}/replays), straight from the API. */
async function firstPlay(
  page: Page,
): Promise<{ play_id: string; t_start: number }> {
  if (API === "mock") return { play_id: "play_0001", t_start: 0 };
  const res = await page.request.get(`${API}/games/${GAME}/replays`);
  const { replays } = await res.json();
  expect(replays.length).toBeGreaterThan(0);
  return replays[0];
}

test.describe.configure({ mode: "serial" });

test("ANGLES real game: Angles row, a Tier B cut, Player POV, Up, Free view", async ({
  page,
}) => {
  test.setTimeout(180_000);
  const play = await firstPlay(page);
  await openWatch(page, GAME, `?t=${play.t_start + 1}`);
  await page.keyboard.press("Space");
  await expect.poll(async () => (await media(page)).paused).toBe(true);

  await menuTo(page, "nav-replays");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("domore")).toHaveAttribute(
    "data-row",
    "nav-replays",
  );
  const thumbs = page.locator('[data-testid="domore"] [data-testid^="angle-"]');
  expect(await thumbs.count()).toBeGreaterThan(3);
  await shot(page, "01-angles-row");

  await menuTo(page, "angle-broadcast_high");
  await page.keyboard.press("Enter");
  await expect(replay(page)).toHaveAttribute("data-angle", "broadcast_high");
  await expect
    .poll(async () => (await media(page)).ready, { timeout: 30_000 })
    .toBeGreaterThanOrEqual(2);
  await page.keyboard.press("Enter"); // pause on a frame
  await shot(page, "02-tierB-broadcast-high");
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("watch")).toBeVisible();

  // Player POV: the key player's chip first, then another player's eyes with Up
  await menuTo(page, "action-pov");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("domore")).toHaveAttribute(
    "data-row",
    "action-pov",
  );
  await shot(page, "03-player-pov-chips");
  await page.keyboard.press("Enter");
  await expect(replay(page)).toHaveAttribute("data-tier", "C");
  const first = await replay(page).getAttribute("data-pov");
  expect(first).toBeTruthy();
  await expect(page.getByTestId("pov-honesty")).toBeVisible();
  await expect
    .poll(async () => (await media(page)).ready, { timeout: 30_000 })
    .toBeGreaterThanOrEqual(2);
  await page.waitForTimeout(1500);
  await shot(page, "04-virtual-pov-key-player");
  await page.keyboard.press("ArrowUp");
  await expect(replay(page)).not.toHaveAttribute("data-pov", first ?? "");
  await expect
    .poll(async () => (await media(page)).ready, { timeout: 30_000 })
    .toBeGreaterThanOrEqual(2);
  await page.waitForTimeout(1500);
  await shot(page, "05-virtual-pov-next-player");

  // Free view from the angle (Down), then a preset
  await page.keyboard.press("ArrowDown");
  await expect(replay(page)).toHaveAttribute("data-mode", "free");
  await expect(page.getByTestId("free-view")).toHaveAttribute(
    "data-ready",
    "true",
    {
      timeout: 30_000,
    },
  );
  await shot(page, "06-free-view-real");
  await page.keyboard.press("ArrowLeft");
  await page.keyboard.press("ArrowLeft");
  await page.keyboard.press("ArrowUp");
  await shot(page, "07-free-view-orbited");
  await page.keyboard.press("Escape");
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("watch")).toBeVisible();

  // Moments → Down on a moment in the play
  await page.keyboard.press("ArrowDown");
  await expect(page.getByTestId("moments-layer")).toBeVisible();
  const card = page.locator('[data-testid="moment-card"][data-angles="true"]');
  if (await card.count()) {
    for (let i = 0; i < 40; i++) {
      const on = page.locator(
        '[data-testid="moment-card"][data-focused="true"]',
      );
      if ((await on.getAttribute("data-angles")) === "true") break;
      await page.keyboard.press("ArrowRight");
    }
    await shot(page, "08-moment-with-angles");
    await page.keyboard.press("ArrowDown");
    await expect(replay(page)).toBeVisible();
    await shot(page, "09-moment-angles-open");
  }
});
