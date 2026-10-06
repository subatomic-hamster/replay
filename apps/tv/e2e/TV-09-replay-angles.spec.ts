// M8 multi-angle replay: Left/Right cut between time-aligned angle videos, keeping the
// playback position and play state; Back walks Replay → list → Watch. The mock serves
// every angle as /mock/wide.mp4?angle=<id>, so each cut is a real src swap + reload.
import { expect, test, type Page } from "@playwright/test";
import { cycleAngle, tierBadge } from "../../../packages/tv-core/src/replays";
import { GAME_ID, menuTo, openWatch } from "./helpers";

const REPLAY = `/tv/${GAME_ID}/replays/play_0001`;

async function media(page: Page) {
  return page.evaluate(() => {
    const v = document.querySelector<HTMLVideoElement>('[data-testid="video"]');
    return v
      ? { t: v.currentTime, paused: v.paused, src: v.currentSrc, ready: v.readyState }
      : { t: -1, paused: true, src: "", ready: 0 };
  });
}

async function expectAngle(page: Page, label: string, badge: string, pos: string) {
  await expect(page.getByTestId("replay-angle-label")).toHaveText(label);
  await expect(page.getByTestId("replay-tier-badge")).toHaveText(badge);
  await expect(page.getByTestId("replay-angle-pos")).toHaveText(pos);
}

/** Cut with `key` and check the new angle took over at the same media time, still paused. */
async function cut(page: Page, key: string, angleId: string, t0: number) {
  await page.keyboard.press(key);
  await expect(page.getByTestId("replay")).toHaveAttribute("data-angle", angleId);
  await expect(page.getByTestId("replay-bug")).toHaveAttribute("data-prominent", "true");
  await expect.poll(async () => (await media(page))?.src).toContain(`angle=${angleId}`);
  await expect.poll(async () => Math.abs(((await media(page))?.t ?? -1) - t0)).toBeLessThan(0.05);
  expect((await media(page))?.paused).toBe(true);
}

async function openReplay(page: Page) {
  await page.goto(REPLAY);
  await expect
    .poll(async () => (await media(page))?.ready ?? 0, { timeout: 15_000 })
    .toBeGreaterThanOrEqual(2);
}

test("TV-09 cycleAngle wraps both ways; tier badges", () => {
  expect(cycleAngle(0, 4, 1)).toBe(1);
  expect(cycleAngle(3, 4, 1)).toBe(0);
  expect(cycleAngle(0, 4, -1)).toBe(3);
  expect(cycleAngle(2, 4, -1)).toBe(1);
  expect(cycleAngle(0, 1, 1)).toBe(0);
  expect(cycleAngle(0, 0, -1)).toBe(0);
  expect([tierBadge("A"), tierBadge("B"), tierBadge("C")]).toEqual(["Real video", "2.5D", "3D"]);
});

test("TV-09 Watch → Replays list → replay → Back → list → Watch", async ({ page }) => {
  // A game without replays has no Replays item.
  await openWatch(page, "g_pickle4");
  await page.keyboard.press("ArrowUp");
  await expect(page.getByTestId("nav-library")).toHaveAttribute("data-focused", "true");
  await expect(page.getByTestId("nav-replays")).toHaveCount(0);

  await openWatch(page);
  await menuTo(page, "nav-replays");
  await page.keyboard.press("Enter");

  const cards = page.getByTestId("replay-card");
  await expect(cards).toHaveCount(2);
  await expect(cards.first()).toContainText("4 angles");
  await expect(cards.first()).toHaveAttribute("data-focused", "true");
  await page.keyboard.press("ArrowDown");
  await expect(cards.nth(1)).toHaveAttribute("data-focused", "true");
  await page.keyboard.press("ArrowUp");
  await expect(cards.first()).toHaveAttribute("data-focused", "true");
  await page.keyboard.press("Enter");

  await expect(page.getByTestId("replay")).toHaveAttribute("data-angle", "wide");
  await expect(page.getByTestId("replay-title")).toHaveText("Marcus — make (mock)");
  await expect(page.getByTestId("replay-synthetic")).toBeVisible();

  await page.keyboard.press("Escape");
  await expect(page.getByTestId("replay-list")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("video")).toBeAttached();
  await expect(page.getByTestId("mode-pill")).toBeVisible();
});

