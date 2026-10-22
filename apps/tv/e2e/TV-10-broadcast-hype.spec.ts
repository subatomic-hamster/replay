// M13 in the player: Commentary (Do more) turns on the broadcast rendition (M6, with sound,
// same media time) and the commentary captions synced to media time (M7). Mock fixture:
// g_mock01 has a broadcast rendition (wide.mp4?rendition=broadcast) and a commentary
// script; g_pickle4 has neither. The hype meter left the court line in the redesign; hype
// peaks are the Highlights way to watch now (TV-22).
import { expect, test } from "@playwright/test";
import {
  captionAt,
  fmtClock,
  hypeBars,
  listWindow,
  nextPeak,
  nudgeTrim,
  rallyAtCondensed,
  rallyOrder,
  type RallyDoc,
} from "../../../packages/tv-core/src/discovery";
import { boxColumns } from "../../../packages/tv-core/src/display";
import { GAME_ID, media, menuTo, openWatch } from "./helpers";

test("TV-10 pure helpers: hype bars, peaks, captions, trim, rallies, windows, box columns", () => {
  expect(hypeBars([0, 0.2, 0.9, 0.1, 0, 0.5], 3)).toEqual([0.2, 0.9, 0.5]); // max-pooled
  expect(hypeBars([], 4)).toEqual([]);
  const cands = [
    { t: 14.5, score: 0.95 },
    { t: 3.5, score: 0.8 },
  ];
  expect(nextPeak(cands, 0)).toBe(0.5);
  expect(nextPeak(cands, 0.5)).toBe(11.5);
  expect(nextPeak(cands, 11.5)).toBe(0.5); // wraps
  expect(nextPeak([], 3)).toBeNull();

  const lines = [
    { t: 1, text: "a", audio_t: 1, audio_s: 1.8 },
    { t: 3, text: "b" },
  ];
  expect(captionAt(lines, 0.5)).toBeNull();
  expect(captionAt(lines, 2)?.text).toBe("a");
  expect(captionAt(lines, 2.9)).toBeNull();
  expect(captionAt(lines, 5.5)?.text).toBe("b"); // no audio: CAPTION_S = 3
  expect(captionAt(lines, 6.1)).toBeNull();

  expect(nudgeTrim({ t_start: 4, t_end: 10 }, "start", -0.5, 20)).toEqual({
    t_start: 3.5,
    t_end: 10,
  });
  expect(nudgeTrim({ t_start: 0.2, t_end: 10 }, "start", -0.5, 20)).toEqual({
    t_start: 0,
    t_end: 10,
  });
  expect(nudgeTrim({ t_start: 4, t_end: 5 }, "start", 0.5, 20)).toEqual({
    t_start: 4,
    t_end: 5,
  }); // ≥ 1 s
  expect(nudgeTrim({ t_start: 4, t_end: 19.8 }, "end", 0.5, 20)).toEqual({
    t_start: 4,
    t_end: 20,
  });
  expect(nudgeTrim({ t_start: 4, t_end: 5 }, "end", -0.5, 20)).toEqual({
    t_start: 4,
    t_end: 5,
  });

  const doc: RallyDoc = {
    n: 3,
    longest: ["r2", "r1"],
    condensed: { status: "done", url: "x" },
    rallies: [
      {
        id: "r1",
        n: 1,
        event_id: "a",
        t_start: 1,
        t_end: 6,
        duration_s: 5,
        shots: 6,
        condensed_t: 0,
      },
      {
        id: "r3",
        n: 3,
        event_id: "c",
        t_start: 17,
        t_end: 19,
        duration_s: 2,
        shots: 0,
        condensed_t: 12,
      },
      {
        id: "r2",
        n: 2,
        event_id: "b",
        t_start: 8,
        t_end: 16,
        duration_s: 8,
        shots: 9,
        condensed_t: 5.5,
      },
    ],
  };
  expect(rallyOrder(doc, "time").map((r) => r.id)).toEqual(["r1", "r2", "r3"]);
  expect(rallyOrder(doc, "longest").map((r) => r.id)).toEqual([
    "r2",
    "r1",
    "r3",
  ]);
  expect(rallyAtCondensed(doc.rallies, 0)?.id).toBe("r1");
  expect(rallyAtCondensed(doc.rallies, 6)?.id).toBe("r2");
  expect(rallyAtCondensed(doc.rallies, 13)?.id).toBe("r3");

  expect(fmtClock(3.5)).toBe("0:03.5");
  expect(fmtClock(59.96)).toBe("1:00.0");
  expect([
    listWindow(0, 10, 5),
    listWindow(5, 10, 5),
    listWindow(9, 10, 5),
    listWindow(2, 3, 5),
  ]).toEqual([0, 3, 5, 0]);

  const cols = (available: string[], extra: object) =>
    boxColumns({
      available,
      box_score: [
        { player_id: "p1", name: null, attempts: 1, makes: 1, ...extra },
      ],
      shots: [],
    }).map((c) => c.label);
  expect(cols([], {})).toEqual(["Att", "Made", "Conf"]);
  expect(cols(["shots", "steals"], { points: 2, distance_m: 120 })).toEqual([
    "Att",
    "Made",
    "Pts",
    "Stl",
    "Dist m",
    "Conf",
  ]);
});

