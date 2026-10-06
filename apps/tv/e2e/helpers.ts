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

/** Open the Watch action menu (Up) and reach `id` with the D-pad only: Right along the top
 *  row, and when the item lives in a group (its `data-group`), Right to the group, Select
 *  to open it, then Right along the group's row. */
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

/** The visible Watch menu items: `spread` between their top edges (one line: a few px of
 *  sub-pixel/border jitter; a wrap: a whole item height), the lowest bottom edge and the
 *  smallest item height, in CSS px at 1920x1080. */
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

async function walkTo(page: Page, id: string) {
  for (let i = 0; i < 12 && (await focusedMenuItem(page)) !== id; i++) {
    await page.keyboard.press("ArrowRight");
  }
  await expect(page.getByTestId(id)).toHaveAttribute("data-focused", "true");
}

/** Every video 404s, and live 50 ms intervals (the screens' "wait for duration()"
 *  pollers) are counted; read the count with `pollers`. Call before `goto`. */
export async function failVideoAndCountPollers(page: Page) {
  await page.route(/\/mock\/wide\.mp4/, (route) => route.fulfill({ status: 404 }));
  await page.addInitScript(() => {
    const live = new Set<number>();
    const set = window.setInterval.bind(window);
    const clear = window.clearInterval.bind(window);
    Object.assign(window, { __pollers: live });
    window.setInterval = ((fn: TimerHandler, ms?: number, ...args: unknown[]) => {
      const id = set(fn, ms, ...args);
      if (ms === 50) live.add(id);
      return id;
    }) as typeof window.setInterval;
    window.clearInterval = ((id?: number) => {
      if (id !== undefined) live.delete(id);
      clear(id);
    }) as typeof window.clearInterval;
  });
}

export const pollers = (page: Page) =>
  page.evaluate(() => (window as unknown as { __pollers: Set<number> }).__pollers.size);

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
      '[data-testid^="nav-"][data-focused="true"], [data-testid^="action-"][data-focused="true"], [data-testid^="menu-"][data-focused="true"]',
    );
    return el?.getAttribute("data-testid") ?? null;
  });
}
