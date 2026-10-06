// M3 evidence: the RN TV app (web build) on a processed game from a running services/api.
// Opens the first ready game in the library and walks library → watch → select → follow →
// back, then tagging, highlights and review, saving a 1080p screenshot per step to
// REPLAY_TV_EVIDENCE_DIR. Assertions are structural (the real pipeline decides how many
// players and events there are); the screenshots are the evidence.
import { expect, test, type Page } from "@playwright/test";
import path from "node:path";
import { menuTo } from "../e2e/helpers";

const OUT = process.env.REPLAY_TV_EVIDENCE_DIR ?? "test-results/evidence";
const SEEK_TO = Number(process.env.REPLAY_TV_EVIDENCE_T ?? "4");

async function shot(page: Page, name: string) {
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(OUT, `${name}.png`) });
}

async function videoState(page: Page) {
  return page.evaluate(() => {
    const v = document.querySelector<HTMLVideoElement>('[data-testid="video"]');
    return v ? { t: v.currentTime, paused: v.paused, ready: v.readyState } : null;
  });
}

test("M3 walkthrough", async ({ page }) => {
  test.setTimeout(120_000);
  await page.goto("/");
  const ready = page.locator('[data-testid="game-card"]', {
    has: page.locator('[data-testid="game-status"]', { hasText: "ready" }),
  });
  await expect(ready.first()).toBeVisible({ timeout: 20_000 });
  const cards = page.getByTestId("game-card");
  const index = await cards.evaluateAll(
    (els) => els.findIndex((el) => el.textContent?.includes("ready")),
  );
  for (let i = 0; i < index; i++) await page.keyboard.press("ArrowRight");
  await shot(page, "01-library");

  await page.keyboard.press("Enter");
  await expect.poll(async () => (await videoState(page))?.ready ?? 0, { timeout: 30_000 }).toBeGreaterThanOrEqual(2);
  // Select plays; seek into the action (Right scrubs 5 s).
  await page.keyboard.press("Enter");
  await expect.poll(async () => (await videoState(page))?.paused).toBe(false);
  for (let i = 0; i < Math.round(SEEK_TO / 5); i++) await page.keyboard.press("ArrowRight");
  await page.waitForTimeout(1200);
  await shot(page, "02-watch-wide");

  // Select again: pause → select mode with boxes on the players.
  await page.keyboard.press("Enter");
  await expect(page.locator('[data-testid^="select-box-"]').first()).toBeVisible({ timeout: 10_000 });
  await page.keyboard.press("ArrowRight");
  await shot(page, "03-select");

  const focused = await page
    .locator('[data-testid^="select-box-"][data-focused="true"]')
    .getAttribute("data-player-id");
  expect(focused).toBeTruthy();

  // Follow the focused player, play a moment so the crop path moves.
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("followcam-active")).toBeVisible();
  await page.keyboard.press("Enter");
  await page.waitForTimeout(1500);
  await page.keyboard.press("Enter");
  await shot(page, "04-follow");

  // Spotlight via the action menu (Up → Playback ▸ → Spotlight).
  await menuTo(page, "action-spotlight");
  await page.keyboard.press("Enter");
  await shot(page, "05-follow-spotlight");
  await page.keyboard.press("s");

  // Back to wide: the amber follow frame stays on the player.
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("followcam-active")).toHaveCount(0);
  await shot(page, "06-back-to-wide");

  // Tagging the last focused player (the `t` shortcut = action row → Tag player).
  await page.keyboard.press("t");
  await expect(page.getByTestId("tag-dialog")).toBeVisible();
  await shot(page, "07-tag-dialog");
  await page.keyboard.press("Escape");

  // Highlights and Review via the action menu ("Game ▸" group).
  await menuTo(page, "nav-highlights");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("query-chip").first()).toBeVisible();
  await page.keyboard.press("Enter");
  await page.waitForTimeout(1500);
  await shot(page, "08-highlights");

  await page.keyboard.press("Escape");
  await expect(page.getByTestId("video")).toBeAttached();
  await menuTo(page, "nav-review");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("auto-detected-label")).toBeVisible();
  await page.waitForTimeout(1000);
  await shot(page, "09-review");
});
