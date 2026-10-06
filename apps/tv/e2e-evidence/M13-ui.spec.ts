// M13 evidence: the RN TV app (web build) on the M5/M6/M7/M11 features, against a running
// services/api (REPLAY_TV_API=<base>) serving SYNTHETIC games the worker processed, or the
// mock fixture (REPLAY_TV_API=mock). Saves a 1080p screenshot per step to
// REPLAY_TV_EVIDENCE_DIR. Assertions are structural — the pipeline decides how many
// clips, rallies and hits there are; the screenshots are the evidence.
//
//   REPLAY_TV_EVIDENCE_GAME      a game with a broadcast rendition (default g_mock01)
//   REPLAY_TV_EVIDENCE_NET_GAME  a game with rallies (default g_pickle4)
import { expect, test, type Page } from "@playwright/test";
import path from "node:path";
import { menuTo, openWatch } from "../e2e/helpers";

const API = process.env.REPLAY_TV_API ?? "mock";
const LIVE = API !== "mock";
const OUT = process.env.REPLAY_TV_EVIDENCE_DIR ?? "test-results/evidence-m13";
const GAME = process.env.REPLAY_TV_EVIDENCE_GAME ?? "g_mock01";
const NET_GAME = process.env.REPLAY_TV_EVIDENCE_NET_GAME ?? "g_pickle4";
const RENDER_TIMEOUT = 180_000; // a real 9:16 export / condensed render on CPU

async function shot(page: Page, name: string) {
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(OUT, `${name}.png`) });
}

async function media(page: Page) {
  return page.evaluate(() => {
    const v = document.querySelector<HTMLVideoElement>('[data-testid="video"]');
    return v ? { t: v.currentTime, paused: v.paused, ready: v.readyState, src: v.currentSrc } : null;
  });
}

test.describe.configure({ mode: "serial" });

test("M13 watch: broadcast + commentary captions + hype meter", async ({ page }) => {
  test.setTimeout(120_000);
  await openWatch(page, GAME);
  await expect(page.getByTestId("hype-meter")).toBeVisible({ timeout: 15_000 });

  await menuTo(page, "action-broadcast");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("watch")).toHaveAttribute("data-broadcast", "true");
  await expect.poll(async () => (await media(page))?.src ?? "").toContain("broadcast");
  await expect.poll(async () => (await media(page))?.ready ?? 0, { timeout: 30_000 }).toBeGreaterThanOrEqual(2);
  await page.keyboard.press("ArrowDown"); // close the row (a toggle leaves it open)
  await menuTo(page, "action-captions");
  await page.keyboard.press("Enter");
  await page.keyboard.press("ArrowDown"); // close the row
  await page.keyboard.press("Enter"); // play
  await expect(page.getByTestId("caption")).toBeVisible({ timeout: 30_000 });
  await page.keyboard.press("Enter"); // pause on the caption
  await shot(page, "01-watch-broadcast-captions");

  await menuTo(page, "action-hype-peak");
  await page.keyboard.press("Enter");
  await page.waitForTimeout(800);
  await shot(page, "02-watch-hype-peak");
});

test("M13 clips: a phone tap, the list, the D-pad trim and the 9:16 share", async ({ page }) => {
  test.setTimeout(RENDER_TIMEOUT + 60_000);
  if (LIVE) {
    // The phone companion's POST, at the end of the first play: D-50 cuts that play.
    const plays = await (await page.request.get(`${API}/games/${GAME}/plays`)).json();
    const first = plays.plays[0];
    const tap = await page.request.post(`${API}/games/${GAME}/triggers`, {
      data: { t: first.t_end + 0.3 },
    });
    expect(tap.status()).toBe(201);
    expect((await tap.json()).clip?.play_id).toBe(first.id);
  }
  await page.goto(`/tv/${GAME}/clips`);
  const cards = page.getByTestId("clip-card");
  await expect(cards.first()).toBeVisible({ timeout: 15_000 });
  await expect(page.locator('[data-testid="clip-card"][data-trigger="tap"]').first()).toBeVisible();
  await page.waitForTimeout(1500); // the focused clip previews
  await shot(page, "03-clips");

  await page.keyboard.press("Enter");
  await page.keyboard.press("ArrowLeft"); // start −0.5 s
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowRight"); // end +0.5 s
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("Enter"); // Save trim
  await expect(page.getByTestId("trim-note")).toHaveText("Trim saved");
  await shot(page, "04-clip-trim");

  await page.keyboard.press("ArrowRight"); // Share 9:16
  await page.keyboard.press("Enter");
  const panel = page.getByTestId("export-panel");
  await expect(panel).toBeVisible();
  await expect(panel).toHaveAttribute("data-status", "done", { timeout: RENDER_TIMEOUT });
  await expect.poll(async () =>
    page.evaluate(() => {
      const v = document.querySelector<HTMLVideoElement>('[data-testid="vertical-preview"] video');
      return v?.readyState ?? 0;
    }), { timeout: 30_000 }).toBeGreaterThanOrEqual(2);
  await shot(page, "05-share-9x16");
});

test("M13 search, advice and review", async ({ page }) => {
  test.setTimeout(90_000);
  await page.goto(`/tv/${GAME}/search`);
  await expect(page.getByTestId("search-chip").first()).toBeVisible({ timeout: 15_000 });
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("search-interpretation")).toBeVisible({ timeout: 15_000 });
  await page.waitForTimeout(1000);
  await shot(page, "06-search");

  await page.goto(`/tv/${GAME}/advice`);
  await expect(page.getByTestId("advice-panel")).toBeVisible({ timeout: 15_000 });
  await shot(page, "07-advice");

  await page.goto(`/tv/${GAME}/review`);
  await expect(page.getByTestId("auto-detected-label")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId("review-item").or(page.getByTestId("review-empty"))).toBeVisible();
  await shot(page, "08-review");
});

test("M13 rallies and the condensed game", async ({ page }) => {
  test.setTimeout(RENDER_TIMEOUT + 60_000);
  await page.goto(`/tv/${NET_GAME}/rallies`);
  await expect(page.getByTestId("rally-row").first()).toBeVisible({ timeout: 15_000 });
  await page.keyboard.press("ArrowRight"); // Longest
  await page.keyboard.press("ArrowDown");
  await expect.poll(async () => (await media(page))?.ready ?? 0, { timeout: 30_000 }).toBeGreaterThanOrEqual(2);
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("rally-counter")).toBeVisible();
  await page.waitForTimeout(1200);
  await shot(page, "09-rallies-longest");

  await page.keyboard.press("ArrowUp");
  await page.keyboard.press("ArrowRight"); // Condensed game
  await expect(page.getByTestId("rally-tab-condensed")).toHaveAttribute("data-focused", "true");
  // not rendered yet (a re-run finds it done, and the status line gone): ask for it
  if (await page.getByTestId("condensed-status").count()) await page.keyboard.press("Enter");
  await expect(page.getByTestId("rallies")).toHaveAttribute("data-condensed", "true", {
    timeout: RENDER_TIMEOUT,
  });
  await expect.poll(async () => (await media(page))?.ready ?? 0, { timeout: 30_000 }).toBeGreaterThanOrEqual(2);
  await page.keyboard.press("Enter"); // play the condensed game
  await expect(page.getByTestId("rally-counter")).toBeVisible({ timeout: 15_000 });
  await page.waitForTimeout(1500);
  await shot(page, "10-condensed-game");
});