test("TV-09 Left/Right cut angles at the same time and play state, wrapping", async ({ page }) => {
  await openReplay(page);
  await expectAngle(page, "Wide", "Real video", "1 / 4");
  // The angle name is big right after a cut (and on entry), then shrinks.
  await expect(page.getByTestId("replay-bug")).toHaveAttribute("data-prominent", "true");
  await expect(page.getByTestId("replay-bug")).toHaveAttribute("data-prominent", "false", { timeout: 5_000 });

  // Autoplays; let it run past 1 s, then pause with Select.
  await expect.poll(async () => (await media(page))?.t ?? 0, { timeout: 10_000 }).toBeGreaterThan(1);
  await page.keyboard.press("Enter");
  await expect.poll(async () => (await media(page))?.paused).toBe(true);
  const t0 = (await media(page)).t;

  await cut(page, "ArrowRight", "follow:p1", t0);
  await expectAngle(page, "Follow · Marcus", "Real video", "2 / 4");
  await cut(page, "ArrowRight", "broadcast_high", t0);
  await expectAngle(page, "Broadcast high", "2.5D", "3 / 4");
  await cut(page, "ArrowRight", "orbit", t0);
  await expectAngle(page, "Orbit", "2.5D", "4 / 4");
  await cut(page, "ArrowRight", "wide", t0); // wraps forward
  await expectAngle(page, "Wide", "Real video", "1 / 4");
  await cut(page, "ArrowLeft", "orbit", t0); // wraps back
  await expectAngle(page, "Orbit", "2.5D", "4 / 4");

  // Playing, with two cuts faster than a load: still playing, not reset to 0.
  await page.keyboard.press("Enter");
  await expect.poll(async () => (await media(page)).t).toBeGreaterThan(t0 + 1);
  const before = (await media(page)).t;
  await page.keyboard.press("ArrowLeft");
  await page.keyboard.press("ArrowLeft");
  await expect(page.getByTestId("replay")).toHaveAttribute("data-angle", "follow:p1");
  await expect
    .poll(async () => {
      const m = await media(page);
      return m.src.includes("angle=follow") && m.ready >= 2;
    })
    .toBe(true);
  const after = await media(page);
  expect(after.t).toBeGreaterThan(before - 0.1);
  expect(after.t).toBeLessThan(before + 5);
  await expect.poll(async () => (await media(page)).paused).toBe(false);

  await page.keyboard.press("Backspace");
  await expect(page.getByTestId("replay-list")).toBeVisible();
});

test("TV-09 10-foot UI: replay screens keep text ≥ 24 px and ring the focused card", async ({ page }) => {
  for (const path of [`/tv/${GAME_ID}/replays`, REPLAY]) {
    await page.goto(path);
    await page.waitForTimeout(500);
    const small = await page.evaluate(() =>
      [...document.querySelectorAll("div, span")]
        .filter((el) => [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent?.trim()))
        .map((el) => ({ text: el.textContent, size: parseFloat(getComputedStyle(el).fontSize) }))
        .filter((x) => x.size < 24),
    );
    expect(small, path).toEqual([]);
  }
  await page.goto(`/tv/${GAME_ID}/replays`);
  const ring = (i: number) =>
    page.getByTestId("replay-card").nth(i).evaluate((el) => getComputedStyle(el).borderTopColor);
  expect(await ring(0)).not.toBe(await ring(1));
});

// Opt-in evidence (REPLAY_TV_EVIDENCE_DIR): the view on a Tier A and a Tier B angle, the
// angle bug still big from the cut. Mock fixture → the picture is the mock wide.mp4.
test("TV-09 evidence screenshots", async ({ page }) => {
  const dir = process.env.REPLAY_TV_EVIDENCE_DIR;
  test.skip(!dir, "set REPLAY_TV_EVIDENCE_DIR to write screenshots");
  await openReplay(page);
  await page.keyboard.press("Enter");
  await expect.poll(async () => (await media(page))?.paused).toBe(true);
  await page.keyboard.press("ArrowRight");
  await expect.poll(async () => (await media(page))?.ready ?? 0).toBeGreaterThanOrEqual(2);
  await page.screenshot({ path: `${dir}/replay-tierA-follow-mock.png` });
  await page.keyboard.press("ArrowLeft");
  await page.keyboard.press("ArrowLeft");
  await expect(page.getByTestId("replay")).toHaveAttribute("data-angle", "orbit");
  await expect.poll(async () => (await media(page))?.ready ?? 0).toBeGreaterThanOrEqual(2);
  await page.screenshot({ path: `${dir}/replay-tierB-orbit-mock.png` });
});
