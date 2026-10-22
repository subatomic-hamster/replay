// Seeking in the player (docs/ux/redesign.md "Remote mapping"): each Left/Right tap or
// repeat goes to the next stop, a grid at the step (10 s; a hold accelerates to 30 s after
// 1 s, 1 min after 3 s, 2 min after 5 s) plus every moment's start (seek.ts nextStop).
// The video pauses while a 400 px preview (the storyboard sprite's cell, or at a moment
// its thumb and name) rides the playhead, and playback resumes at the stop after the
// release. Rew/FF (`,` `.`) scrub at 2/4/8/16× with a `×8` readout.
// Mock: 20 s video; storyboard 10 frames of 320x180 every 2 s on one 3200x180 sheet;
// g_mock01 moments at 3, 8, 14, 17 s, g_mock02 none.
import { expect, test, type Page } from "@playwright/test";
import type { Moment, Storyboard } from "../../../packages/tv-core/src/types";
import {
  fmtDelta,
  holdStep,
  jumpMoment,
  nextScrub,
  nextStop,
  storyboardCell,
} from "../src/playback/seek";
import { media, openWatch } from "./helpers";

const preview = (page: Page) => page.getByTestId("seek-preview");
const attr = async (page: Page, name: string) =>
  (await preview(page).getAttribute(`data-${name}`)) ?? "";

/** Every seek preview state the page shows ("t|snapped|label|readout|sprite x"), deduped,
 *  logged as React commits it: fast taps outrun Playwright's reads. */
async function logSeeks(page: Page) {
  await page.evaluate(() => {
    const log: string[] = [];
    (window as Window & { seekLog?: string[] }).seekLog = log;
    const q = (id: string) =>
      document.querySelector<HTMLElement>(`[data-testid="${id}"]`);
    new MutationObserver(() => {
      const p = q("seek-preview");
      if (!p) return;
      const row = [
        p.dataset.t,
        p.dataset.snapped,
        q("seek-label")?.textContent ?? "",
        q("seek-readout")?.textContent ?? "",
        p.dataset.x,
      ].join("|");
      if (log.at(-1) !== row) log.push(row);
    }).observe(document.body, {
      subtree: true,
      childList: true,
      characterData: true,
      attributes: true,
    });
  });
}
const seekLog = (page: Page) =>
  page.evaluate(
    () => (window as Window & { seekLog?: string[] }).seekLog ?? [],
  );

test("TV-20 seek stops: a grid at the step plus every moment's start", () => {
  const at = (id: string, t_start: number, kind: Moment["kind"] = "play") =>
    ({
      id,
      t: t_start + 1.5,
      t_start,
      t_end: t_start + 3,
      kind,
      label: id,
      thumb_url: null,
    }) satisfies Moment;
  /** `n` steps from `from`; a moment stop reads "t id". */
  const walk = (
    ms: Moment[],
    from: number,
    dir: 1 | -1,
    step: number,
    n: number,
    dur = 240,
    live = false,
  ) => {
    const out: (number | string)[] = [];
    let t = from;
    for (let i = 0; i < n; i++) {
      const s = nextStop(ms, t, dir, step, dur, live && i === 0);
      out.push(s.moment ? `${s.t} ${s.moment.id}` : s.t);
      t = s.t;
    }
    return out;
  };
  // grid only, anchored at 0 whatever the start
  expect(walk([], 33.4, 1, 10, 3)).toEqual([40, 50, 60]);
  expect(walk([], 47, 1, 30, 2)).toEqual([60, 90]);
  // a moment between grid points is an extra stop, not a replacement
  const basket = at("basket", 43, "score");
  expect(walk([basket], 30, 1, 10, 4)).toEqual([40, "43 basket", 50, 60]);
  // backwards, the same stops in reverse
  expect(walk([basket], 60, -1, 10, 4)).toEqual([50, "43 basket", 40, 30]);
  // a moment on (or a hair off) a grid point is that one stop, with its name
  expect(walk([at("on", 50)], 30, 1, 10, 3)).toEqual([40, "50 on", 60]);
  expect(walk([at("off", 50.1)], 30, 1, 10, 3)).toEqual([40, "50.1 off", 60]);
  expect(walk([at("off", 49.9)], 60, -1, 10, 2)).toEqual(["49.9 off", 40]);
  // the ends are stops, and a step at an end stays there
  expect(walk([], 235, 1, 10, 2)).toEqual([240, 240]);
  expect(walk([], 230, 1, 10, 3, 245)).toEqual([240, 245, 245]);
  expect(walk([], 3, -1, 10, 2)).toEqual([0, 0]);
  expect(walk([at("pre", -1)], 5, -1, 10, 2)).toEqual(["0 pre", 0]); // clamped to 0
  // the first back step from the playing video skips a stop it just left
  expect(walk([], 40.6, -1, 10, 1, 240, true)).toEqual([30]);
  expect(walk([], 40.6, -1, 10, 1)).toEqual([40]);
  expect(walk([], 1.5, -1, 10, 1, 240, true)).toEqual([0]);
  // a cluster at a fast tier: one stop per interval, score > play > bookmark
  const cluster = [
    at("p", 61),
    at("s1", 62, "score"),
    at("bm", 63, "bookmark"),
    at("s2", 65, "score"),
    at("bm2", 130, "bookmark"),
  ];
  expect(walk(cluster, 0, 1, 60, 6)).toEqual([
    60,
    "62 s1",
    120,
    "130 bm2",
    180,
    240,
  ]);
  expect(walk(cluster, 180, -1, 60, 5)).toEqual([
    "130 bm2",
    120,
    "62 s1",
    60,
    0,
  ]);
  // below the fast tiers every moment is a stop
  expect(walk(cluster, 60, 1, 30, 5)).toEqual([
    "61 p",
    "62 s1",
    "63 bm",
    "65 s2",
    90,
  ]);
  // a real-like game, 33 moments in 240 s: taps still stop at every grid point, in order
  const dense = Array.from({ length: 33 }, (_, i) =>
    at(`e${i}`, 4 + i * 7.1 + (i % 3)),
  );
  const taps = walk(dense, 30, 1, 10, 40).map((s) => parseFloat(String(s)));
  for (const g of [40, 50, 60, 70, 80, 90, 100, 110]) expect(taps).toContain(g);
  const inRange = dense.filter((d) => d.t_start > 30.25 && d.t_start < 110);
  for (const d of inRange) expect(taps).toContain(d.t_start);
  expect(taps.every((t, i) => i === 0 || t > taps[i - 1] || t === 240)).toBe(
    true,
  );
});

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
  // the next point on the 10 s grid (g_mock02 has no moments); the readout is the distance
  const at = Number(await attr(page, "t"));
  expect(at).toBe(10);
  const delta = Number(
    (await page.getByTestId("seek-readout").textContent())?.slice(-2),
  );
  expect(Math.abs(delta - (10 - from))).toBeLessThanOrEqual(1);
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
  await openWatch(page, "g_mock01");
  await logSeeks(page);
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
  // Each repeat went to the next stop: the moments' starts and the 10 s grid, then the end.
  const ts = (await seekLog(page)).map((r) => r.split("|")[0]);
  expect(ts.slice(-5)).toEqual(["6.5", "10.0", "12.5", "15.5", "20.0"]);
  await page.keyboard.up("ArrowRight");
  await expect(preview(page)).toHaveCount(0, { timeout: 3_000 });
});

