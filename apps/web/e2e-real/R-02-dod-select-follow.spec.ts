// §6.3 DoD line 2: "select -> follow -> back works for every on-court player in a
// 5-minute stretch of real footage". Walks every select box at four timestamps of the
// 240 s Kennesaw clip with the D-pad only, and writes the result table next to the
// screenshots for samples/real/RESULTS.md.
//
//   REPLAY_E2E_REAL=1 pnpm exec playwright test --project=real R-02
import { expect, test, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { API, SHOTS, findGame, transform, videoState, waitForVideo } from "./helpers";

const TITLE = process.env.REPLAY_E2E_REAL_TITLE ?? "Kennesaw 240";
const TIMESTAMPS = [30, 90, 150, 210];
const MAX_PRESSES = 20;
const DIRS = ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"] as const;

type Row = {
  t: number;
  player: string;
  reached: boolean;
  presses: number;
  followed: boolean;
  seekFree: boolean;
  backToWide: boolean;
};

async function boxes(page: Page) {
  return page.evaluate(() =>
    [...document.querySelectorAll<HTMLElement>('[data-testid^="select-box-"]')].map((el) => {
      const r = el.getBoundingClientRect();
      return {
        id: el.dataset.playerId!,
        cx: r.x + r.width / 2,
        cy: r.y + r.height / 2,
        focused: el.dataset.focused === "true",
      };
    }),
  );
}

/** Drive the spatial-focus algorithm to `target` with arrows only. Returns the number
 *  of presses it took, or -1 if it is unreachable inside MAX_PRESSES. */
async function walkTo(page: Page, target: string): Promise<number> {
  const tried = new Map<string, Set<string>>();
  for (let presses = 0; presses <= MAX_PRESSES; presses++) {
    let now = await boxes(page);
    let cur = now.find((b) => b.focused);
    if (!cur) {
      // Nothing focused at all: one press has to seed it (E-11), and it counts.
      await page.keyboard.press("ArrowRight");
      presses++;
      now = await boxes(page);
      cur = now.find((b) => b.focused);
      if (!cur) return -1;
    }
    if (cur.id === target) return presses;
    const to = now.find((b) => b.id === target);
    if (!to) return -1;
    const dx = to.cx - cur.cx;
    const dy = to.cy - cur.cy;
    const x = dx > 0 ? "ArrowRight" : "ArrowLeft";
    const y = dy > 0 ? "ArrowDown" : "ArrowUp";
    const order =
      Math.abs(dx) > Math.abs(dy)
        ? [x, y, ...DIRS.filter((d) => d !== x && d !== y)]
        : [y, x, ...DIRS.filter((d) => d !== x && d !== y)];
    const seen = tried.get(cur.id) ?? new Set<string>();
    tried.set(cur.id, seen);
    let moved = false;
    for (const dir of order) {
      if (seen.has(dir) || presses >= MAX_PRESSES) continue;
      seen.add(dir);
      await page.keyboard.press(dir);
      presses++;
      const after = (await boxes(page)).find((b) => b.focused);
      if (after && after.id !== cur.id) {
        moved = true;
        break;
      }
    }
    if (!moved) return -1;
  }
  return -1;
}

/** Paused wide shot at `t`, in select mode, with the box set settled — the tracks cache
 *  streams 10 s chunks, so the overlay can be briefly empty right after a seek. */
async function selectAt(page: Page, t: number): Promise<string[]> {
  await page.evaluate((to) => {
    document.querySelector<HTMLVideoElement>('[data-testid="video"]')!.currentTime = to;
  }, t);
  await expect.poll(async () => (await videoState(page))?.currentTime ?? -1).toBeCloseTo(t, 0);
  let last = "";
  for (let i = 0; i < 40; i++) {
    const ids = (await boxes(page)).map((b) => b.id).sort();
    if (ids.length && ids.join() === last) return ids;
    last = ids.join();
    await page.waitForTimeout(250);
  }
  return last ? last.split(",") : [];
}

test("R-02 select -> follow -> back for every on-court player at 30/90/150/210 s", async ({
  page,
}) => {
  test.setTimeout(900_000);
  const gameId = await findGame(page, TITLE);
  test.skip(!gameId, `no processed game titled "${TITLE}" on ${API}`);

  await page.goto(`/tv/${gameId}?mode=select&t=${TIMESTAMPS[0]}`);
  await waitForVideo(page);
  const wide = await transform(page);
  const rows: Row[] = [];

  for (const t of TIMESTAMPS) {
    const ids = await selectAt(page, t);
    for (const id of ids) {
      await selectAt(page, t);
      const presses = await walkTo(page, id);
      const row: Row = {
        t,
        player: id,
        reached: presses >= 0,
        presses: Math.max(presses, 0),
        followed: false,
        seekFree: false,
        backToWide: false,
      };
      if (row.reached) {
        const before = (await videoState(page))!.currentTime;
        await page.keyboard.press("Enter");
        await expect(page.getByTestId("followcam-active")).toBeVisible();
        await expect(page.getByTestId("followcam-active")).toHaveAttribute("data-player-id", id);
        await expect.poll(() => transform(page)).not.toBe(wide);
        row.followed = true;
        row.seekFree = Math.abs((await videoState(page))!.currentTime - before) <= 1 / 30 + 1e-6;

        await page.keyboard.press("Escape");
        await expect(page.getByTestId("followcam-active")).toHaveCount(0);
        await expect.poll(() => transform(page)).toBe(wide);
        row.backToWide = true;
        // Escape lands in the wide shot (W4); Space twice pauses back into select mode.
        await page.keyboard.press("Space");
        await page.keyboard.press("Space");
        await expect.poll(async () => (await videoState(page))?.paused).toBe(true);
      }
      rows.push(row);
    }
  }

  fs.mkdirSync(SHOTS, { recursive: true });
  const jobs = await (await page.request.get(`${API}/games/${gameId}`)).json();
  fs.writeFileSync(
    path.join(SHOTS, "dod-select-follow.json"),
    JSON.stringify({ gameId, title: TITLE, duration_s: jobs.video?.duration_s, rows }, null, 1),
  );

  const byT = TIMESTAMPS.map((t) => rows.filter((r) => r.t === t));
  for (const group of byT) expect(group.length, "boxes on court").toBeGreaterThan(0);
  const failed = rows.filter((r) => r.reached && !(r.followed && r.seekFree && r.backToWide));
  expect(failed, "reached players that did not follow/return cleanly").toEqual([]);
});
