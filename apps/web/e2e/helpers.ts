import { expect, type Page } from "@playwright/test";

export const FRAME = 1 / 30;
export const GAME_ID = "g_mock01";
/** A net sport: one court variant, and `sport_ui.review` lists only the heatmap. */
export const NET_GAME_ID = "g_pickle4";

export interface MockCall {
  method: string;
  path: string;
  body?: unknown;
}

export async function mockCalls(page: Page): Promise<MockCall[]> {
  return page.evaluate(
    () => (window as unknown as { __replayMockCalls?: MockCall[] }).__replayMockCalls ?? [],
  );
}

export async function video(page: Page) {
  return page.evaluate(() => {
    const v = document.querySelector<HTMLVideoElement>('[data-testid="video"]');
    if (!v) return null;
    return {
      currentTime: v.currentTime,
      duration: v.duration,
      paused: v.paused,
      readyState: v.readyState,
      ended: v.ended,
      src: v.currentSrc,
    };
  });
}

export async function transform(page: Page): Promise<string> {
  return page.evaluate(() => {
    const el = document.querySelector('[data-testid="player-transform"]');
    return el ? getComputedStyle(el).transform : "none";
  });
}

/** Open the fixture game and wait until the media is actually decodable. */
export async function openWatch(page: Page, id = GAME_ID) {
  await page.goto(`/tv/${id}`);
  await expect(page.getByTestId("video")).toBeAttached();
  await expect
    .poll(async () => (await video(page))?.readyState ?? 0, { timeout: 15_000 })
    .toBeGreaterThanOrEqual(2);
}

/** Watch's top row: ArrowUp opens it at Library, then Right until `id` has focus. */
export async function menuTo(page: Page, id: string) {
  await page.keyboard.press("ArrowUp");
  await expect(page.getByTestId("nav-library")).toHaveAttribute("data-focused", "true");
  await expect(page.getByTestId(id)).toBeAttached();
  for (let i = 0; i < 16; i++) {
    if ((await page.getByTestId(id).getAttribute("data-focused")) === "true") break;
    await page.keyboard.press("ArrowRight");
  }
  await expect(page.getByTestId(id)).toHaveAttribute("data-focused", "true");
}

/** No rendered text below 24 px at 1080p (NF-01). */
export async function smallText(page: Page) {
  return page.evaluate(() =>
    [...document.querySelectorAll("div, span, p, li, td, th, h1, h2")]
      .filter((el) => [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent?.trim()))
      .map((el) => ({ text: el.textContent, size: parseFloat(getComputedStyle(el).fontSize) }))
      .filter((x) => x.size < 24),
  );
}

/** Play briefly, then pause — which is what opens select mode (W3). */
export async function enterSelectMode(page: Page) {
  await page.keyboard.press("Space");
  await expect.poll(async () => (await video(page))?.paused).toBe(false);
  await page.keyboard.press("Space");
  await expect.poll(async () => (await video(page))?.paused).toBe(true);
  await expect(page.locator('[data-testid^="select-box-"]').first()).toBeVisible();
}

export async function focusedBoxId(page: Page): Promise<string | null> {
  return page.evaluate(() => {
    const el = document.querySelector('[data-testid^="select-box-"][data-focused="true"]');
    return el?.getAttribute("data-player-id") ?? null;
  });
}