test("TV-20 taps stop at each 10 s grid point and each moment's start; release lands on the stop", async ({
  page,
}) => {
  await openWatch(page, "g_mock01", "?t=0.5");
  await expect.poll(async () => (await media(page)).paused).toBe(false);
  await page.keyboard.press("Space"); // paused: the seek starts from a fixed point
  await expect.poll(async () => (await media(page)).paused).toBe(true);
  const t0 = (await media(page)).t;
  // g_mock01's stops: moment starts 1.5, 6.5, 12.5, 15.5 (t_key − 1.5), the grid at 10, the end.
  const stops: [number, string, string][] = [
    [1.5, "e_0001", "Basket, Marcus"],
    [6.5, "e_0002", "Missed shot"], // unnamed players: no name in the label
    [10, "", ""],
    [12.5, "e_0003", "Basket, Marcus"],
    [15.5, "e_0004", "Basket"],
    [20, "", ""],
  ];
  const ahead = stops.filter(([t]) => t > t0 + 0.25);
  const row = ([t, id, label]: [number, string, string]) =>
    [
      t.toFixed(1),
      id,
      label,
      fmtDelta(t - t0),
      // a moment shows its thumb, a grid point the sprite cell (10 frames, every 2 s)
      id ? "" : Math.min(9, Math.floor(t / 2)) * 320,
    ].join("|");

  // Quick taps are one seek (each within the 600 ms linger): every stop in turn, one
  // past the end stays there, then two back.
  await logSeeks(page);
  for (let i = 0; i <= ahead.length; i++)
    await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowLeft");
  await page.keyboard.press("ArrowLeft");
  const [e3, e4] = stops.slice(3); // 12.5 Basket, 15.5
  await expect
    .poll(() => seekLog(page))
    .toEqual([...ahead.map(row), row(e4), row(e3)]);
  await expect(page.getByTestId("seek-label")).toHaveText("Basket, Marcus");
  await expect(page.getByTestId("timeline")).toHaveAttribute("data-t", "12.5");

  // Released: it was paused, so it stays paused, exactly on the moment's start.
  await expect(preview(page)).toHaveCount(0, { timeout: 3_000 });
  await expect.poll(async () => (await media(page)).t).toBeCloseTo(12.5, 2);
  expect((await media(page)).paused).toBe(true);

  // Playing from there, a tap stops at the next moment and resumes at its start.
  await page.keyboard.press("Space");
  await expect.poll(async () => (await media(page)).paused).toBe(false);
  await page.keyboard.press("ArrowRight");
  await expect(preview(page)).toHaveAttribute("data-snapped", "e_0004");
  await expect(preview(page)).toHaveAttribute("data-t", "15.5");
  await expect(preview(page)).toHaveCount(0, { timeout: 3_000 });
  await expect.poll(async () => (await media(page)).paused).toBe(false);
  const t = (await media(page)).t;
  expect(t).toBeGreaterThanOrEqual(15.45);
  expect(t).toBeLessThan(16.5);
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
