// Seeking in the player (docs/ux/redesign.md "Remote mapping"): a Left/Right tap moves
// 10 s, a hold accelerates (10 s steps, 30 s after 1 s, 1 min after 3 s, 2 min after 5 s),
// the video pauses while a 400 px preview cut from the storyboard sprite rides the
// playhead, snaps to a moment within 3 s and names it, and playback resumes from the new
// point after the release. Rew/FF (`,` `.`) scrub at 2/4/8/16× with a `×8` readout.
// Mock: 20 s video; storyboard 10 frames of 320x180 every 2 s on one 3200x180 sheet;
// g_mock01 moments at 3, 8, 14, 17 s, g_mock02 none.
import { expect, test, type Page } from "@playwright/test";
import type { Moment, Storyboard } from "../../../packages/tv-core/src/types";
import {
  fmtDelta,
  holdStep,
  jumpMoment,
  nextScrub,
  snapTo,
  storyboardCell,
} from "../src/playback/seek";
import { media, openWatch } from "./helpers";

const preview = (page: Page) => page.getByTestId("seek-preview");
const attr = async (page: Page, name: string) =>
  (await preview(page).getAttribute(`data-${name}`)) ?? "";

test("TV-20 seek maths: hold tiers, scrub speeds, snap, jumps, storyboard cells", () => {
  expect([0, 999, 1000, 2999, 3000, 4999, 5000, 60000].map(holdStep)).toEqual([
    10, 10, 30, 30, 60, 60, 120, 120,
  ]);
  let s = nextScrub(null, 1);
  expect(s).toEqual({ dir: 1, speed: 2 });
  for (const want of [4, 8, 16, 16]) {
    s = nextScrub(s, 1);
    expect(s.speed).toBe(want);
  }
  expect(nextScrub(s, -1)).toEqual({ dir: -1, speed: 2 }); // flipping starts over
  expect(fmtDelta(120)).toBe("+2:00");
  expect(fmtDelta(-30)).toBe("−0:30");

  const m = (id: string, t: number): Moment => ({
    id,
    t,
    t_start: t - 1.5,
    t_end: t + 1.5,
    kind: "play",
    label: id,
    thumb_url: null,
  });
  const ms = [m("a", 3), m("b", 8), m("c", 14)];
  expect(snapTo(ms, 10.5)?.id).toBe("b");
  expect(snapTo(ms, 11.1)?.id).toBe("c");
  expect(snapTo(ms, 25)).toBeNull();
  expect(jumpMoment(ms, 0, 1)?.id).toBe("a");
  expect(jumpMoment(ms, 1.5, 1)?.id).toBe("b"); // just jumped to a: on to the next
  expect(jumpMoment(ms, 7, -1)?.id).toBe("a"); // 0.5 s into b: back past it
  expect(jumpMoment(ms, 20, 1)).toBeNull();

  const sb: Storyboard = {
    interval_s: 2,
    width: 320,
    height: 180,
    cols: 10,
    rows: 10,
    count: 10,
    sheets: ["s0"],
  };
  expect(storyboardCell(sb, 10.4)).toEqual({
    sheet: "s0",
    x: 1600,
    y: 0,
    sheetW: 3200,
    sheetH: 180,
  });
  expect(storyboardCell(sb, 99)?.x).toBe(2880); // clamped to the last frame
  const big: Storyboard = {
    ...sb,
    cols: 2,
    rows: 2,
    count: 6,
    sheets: ["s0", "s1"],
  };
  expect(storyboardCell(big, 9)).toEqual({
    sheet: "s1",
    x: 0,
    y: 0,
    sheetW: 640,
    sheetH: 180,
  });
  expect(storyboardCell(big, 7)).toEqual({
    sheet: "s0",
    x: 320,
    y: 180,
    sheetW: 640,
    sheetH: 360,
  });
});

test("TV-20 a tap seeks 10 s with a sprite preview, then resumes from there", async ({
  page,
}) => {
  await openWatch(page, "g_mock02", "?t=1");
  await expect.poll(async () => (await media(page)).paused).toBe(false);
  const from = (await media(page)).t;
  await page.keyboard.press("ArrowRight");
  await expect(preview(page)).toBeVisible();
  expect((await media(page)).paused).toBe(true); // playback pauses while seeking
  const at = Number(await attr(page, "t"));
  expect(at).toBeGreaterThan(from + 9.5);
  expect(at).toBeLessThan(from + 11);
  await expect(page.getByTestId("seek-readout")).toHaveText("+0:10");
  expect(await attr(page, "step")).toBe("10");

  // The frame is the sprite cell for that time, cropped out of the sheet (scale 400/320).
  expect(await attr(page, "sheet")).toContain("/mock/storyboard/0000.jpg");
  expect(Number(await attr(page, "x"))).toBe(Math.floor(at / 2) * 320);
  const frame = (await preview(page).boundingBox())!;
  const sprite = (await page.getByTestId("seek-sprite").boundingBox())!;
  expect(sprite.width).toBeCloseTo(4000, 0);
  expect(sprite.height).toBeCloseTo(225, 0);
  expect(sprite.x - frame.x).toBeCloseTo(-Math.floor(at / 2) * 400, 0);
  expect(frame.width).toBeCloseTo(400, 0);

  // Released: after a beat the preview goes and playback resumes at the new point.
  await expect(preview(page)).toHaveCount(0, { timeout: 3_000 });
  await expect.poll(async () => (await media(page)).paused).toBe(false);
  expect((await media(page)).t).toBeGreaterThan(at - 0.2);
});

