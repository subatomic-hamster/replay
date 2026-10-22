// M8 multi-angle replay, inside the player: Left/Right cut between time-aligned angle
// videos, keeping the playback position and play state; Back returns to the game. The mock
// serves every angle as /mock/wide.mp4?angle=<id>, so each cut is a real src swap + reload.
import { expect, test, type Page } from "@playwright/test";
import {
  angleHonesty,
  angleLabel,
  cycleAngle,
  tierBadge,
} from "../../../packages/tv-core/src/replays";
import { GAME_ID, openWatch, smallText } from "./helpers";

const REPLAY = `/tv/${GAME_ID}/replays/play_0001`;

async function media(page: Page) {
  return page.evaluate(() => {
    const v = document.querySelector<HTMLVideoElement>('[data-testid="video"]');
    return v
      ? {
          t: v.currentTime,
          paused: v.paused,
          src: v.currentSrc,
          ready: v.readyState,
        }
      : { t: -1, paused: true, src: "", ready: 0 };
  });
}

async function expectAngle(
  page: Page,
  label: string,
  badge: string,
  pos: string,
) {
  await expect(page.getByTestId("replay-angle-label")).toHaveText(label);
  await expect(page.getByTestId("replay-tier-badge")).toHaveText(badge);
  await expect(page.getByTestId("replay-angle-pos")).toHaveText(pos);
}

/** Cut with `key` and check the new angle took over at the same media time, still paused. */
async function cut(page: Page, key: string, angleId: string, t0: number) {
  await page.keyboard.press(key);
  await expect(page.getByTestId("replay")).toHaveAttribute(
    "data-angle",
    angleId,
  );
  await expect(page.getByTestId("replay-bug")).toHaveAttribute(
    "data-prominent",
    "true",
  );
  await expect
    .poll(async () => (await media(page))?.src)
    .toContain(`angle=${angleId}`);
  await expect
    .poll(async () => Math.abs(((await media(page))?.t ?? -1) - t0))
    .toBeLessThan(0.05);
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
  // plain words: the camera's own pixels, or recreated from them (no tier letters)
  expect([tierBadge("A"), tierBadge("B"), tierBadge("C")]).toEqual([
    "Camera",
    "Virtual replay",
    "Virtual replay",
  ]);
  const angle = (id: string, tier: "A" | "B" | "C", label: string) => ({
    id,
    tier,
    label,
    url: "",
    duration_s: 1,
    width: 1,
    height: 1,
  });
  const pov = angle("pov:p3", "C", "Virtual POV · Player 3");
  expect(angleLabel(pov)).toBe("Player's view · Player 3");
  expect(angleLabel(angle("3d:wing", "C", "Virtual wing"))).toBe(
    "Virtual wing",
  );
  expect(angleHonesty(angle("wide", "A", "Wide"))).toBeNull();
  expect(angleHonesty(angle("orbit", "B", "Orbit"))).toBe(
    "Recreated from the real players on a model of the court",
  );
  expect(angleHonesty(pov)).toBe("A recreated player's-eye view, not a camera");
});

// The way in from the player (Do more → Replay angles) and Back to the game: TV-26.
// A game without replays keeps the tile, says why, and Free view / POV are not tiles.
test("TV-09 a game without replays has no Free view or Player POV", async ({
  page,
}) => {
  await openWatch(page, "g_pickle4");
  await page.keyboard.press("ArrowUp");
  await expect(page.getByTestId("domore")).toBeVisible();
  await expect(page.getByTestId("nav-replays")).toContainText(
    /Not ready for this game|Getting ready/,
  );
  await expect(page.getByTestId("action-free-view")).toHaveCount(0);
  await expect(page.getByTestId("action-pov")).toHaveCount(0);
});

