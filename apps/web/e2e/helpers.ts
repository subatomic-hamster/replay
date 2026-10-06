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

/** Watch's action menu: ArrowUp opens it at Library; Right along the top row, and when
 *  `id` lives in a group (its `data-group`), Right to the group, Enter to open it, then
 *  Right along the group's row. D-pad only. */
export async function menuTo(page: Page, id: string) {
  await page.keyboard.press("ArrowUp");
  await expect(page.getByTestId("nav-library")).toHaveAttribute("data-focused", "true");
  await expect(page.getByTestId(id)).toBeAttached();
  const group = await page.getByTestId(id).getAttribute("data-group");
  if (group) {
    await walkTo(page, group);
    await page.keyboard.press("Enter");
  }
  await walkTo(page, id);
}

async function walkTo(page: Page, id: string) {
  for (let i = 0; i < 12; i++) {
    if ((await page.getByTestId(id).getAttribute("data-focused")) === "true") break;
    await page.keyboard.press("ArrowRight");
  }
  await expect(page.getByTestId(id)).toHaveAttribute("data-focused", "true");
}

/** Every Watch menu row (top + each group) fits in one line at 1080p: all its visible
 *  items share a top edge and the bar stays above the picture's top fifth. */
export async function menuRowsOneLine(
  page: Page,
): Promise<{ spread: number; bottom: number; height: number; n: number }> {
  return page.evaluate(() => {
    const rects = [...document.querySelectorAll<HTMLElement>('[data-testid^="nav-"], [data-testid^="action-"], [data-testid^="menu-"]')]
      .filter((el) => el.offsetParent !== null && !el.getAttribute("data-testid")?.startsWith("menu-row"))
      .map((el) => el.getBoundingClientRect());
    const tops = rects.map((r) => r.top);
    return {
      spread: Math.max(...tops) - Math.min(...tops),
      bottom: Math.max(...rects.map((r) => r.bottom)),
      height: Math.min(...rects.map((r) => r.height)),
      n: rects.length,
    };
  });
}

export async function focusedMenuItem(page: Page): Promise<string | null> {
  return page.evaluate(() => {
    const el = document.querySelector(
      '[data-testid^="nav-"][data-focused="true"], [data-testid^="action-"][data-focused="true"], [data-testid^="menu-"][data-focused="true"]',
    );
    return el?.getAttribute("data-testid") ?? null;
  });
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