test("TV-20 the storyboard sheets load with the game, before the first seek", async ({
  page,
}) => {
  const sheet = page.waitForRequest(/\/mock\/storyboard\/0000\.jpg/);
  await openWatch(page, "g_mock02", "?t=1");
  await sheet; // no key pressed yet
  await expect(preview(page)).toHaveCount(0);
});

test("TV-20 holding accelerates: 10 s, then 30 s after 1 s, 1 min after 3 s, 2 min after 5 s", async ({
  page,
}) => {
  await openWatch(page, "g_mock02");
  const steps: Record<string, string> = {};
  await page.keyboard.down("ArrowRight");
  const t0 = Date.now();
  // Remote-style repeats every 120 ms; sample the step after each tier boundary.
  for (const [label, at] of [
    ["0.5", 500],
    ["1.3", 1300],
    ["3.3", 3300],
    ["5.3", 5300],
  ] as const) {
    while (Date.now() - t0 < at) {
      await page.waitForTimeout(120);
      await page.keyboard.down("ArrowRight");
    }
    steps[label] = await attr(page, "step");
  }
  expect(steps).toEqual({
    "0.5": "10",
    "1.3": "30",
    "3.3": "60",
    "5.3": "120",
  });
  expect((await media(page)).paused).toBe(true);
  await expect(page.getByTestId("timeline")).toHaveAttribute("data-t", "20.0"); // clamped at the end
  await page.keyboard.up("ArrowRight");
  await expect(preview(page)).toHaveCount(0, { timeout: 3_000 });
});

test("TV-20 near a moment the preview snaps to it, names it, and playback resumes at its start", async ({
  page,
}) => {
  await openWatch(page, "g_mock01", "?t=4");
  await expect.poll(async () => (await media(page)).paused).toBe(false);
  await page.keyboard.press("ArrowRight"); // ~14.x s: within 3 s of e_0003 (14 s)
  await expect(preview(page)).toHaveAttribute("data-snapped", "e_0003");
  await expect(preview(page)).toHaveAttribute("data-t", "14.0");
  await expect(page.getByTestId("seek-label")).toHaveText("Basket, Marcus");
  await expect(page.getByTestId("timeline")).toHaveAttribute("data-t", "14.0");
  await expect(preview(page)).toHaveCount(0, { timeout: 3_000 });
  await expect.poll(async () => (await media(page)).paused).toBe(false);
  const t = (await media(page)).t;
  expect(t).toBeGreaterThanOrEqual(12.45); // the moment's start (t_start = 12.5 s)
  expect(t).toBeLessThan(13.6);
});

test("TV-20 Fast-forward scrubs at 2/4/8× with a ×8 readout; Select commits, Back cancels", async ({
  page,
}) => {
  await openWatch(page, "g_mock02", "?t=1");
  await expect.poll(async () => (await media(page)).paused).toBe(false);
  for (let i = 0; i < 3; i++) await page.keyboard.press(".");
  await expect(page.getByTestId("seek-readout")).toHaveText("×8");
  await expect(page.getByTestId("seek-readout")).toHaveAttribute(
    "data-dir",
    "1",
  );
  await expect(preview(page)).toHaveAttribute("data-speed", "8");
  expect((await media(page)).paused).toBe(true);
  const a = Number(await attr(page, "t"));
  await page.waitForTimeout(500);
  const b = Number(await attr(page, "t"));
  expect(b - a).toBeGreaterThan(2.5); // ~8 s of game per second
  await page.keyboard.press("Enter");
  await expect(preview(page)).toHaveCount(0);
  await expect.poll(async () => (await media(page)).paused).toBe(false);
  expect((await media(page)).t).toBeGreaterThan(b - 0.2);

  // Rewind flips to 2× backwards; Back drops the scrub and plays on from where it was.
  const before = (await media(page)).t;
  await page.keyboard.press(",");
  await expect(page.getByTestId("seek-readout")).toHaveText("×2");
  await expect(page.getByTestId("seek-readout")).toHaveAttribute(
    "data-dir",
    "-1",
  );
  await page.waitForTimeout(400);
  await page.keyboard.press("Escape");
  await expect(preview(page)).toHaveCount(0);
  await expect.poll(async () => (await media(page)).paused).toBe(false);
  expect(Math.abs((await media(page)).t - before)).toBeLessThan(1);
});
