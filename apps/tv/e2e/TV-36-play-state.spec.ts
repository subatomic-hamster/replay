// TV-36 play state: the transport shows ❚❚ while playing and ▶ "Paused" while paused (and
// stays up paused); a toggle by Select or the Play/Pause key flashes the new state in the
// centre; the wide legend says what Select does. The Replay angles room shows the same
// state in its bug. PLAY_SHOTS=<dir> also saves review screenshots (PLAY_SHOTS_W=960 for
// the half-size check).
import { expect, test, type Page } from "@playwright/test";
import { GAME_ID, media, openWatch } from "./helpers";

const SHOTS = process.env.PLAY_SHOTS;
const W = Number(process.env.PLAY_SHOTS_W || 1920);
test.use({ viewport: { width: W, height: (W * 9) / 16 } });

const shot = async (page: Page, name: string) => {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}-${W}.png` });
};
const state = (page: Page) => page.getByTestId("playstate");
const flash = (page: Page) => page.getByTestId("play-flash");

test("TV-36 Watch: Select and Play/Pause flip the play state, with a centre flash", async ({
  page,
}) => {
  await openWatch(page);
  await expect.poll(async () => (await media(page)).paused).toBe(false);
  await expect(state(page)).toHaveAttribute("data-state", "playing");
  await shot(page, "watch-playing");

  await page.keyboard.press("Enter"); // Select pauses
  await expect(flash(page)).toHaveAttribute("data-state", "paused");
  await shot(page, "watch-flash-paused");
  await expect(state(page)).toHaveAttribute("data-state", "paused");
  await expect(state(page)).toContainText("Paused");
  await expect.poll(async () => (await media(page)).paused).toBe(true);
  await expect(flash(page)).toHaveCount(0); // a brief flash, not a badge
  // paused: the transport, its state and "Select Play" stay past the 5 s hide
  await page.waitForTimeout(6_000);
  await expect(page.getByTestId("transport")).toHaveAttribute(
    "data-hidden",
    "false",
  );
  await expect(state(page)).toHaveAttribute("data-state", "paused");
  await expect(page.getByTestId("legend-Select")).toHaveAttribute(
    "data-label",
    "Play",
  );
  await shot(page, "watch-paused");

  await page.keyboard.press(" "); // the Play/Pause key plays
  await expect(flash(page)).toHaveAttribute("data-state", "playing");
  await shot(page, "watch-flash-playing");
  await expect(state(page)).toHaveAttribute("data-state", "playing");
  await expect.poll(async () => (await media(page)).paused).toBe(false);
  await expect(page.getByTestId("legend-Select")).toHaveCount(0);

  await page.keyboard.press(" "); // and pauses
  await expect(flash(page)).toHaveAttribute("data-state", "paused");
  await expect(state(page)).toHaveAttribute("data-state", "paused");
  await expect.poll(async () => (await media(page)).paused).toBe(true);
});

test("TV-36 Replay angles: Select and Play/Pause flip the state in the bug, with the flash", async ({
  page,
}) => {
  await page.goto(`/tv/${GAME_ID}/replays/play_0001`);
  await expect
    .poll(async () => (await media(page)).ready, { timeout: 15_000 })
    .toBeGreaterThanOrEqual(2);
  await expect.poll(async () => (await media(page)).paused).toBe(false);
  const bugState = page.getByTestId("replay-bug").getByTestId("playstate");
  await expect(bugState).toHaveAttribute("data-state", "playing");
  await shot(page, "angles-playing");

  await page.keyboard.press("Enter");
  await expect(flash(page)).toHaveAttribute("data-state", "paused");
  await expect(bugState).toHaveAttribute("data-state", "paused");
  await expect(bugState).toContainText("Paused");
  await expect.poll(async () => (await media(page)).paused).toBe(true);
  await expect(flash(page)).toHaveCount(0);
  await shot(page, "angles-paused");

  await page.keyboard.press(" ");
  await expect(flash(page)).toHaveAttribute("data-state", "playing");
  await expect(bugState).toHaveAttribute("data-state", "playing");
  await expect.poll(async () => (await media(page)).paused).toBe(false);
});