test("TV-09 Left/Right cut angles at the same time and play state, wrapping", async ({
  page,
}) => {
  await openReplay(page);
  await expectAngle(page, "Wide", "Camera", "1 of 5");
  await expect(page.getByTestId("angle-honesty")).toHaveCount(0);
  // The breadcrumb names the room; the legend has at most 3 keys, Back to the game.
  await expect(page.getByTestId("context-chip")).toContainText(
    "Replay angles › Marcus — make (mock)",
  );
  await expect(page.getByTestId("key-legend").locator("> *")).toHaveCount(3);
  await expect(page.getByTestId("legend-◀▶")).toHaveAttribute(
    "data-label",
    "Angles",
  );
  await expect(page.getByTestId("legend-▼")).toHaveAttribute(
    "data-label",
    "Free view",
  );
  await expect(page.getByTestId("legend-Back")).toHaveAttribute(
    "data-label",
    "Game",
  );
  // The angle name is big right after a cut (and on entry), then shrinks.
  await expect(page.getByTestId("replay-bug")).toHaveAttribute(
    "data-prominent",
    "true",
  );
  await expect(page.getByTestId("replay-bug")).toHaveAttribute(
    "data-prominent",
    "false",
    { timeout: 8_000 },
  );

  // Autoplays; let it run past 1 s, then pause with Select.
  await expect
    .poll(async () => (await media(page))?.t ?? 0, { timeout: 10_000 })
    .toBeGreaterThan(1);
  await page.keyboard.press("Enter");
  await expect.poll(async () => (await media(page))?.paused).toBe(true);
  const t0 = (await media(page)).t;

  await cut(page, "ArrowRight", "follow:p1", t0);
  await expectAngle(page, "Follow · Marcus", "Camera", "2 of 5");
  await cut(page, "ArrowRight", "broadcast_high", t0);
  await expectAngle(page, "Broadcast high", "Virtual replay", "3 of 5");
  // every recreated cut says so, in plain words
  await expect(page.getByTestId("angle-honesty")).toHaveText(
    "Recreated from the real players on a model of the court",
  );
  await cut(page, "ArrowRight", "orbit", t0);
  await expectAngle(page, "Orbit", "Virtual replay", "4 of 5");
  // the players' virtual POVs share one slot: the key player's, Up for the next player
  await cut(page, "ArrowRight", "pov:p1", t0);
  await expectAngle(page, "Player's view · Marcus", "Virtual replay", "5 of 5");
  await expect(page.getByTestId("pov-honesty")).toHaveText(
    "A recreated player's-eye view, not a camera",
  );
  await expect(page.getByTestId("legend-▲")).toHaveAttribute(
    "data-label",
    "Next player",
  );
  await cut(page, "ArrowUp", "pov:p2", t0);
  await expectAngle(page, "Player's view · Jordan", "Virtual replay", "5 of 5");
  await cut(page, "ArrowRight", "wide", t0); // wraps forward
  await expectAngle(page, "Wide", "Camera", "1 of 5");
  await expect(page.getByTestId("pov-honesty")).toHaveCount(0);
  await cut(page, "ArrowLeft", "pov:p1", t0); // wraps back, to the key player's POV
  await cut(page, "ArrowLeft", "orbit", t0);
  await expectAngle(page, "Orbit", "Virtual replay", "4 of 5");

  // Playing, with two cuts faster than a load: still playing, not reset to 0.
  await page.keyboard.press("Enter");
  await expect.poll(async () => (await media(page)).t).toBeGreaterThan(t0 + 1);
  const before = (await media(page)).t;
  await page.keyboard.press("ArrowLeft");
  await page.keyboard.press("ArrowLeft");
  await expect(page.getByTestId("replay")).toHaveAttribute(
    "data-angle",
    "follow:p1",
  );
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

  // Back: the game itself (a deep link has no earlier spot: the play's start).
  await page.keyboard.press("Backspace");
  await expect(page.getByTestId("watch")).toBeVisible();
  await expect(page.getByTestId("timeline")).toBeAttached();
});

test("TV-09 10-foot UI: the angle view keeps text ≥ 24 px; the old list is the player", async ({
  page,
}) => {
  await page.goto(REPLAY);
  await expect(page.getByTestId("replay")).toBeVisible();
  await page.waitForTimeout(500);
  expect(await smallText(page)).toEqual([]);
  await page.goto(`/tv/${GAME_ID}/replays`);
  await expect(page.getByTestId("watch")).toBeVisible();
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
  await expect
    .poll(async () => (await media(page))?.ready ?? 0)
    .toBeGreaterThanOrEqual(2);
  await page.screenshot({ path: `${dir}/replay-tierA-follow-mock.png` });
  await page.keyboard.press("ArrowLeft");
  await page.keyboard.press("ArrowLeft");
  await expect(page.getByTestId("replay")).toHaveAttribute(
    "data-angle",
    "orbit",
  );
  await expect
    .poll(async () => (await media(page))?.ready ?? 0)
    .toBeGreaterThanOrEqual(2);
  await page.screenshot({ path: `${dir}/replay-tierB-orbit-mock.png` });
});
