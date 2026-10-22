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
    () =>
      (window as unknown as { __replayMockCalls?: MockCall[] })
        .__replayMockCalls ?? [],
  );
}

export async function video(page: Page) {
  return page.evaluate(() => {
    const v = document.querySelector<HTMLVideoElement>('[data-testid="video"]');
    return v
      ? {
          currentTime: v.currentTime,
          paused: v.paused,
          readyState: v.readyState,
        }
      : null;
  });
}

/** The <video> with its source, for the ways to watch and the broadcast swap. */
export async function media(page: Page) {
  return page.evaluate(() => {
    const v = document.querySelector<HTMLVideoElement>('[data-testid="video"]');
    return v
      ? {
          t: v.currentTime,
          paused: v.paused,
          src: v.currentSrc,
          ready: v.readyState,
          muted: v.muted,
        }
      : { t: -1, paused: true, src: "", ready: 0, muted: true };
  });
}

/** [scaleX, scaleY, translateX, translateY] of the follow-cam transform layer. */
export async function transform(page: Page): Promise<number[]> {
  return page.evaluate(() => {
    const el = document.querySelector('[data-testid="player-transform"]');
    const m = el
      ? new DOMMatrix(getComputedStyle(el).transform)
      : new DOMMatrix();
    return [m.a, m.d, m.e, m.f];
  });
}

/** Open the player (it starts playing) and wait for the video to have a frame. */
export async function openWatch(page: Page, id = GAME_ID, query = "") {
  await page.goto(`/tv/${id}${query}`);
  await expect(page.getByTestId("video")).toBeAttached();
  await expect
    .poll(async () => (await video(page))?.readyState ?? 0, { timeout: 15_000 })
    .toBeGreaterThanOrEqual(2);
}

/** Do more → Follow player (→ Pick another player, once someone is picked): the video
 *  pauses and the markers over the players are pickable. */
export async function enterSelectMode(page: Page) {
  if (!(await page.getByTestId("domore").count())) await openDoMore(page);
  const picked = await page
    .getByTestId("action-follow")
    .getAttribute("data-children");
  await menuTo(
    page,
    picked && picked !== "0" ? "follow-pick" : "action-follow",
  );
  await page.keyboard.press("Enter");
  await expect.poll(async () => (await video(page))?.paused).toBe(true);
  await expect(
    page.locator('[data-testid^="select-box-"]').first(),
  ).toBeVisible();
}

export async function focusedBoxId(page: Page): Promise<string | null> {
  return page.evaluate(() => {
    const el = document.querySelector(
      '[data-testid^="select-box-"][data-focused="true"]',
    );
    return el?.getAttribute("data-player-id") ?? null;
  });
}

/** The Do more tile a sub-row item sits behind: the ways behind Watch, Pick another
 *  player, Spotlight, Tag and Link behind Follow player, the angle thumbnails behind Angles. */
export function parentTile(id: string): string | null {
  if (id.startsWith("way-")) return "menu-watch";
  if (
    id.startsWith("follow-") ||
    ["action-spotlight", "action-tag", "action-link-profile"].includes(id)
  )
    return "action-follow";
  if (id.startsWith("angle-")) return "nav-replays";
  if (id.startsWith("pov-")) return "action-pov";
  return null;
}

/** Do more: the remote's Menu key (`m`), or Up while following (Menu is the player card
 *  there, D-83). */
async function openDoMore(page: Page) {
  const following = await page
    .locator('[data-testid="watch"][data-mode="follow"]')
    .count();
  await page.keyboard.press(following ? "ArrowUp" : "m");
}

/** Open Do more with the remote's Menu key (`m`; Up does the same from the transport) and
 *  reach tile `id` with Left/Right, through its parent's row when it has one. */
export async function menuTo(page: Page, id: string) {
  const domore = page.getByTestId("domore");
  if (!(await domore.count())) await openDoMore(page);
  await expect(domore).toBeVisible();
  const parent = parentTile(id);
  const row = (await domore.getAttribute("data-row")) ?? "main";
  if (row !== (parent ?? "main")) {
    if (row !== "main") {
      await page.keyboard.press("Escape"); // back to the main row
      await expect(domore).toHaveAttribute("data-row", "main");
    }
    if (parent) {
      await walkTo(page, parent);
      // its row is in (Angles: the play's manifest arrives after the game)
      await expect(page.getByTestId(parent)).not.toHaveAttribute(
        "data-children",
        "0",
      );
      await page.keyboard.press("Enter");
      await expect(domore).toHaveAttribute("data-row", parent);
    }
  }
  await walkTo(page, id);
}

async function walkTo(page: Page, id: string) {
  await expect(page.getByTestId(id)).toBeAttached();
  for (const key of ["ArrowRight", "ArrowLeft"]) {
    for (let i = 0; i < 16 && (await focusedMenuItem(page)) !== id; i++) {
      await page.keyboard.press(key);
    }
  }
  await expect(page.getByTestId(id)).toHaveAttribute("data-focused", "true");
}

/** The focused Do more tile's testID. */
export async function focusedMenuItem(page: Page): Promise<string | null> {
  return page.evaluate(
    () =>
      document
        .querySelector('[data-testid="domore"] [data-focused="true"]')
        ?.getAttribute("data-testid") ?? null,
  );
}

/** Hold an arrow like a remote: a keydown, repeats every `every` ms for `ms`, the keyup. */
export async function hold(page: Page, key: string, ms: number, every = 120) {
  await page.keyboard.down(key);
  for (let t = every; t < ms; t += every) {
    await page.waitForTimeout(every);
    await page.keyboard.down(key);
  }
  await page.keyboard.up(key);
}

/** Every video 404s, and live 50 ms intervals (the screens' "wait for duration()"
 *  pollers) are counted; read the count with `pollers`. Call before `goto`. */
export async function failVideoAndCountPollers(page: Page) {
  await page.route(/\/mock\/wide\.mp4/, (route) =>
    route.fulfill({ status: 404 }),
  );
  await page.addInitScript(() => {
    const live = new Set<number>();
    const set = window.setInterval.bind(window);
    const clear = window.clearInterval.bind(window);
    Object.assign(window, { __pollers: live });
    window.setInterval = ((
      fn: TimerHandler,
      ms?: number,
      ...args: unknown[]
    ) => {
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
  page.evaluate(
    () => (window as unknown as { __pollers: Set<number> }).__pollers.size,
  );

/** No rendered text below 24 px at 1080p (NF-01). */
export async function smallText(page: Page) {
  return page.evaluate(() =>
    [...document.querySelectorAll("div, span")]
      .filter((el) =>
        [...el.childNodes].some(
          (n) => n.nodeType === 3 && n.textContent?.trim(),
        ),
      )
      .map((el) => ({
        text: el.textContent,
        size: parseFloat(getComputedStyle(el).fontSize),
      }))
      .filter((x) => x.size < 24),
  );
}
