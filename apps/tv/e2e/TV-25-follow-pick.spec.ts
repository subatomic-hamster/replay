// Do more → Follow player picks on the video (REPLAY_PLAN.md §1: "pause, arrow between
// players, select one, press play"), not from a row of chips: the video pauses with a
// marker in its team's colour on every player in the frame; the arrows move spatially;
// tagged players carry their name, an untagged one reads "Player N" while focused; Select
// follows and playback resumes; Back cancels the pick. The ring is on the player and the
// camera moving within 200 ms of Select (D-82: the camera is computed in the app from the
// tracks already loaded, nothing is fetched on Select), and the camera holds and widens
// through a tracking gap instead of jumping, then closes back in.
import { expect, test, type Page } from "@playwright/test";
import {
  enterSelectMode,
  focusedBoxId,
  media,
  menuTo,
  openWatch,
  smallText,
  transform,
} from "./helpers";

/** Time from the Enter keydown to the ring showing and to the camera leaving the wide
 *  shot, measured in the page on animation frames (no Playwright round trips). */
async function armPickTimer(page: Page) {
  await page.evaluate(() => {
    const w = window as unknown as {
      __pick: { key: number; ring: number; cam: number };
    };
    w.__pick = { key: 0, ring: 0, cam: 0 };
    window.addEventListener(
      "keydown",
      (e) => {
        if (e.key === "Enter" && !w.__pick.key)
          w.__pick.key = performance.now();
      },
      true,
    );
    const tick = () => {
      const p = w.__pick;
      if (p.key) {
        const f = document.querySelector('[data-testid="follow-frame"]');
        if (!p.ring && f && Number(getComputedStyle(f).opacity) > 0.5)
          p.ring = performance.now();
        const el = document.querySelector('[data-testid="player-transform"]');
        const m = el ? new DOMMatrix(getComputedStyle(el).transform) : null;
        if (!p.cam && m && m.a > 1.001) p.cam = performance.now();
      }
      if (!p.ring || !p.cam) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  });
}

const pickLag = (page: Page) =>
  page.evaluate(() => {
    const p = (
      window as unknown as {
        __pick: { key: number; ring: number; cam: number };
      }
    ).__pick;
    return p.ring && p.cam
      ? { ring: p.ring - p.key, cam: p.cam - p.key }
      : null;
  });

test("TV-25 pick on the video with the arrows; Select follows at once; Back cancels", async ({
  page,
}) => {
  await openWatch(page);
  await expect.poll(async () => (await media(page)).paused).toBe(false);
  await menuTo(page, "action-follow");
  const tile = page.getByTestId("action-follow");
  await expect(tile).toContainText("Pick a player on screen");
  await expect(tile).toHaveAttribute("data-children", "0"); // no carousel of players
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("domore")).toHaveCount(0);

  // Paused, a marker on every tracked player, focus on the leftmost.
  const watch = page.getByTestId("watch");
  await expect(watch).toHaveAttribute("data-mode", "select");
  await expect.poll(async () => (await media(page)).paused).toBe(true);
  await expect(page.locator('[data-testid^="select-box-"]')).toHaveCount(4);
  await expect.poll(() => focusedBoxId(page)).toBe("p1");
  await expect(page.getByTestId("select-hint")).toContainText(
    "Arrows move between players",
  );
  await expect(page.getByTestId("player-label-p1")).toHaveText("Marcus");
  await expect(page.getByTestId("player-label-p2")).toHaveCount(0); // anonymous, unfocused
  await page.keyboard.press("ArrowRight");
  await expect.poll(() => focusedBoxId(page)).toBe("p2");
  await expect(page.getByTestId("player-label-p2")).toHaveText("Player 2");
  await expect(page.getByTestId("player-label-p1")).toHaveText("Marcus"); // tagged: stays
  expect(await smallText(page)).toEqual([]);

  // Back cancels the pick: the wide shot, playing again, nobody followed.
  await page.keyboard.press("Escape");
  await expect(watch).toHaveAttribute("data-mode", "wide");
  await expect.poll(async () => (await media(page)).paused).toBe(false);
  await expect(page.getByTestId("follow-frame")).toHaveCount(0);

  // Pick p3 (team 0, like Marcus) with the arrows.
  await enterSelectMode(page);
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowRight");
  await expect.poll(() => focusedBoxId(page)).toBe("p3");
  const teamInk = await page
    .getByTestId("select-box-p1")
    .evaluate((el) => getComputedStyle(el).borderTopColor);

  // Select: ring and camera within 200 ms, playback resumes.
  await armPickTimer(page);
  await page.keyboard.press("Enter");
  await expect.poll(() => pickLag(page)).not.toBeNull();
  const lag = (await pickLag(page))!;
  expect(lag.ring).toBeLessThan(200);
  expect(lag.cam).toBeLessThan(200);
  await expect(watch).toHaveAttribute("data-mode", "follow");
  await expect.poll(async () => (await media(page)).paused).toBe(false);
  const ring = page.getByTestId("follow-frame");
  await expect(ring).toHaveAttribute("data-pid", "p3");
  await expect(ring).toHaveAttribute("data-visible", "true");
  await expect(ring).toContainText("Player 3");
  // the ring is in the player's team colour, not the focus amber
  const top = page.getByTestId("follow-frame-top"); // the ring's top edge
  expect(await top.evaluate((el) => getComputedStyle(el).backgroundColor)).toBe(
    teamInk,
  );
  await expect(page.getByTestId("followcam-active")).toContainText(
    "Following Player 3",
  );

  // Settled: scale 2 (window 0.5 high), clamped at the right edge (x 0.5), so p3's box
  // (x 0.73–0.75, w 0.06) sits at ~48 % across the picture, 12 % wide: the ring is drawn
  // through the same camera as the video.
  await expect
    .poll(async () => (await transform(page))[0], { timeout: 5_000 })
    .toBeCloseTo(2, 2);
  const surface = (await page.getByTestId("player-surface").boundingBox())!;
  await expect
    .poll(async () => {
      const b = (await top.boundingBox())!;
      return Math.abs((b.x - surface.x) / surface.width - 0.48);
    })
    .toBeLessThan(0.03);
  const b = (await top.boundingBox())!;
  expect(Math.abs(b.width / surface.width - 0.12)).toBeLessThan(0.01);

  // Do more while following: who, and the row for them (no chips).
  await menuTo(page, "action-follow");
  await expect(tile).toContainText("Following Player 3");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("domore")).toHaveAttribute(
    "data-row",
    "action-follow",
  );
  await expect(page.getByTestId("follow-pick")).toContainText(
    "Pick another player",
  );
  await expect(page.getByTestId("action-tag")).toContainText("Tag Player 3");
  await expect(page.getByTestId("action-spotlight")).toBeAttached();
  await expect(page.getByTestId("action-link-profile")).toBeAttached();
  await page.keyboard.press("Escape");
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("domore")).toHaveCount(0);

  // Back stops following: eases back to the wide shot, still playing, ring stays on p3.
  await page.keyboard.press("Escape");
  await expect(watch).toHaveAttribute("data-mode", "wide");
  await expect.poll(async () => (await transform(page))[0]).toBeCloseTo(1, 3);
  await expect(ring).toHaveAttribute("data-pid", "p3");
  expect((await media(page)).paused).toBe(false);
});