test("TV-10 Commentary on: the broadcast rendition at the same media time, with sound", async ({
  page,
}) => {
  await openWatch(page);
  await expect
    .poll(async () => (await media(page)).t, { timeout: 10_000 })
    .toBeGreaterThan(1.5);

  await menuTo(page, "action-captions");
  await expect(page.getByTestId("action-captions")).toHaveAttribute(
    "data-on",
    "false",
  );
  const before = (await media(page)).t;
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("watch")).toHaveAttribute(
    "data-broadcast",
    "true",
  );
  await expect(page.getByTestId("action-captions")).toHaveAttribute(
    "data-on",
    "true",
  );
  await expect
    .poll(async () => {
      const m = await media(page);
      return m.src.includes("rendition=broadcast") && m.ready >= 2;
    })
    .toBe(true);
  const after = await media(page);
  expect(after.t).toBeGreaterThan(before - 0.1); // resumed where the wide shot was
  expect(after.t).toBeLessThan(before + 3);
  expect(after.muted).toBe(false); // the broadcast mix plays with sound
  await expect.poll(async () => (await media(page)).paused).toBe(false);

  // Off: back to the muted wide shot, still at the same place.
  const t1 = (await media(page)).t;
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("watch")).toHaveAttribute(
    "data-broadcast",
    "false",
  );
  await expect
    .poll(async () => (await media(page)).src)
    .toMatch(/\/mock\/wide\.mp4$/);
  await expect
    .poll(async () => (await media(page)).ready)
    .toBeGreaterThanOrEqual(2);
  expect((await media(page)).t).toBeGreaterThan(t1 - 0.1);
  expect((await media(page)).muted).toBe(true);
});

test("TV-10 a game with no commentary or broadcast has no Commentary tile", async ({
  page,
}) => {
  await openWatch(page, "g_pickle4");
  await page.keyboard.press("ArrowUp"); // Up from the transport opens Do more
  await expect(page.getByTestId("domore")).toBeVisible();
  await expect(page.getByTestId("nav-phone")).toBeAttached();
  await expect(page.getByTestId("action-captions")).toHaveCount(0);
  await expect(page.getByTestId("watch")).toHaveAttribute(
    "data-broadcast",
    "false",
  );
  expect((await media(page)).src).toMatch(/\/mock\/wide\.mp4$/);
});

test("TV-10 Commentary captions follow media time", async ({ page }) => {
  await page.goto(`/tv/${GAME_ID}?t=3.2`);
  await expect
    .poll(async () => (await media(page)).t, { timeout: 15_000 })
    .toBeGreaterThan(3.1);
  await page.keyboard.press("Space"); // pause inside "Marcus scores two." (3–4.5 s)
  await expect.poll(async () => (await media(page)).paused).toBe(true);
  await expect(page.getByTestId("caption")).toHaveCount(0); // off by default

  await menuTo(page, "action-captions");
  await page.keyboard.press("Enter");
  await page.keyboard.press("Escape"); // close Do more: captions hide while a layer is open
  await expect(page.getByTestId("caption")).toHaveText("Marcus scores two.");

  await page.keyboard.press("]"); // the next moment's start, 6.5 s: between lines
  await expect.poll(async () => (await media(page)).t).toBeCloseTo(6.5, 1);
  await expect(page.getByTestId("caption")).toHaveCount(0);
  await page.keyboard.press("Space"); // play into the 8 s line
  await expect(page.getByTestId("caption")).toHaveText(
    "Player 2 shoots, no good.",
    { timeout: 8_000 },
  );
});
