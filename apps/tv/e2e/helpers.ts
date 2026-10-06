import { expect, type Page } from "@playwright/test";

export const FRAME = 1 / 30;
export const GAME_ID = "g_mock01";

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
    return v ? { currentTime: v.currentTime, paused: v.paused, readyState: v.readyState } : null;
  });
}

/** [scaleX, scaleY, translateX, translateY] of the follow-cam transform layer. */
export async function transform(page: Page): Promise<number[]> {
  return page.evaluate(() => {
    const el = document.querySelector('[data-testid="player-transform"]');
    const m = el ? new DOMMatrix(getComputedStyle(el).transform) : new DOMMatrix();
    return [m.a, m.d, m.e, m.f];
  });
}

export async function openWatch(page: Page, id = GAME_ID) {
  await page.goto(`/tv/${id}`);
  await expect(page.getByTestId("video")).toBeAttached();
  await expect
    .poll(async () => (await video(page))?.readyState ?? 0, { timeout: 15_000 })
    .toBeGreaterThanOrEqual(2);
}

/** Play briefly, then pause — pausing the wide shot opens select mode (W3). */
export async function enterSelectMode(page: Page) {
  await page.keyboard.press("Enter");
  await expect.poll(async () => (await video(page))?.paused).toBe(false);
  await page.keyboard.press("Enter");
  await expect.poll(async () => (await video(page))?.paused).toBe(true);
  await expect(page.locator('[data-testid^="select-box-"]').first()).toBeVisible();
}

export async function focusedBoxId(page: Page): Promise<string | null> {
  return page.evaluate(() => {
    const el = document.querySelector('[data-testid^="select-box-"][data-focused="true"]');
    return el?.getAttribute("data-player-id") ?? null;
  });
}

/** Open the Watch action row (Up) and walk Right until `id` has focus. */
export async function menuTo(page: Page, id: string) {
  await page.keyboard.press("ArrowUp");
  await expect(page.getByTestId("nav-library")).toHaveAttribute("data-focused", "true");
  for (let i = 0; i < 24 && (await focusedMenuItem(page)) !== id; i++) {
    await page.keyboard.press("ArrowRight");
  }
  await expect(page.getByTestId(id)).toHaveAttribute("data-focused", "true");
}

/** No rendered text below 24 px at 1080p (NF-01). */
export async function smallText(page: Page) {
  return page.evaluate(() =>
    [...document.querySelectorAll("div, span")]
      .filter((el) => [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent?.trim()))
      .map((el) => ({ text: el.textContent, size: parseFloat(getComputedStyle(el).fontSize) }))
      .filter((x) => x.size < 24),
  );
}

export async function focusedMenuItem(page: Page): Promise<string | null> {
  return page.evaluate(() => {
    const el = document.querySelector(
      '[data-testid^="nav-"][data-focused="true"], [data-testid^="action-"][data-focused="true"]',
    );
    return el?.getAttribute("data-testid") ?? null;
  });
}