test("TV-25 through a tracking gap the camera holds and widens, then closes back in", async ({
  page,
}) => {
  // The mock's p1 has no box for 12–13 s (a scripted occlusion).
  await openWatch(page, undefined, "?t=8.5"); // time to settle at scale 2 first
  await enterSelectMode(page);
  await expect.poll(() => focusedBoxId(page)).toBe("p1");
  await page.keyboard.press("Enter");
  const ring = page.getByTestId("follow-frame");
  await expect(ring).toHaveAttribute("data-visible", "true");
  await expect
    .poll(async () => (await transform(page))[0], { timeout: 5_000 })
    .toBeCloseTo(2, 1);

  // Sample the camera and the ring every animation frame from here to past the gap.
  type Sample = {
    t: number;
    s: number;
    on: boolean;
    op: number;
    rx: number;
  };
  const samples = await page.evaluate(
    () =>
      new Promise<Sample[]>((done) => {
        const out: Sample[] = [];
        const v = document.querySelector<HTMLVideoElement>(
          '[data-testid="video"]',
        )!;
        const tick = () => {
          const el = document.querySelector(
            '[data-testid="player-transform"]',
          )!;
          const m = new DOMMatrix(getComputedStyle(el).transform);
          const f = document.querySelector('[data-testid="follow-frame"]');
          const fs = f ? getComputedStyle(f) : null;
          out.push({
            t: v.currentTime,
            s: m.a,
            on: !!f && f.getAttribute("data-visible") === "true",
            op: fs ? Number(fs.opacity) : 0,
            rx: fs ? new DOMMatrix(fs.transform).e : 0,
          });
          if (v.currentTime < 14.5 && !v.paused) requestAnimationFrame(tick);
          else done(out);
        };
        requestAnimationFrame(tick);
      }),
  );
  // Before the gap the ring rides the player at frame rate: always fully on (no
  // flicker), moving a few pixels a frame at most (no jumps between players).
  const tracked = samples.filter((x) => x.t < 11.9);
  expect(tracked.length).toBeGreaterThan(10);
  expect(Math.min(...tracked.map((x) => x.op))).toBeGreaterThan(0.99);
  for (let i = 1; i < tracked.length; i++)
    expect(Math.abs(tracked[i].rx - tracked[i - 1].rx)).toBeLessThan(8);
  // A dropout first keeps the ring on (grace), then fades it out; it comes back after.
  const gapStart = samples.filter((x) => x.t > 12.02 && x.t < 12.15);
  expect(Math.min(...gapStart.map((x) => x.op))).toBeGreaterThan(0.9);
  const gapLate = samples.filter((x) => x.t > 12.75 && x.t < 12.95);
  expect(Math.max(...gapLate.map((x) => x.op))).toBeLessThan(0.1);
  const gap = samples.filter((x) => x.t > 12.1 && x.t < 12.95);
  const after = samples.filter((x) => x.t > 14.2);
  expect(gap.length).toBeGreaterThan(5);
  expect(gap.every((x) => !x.on)).toBe(true); // no box: no ring, honestly
  expect(Math.min(...after.map((x) => x.op))).toBeGreaterThan(0.9);
  // holds first, then starts widening (after 0.6 s), by small steps, never jumping
  const early = gap.filter((x) => x.t < 12.5);
  expect(Math.min(...early.map((x) => x.s))).toBeGreaterThan(1.97);
  expect(Math.min(...gap.map((x) => x.s))).toBeLessThan(1.99);
  for (let i = 1; i < gap.length; i++)
    expect(Math.abs(gap[i].s - gap[i - 1].s)).toBeLessThan(0.05);
  // back: the ring returns and the camera closes in again
  expect(after.length).toBeGreaterThan(0);
  expect(after.every((x) => x.on)).toBe(true);
  expect(after[after.length - 1].s).toBeGreaterThan(
    Math.min(...gap.map((x) => x.s)),
  );
});

