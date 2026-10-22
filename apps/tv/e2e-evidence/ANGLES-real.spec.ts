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

/** Right through the room's cuts until `want` holds for the replay's dataset, at most
 *  one lap; false when the play has no such cut. */
async function cutTo(
  page: Page,
  want: (angle: string, pov: string) => boolean,
): Promise<boolean> {
  const cuts = Number(await replay(page).getAttribute("data-cuts"));
  for (let i = 0; i <= cuts; i++) {
    const angle = (await replay(page).getAttribute("data-angle")) ?? "";
    const pov = (await replay(page).getAttribute("data-pov")) ?? "";
    if (want(angle, pov)) return true;
    await page.keyboard.press("ArrowRight");
    await page.waitForTimeout(300);
  }
  return false;
}

test.describe.configure({ mode: "serial" });

test("ANGLES real game: the room, a recreated cut, Player's view, Up, Free view", async ({
  page,
}) => {
  test.setTimeout(180_000);
  const play = await firstPlay(page);
  await openWatch(page, GAME, `?t=${play.t_start + 1}`);
  await page.keyboard.press("Space");
  await expect.poll(async () => (await media(page)).paused).toBe(true);

  // Do more → Replay angles opens the room on the nearest play's first cut
  await menuTo(page, "nav-replays");
  await page.keyboard.press("Enter");
  await expect(replay(page)).toBeVisible();
  expect(Number(await replay(page).getAttribute("data-cuts"))).toBeGreaterThan(
    3,
  );
  await shot(page, "01-angles-room");

  expect(await cutTo(page, (a) => a === "broadcast_high")).toBe(true);
  await expect(page.getByTestId("replay-tier-badge")).toHaveText(
    "Virtual replay",
  );
  await expect
    .poll(async () => (await media(page)).ready, { timeout: 30_000 })
    .toBeGreaterThanOrEqual(2);
  await page.keyboard.press("Enter"); // pause on a frame
  await shot(page, "02-tierB-broadcast-high");

  // a virtual view (Tier C, image-based): the wing camera, when the play has one
  if (await cutTo(page, (a) => a === "3d:wing")) {
    await expect(replay(page)).toHaveAttribute("data-tier", "C");
    await expect(page.getByTestId("replay-tier-badge")).toHaveText(
      "Virtual replay",
    );
    await expect
      .poll(async () => (await media(page)).ready, { timeout: 30_000 })
      .toBeGreaterThanOrEqual(2);
    await page.waitForTimeout(1500);
    await shot(page, "02b-virtual-wing");
  }

  // Player's view: one cut in the room (the key player's), Up for another player's eyes
  expect(await cutTo(page, (_a, pov) => pov !== "")).toBe(true);
  await expect(page.getByTestId("replay-angle-label")).toContainText(
    "Player's view",
  );
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