test("TV-25 lost past a hand-off's reach: the chip says so and Select picks again nearby", async ({
  page,
}) => {
  // This test's own occlusion (the mock's override hook): p1 gone from 12 s to 40 s.
  await page.addInitScript(() => {
    (
      window as unknown as {
        __replayMockTrackGap: Record<string, [number, number]>;
      }
    ).__replayMockTrackGap = { p1: [12, 40] };
  });
  await openWatch(page, undefined, "?t=9");
  await enterSelectMode(page);
  await expect.poll(() => focusedBoxId(page)).toBe("p1");
  await page.keyboard.press("Enter");
  const watch = page.getByTestId("watch");
  const chip = page.getByTestId("followcam-active");
  await expect(chip).toContainText("Following Marcus");
  await expect(page.getByTestId("follow-repick")).toHaveCount(0);
  // 1.5 s (HANDOFF_MAX_GAP_S) into the gap, no hand-off: say so, don't park on nobody
  await expect(chip).toContainText("Lost sight of Marcus", { timeout: 10_000 });
  await expect(page.getByTestId("follow-repick")).toContainText("Pick again");
  await expect(watch).toHaveAttribute("data-mode", "follow");
  // Select picks again: paused, markers up, focus on the player nearest where Marcus
  // was last seen (p1 x 0.08: p2 at x 0.44 is nearest), Select follows them
  await page.keyboard.press("Enter");
  await expect(watch).toHaveAttribute("data-mode", "select");
  expect((await media(page)).paused).toBe(true);
  await expect.poll(() => focusedBoxId(page)).toBe("p2");
  await page.keyboard.press("Enter");
  await expect(watch).toHaveAttribute("data-mode", "follow");
  await expect(chip).toHaveAttribute("data-player-id", "p2");
  await expect(chip).toContainText("Following Player 2");
  await expect(page.getByTestId("follow-repick")).toHaveCount(0);
  await expect.poll(async () => (await media(page)).paused).toBe(false);
});
