// Do more (UI pass §4.3): at most 6 tiles in the spec's order, all whole and inside the
// 96/54 px safe zone at once (no peek, no scrolling), the 24 px text floor; following, the
// player's card and "Follow someone else" lead and Commentary steps out; a tile whose
// feature is still processing says "Getting ready, about N min" and cannot be chosen.
import { expect, test, type Page } from "@playwright/test";
import { enterSelectMode, focusedBoxId, openWatch, smallText } from "./helpers";

const ORDER = [
  "action-follow",
  "nav-replays",
  "menu-watch",
  "nav-review",
  "action-captions",
  "nav-phone",
];
const FOLLOWING = [
  "follow-card",
  "follow-pick",
  "nav-replays",
  "menu-watch",
  "nav-review",
  "nav-phone",
];

/** The main row's tile ids, left to right. */
const rowIds = (page: Page) =>
  page.evaluate(() =>
    [...document.querySelectorAll('[data-testid="domore"] [data-focused]')].map(
      (el) => el.getAttribute("data-testid"),
    ),
  );

/** Each tile's box, and the part of it the row's clip lets show. */
const boxes = (page: Page) =>
  page.evaluate(() => {
    const tiles = [
      ...document.querySelectorAll('[data-testid="domore"] [data-focused]'),
    ];
    const c = document
      .querySelector('[data-testid="domore-clip"]')!
      .getBoundingClientRect();
    return {
      clip: { left: c.left, right: c.right },
      tiles: tiles.map((el) => {
        const r = el.getBoundingClientRect();
        return {
          id: el.getAttribute("data-testid"),
          left: r.left,
          right: r.right,
          top: r.top,
          bottom: r.bottom,
          shown: Math.max(
            0,
            Math.min(r.right, c.right) - Math.max(r.left, c.left),
          ),
          width: r.width,
        };
      }),
    };
  });

async function allWhole(page: Page, order: string[]) {
  await expect.poll(() => rowIds(page)).toEqual(order);
  await page.waitForTimeout(300); // the 150 ms slide
  const { clip, tiles } = await boxes(page);
  expect(clip.left).toBeGreaterThanOrEqual(96 - 24);
  expect(clip.right).toBeLessThanOrEqual(1920 - 96 + 24);
  for (const t of tiles) {
    expect(t.shown, t.id!).toBeGreaterThanOrEqual(t.width - 1); // whole: no peek
    expect(t.left, t.id!).toBeGreaterThanOrEqual(96 - 12);
    expect(t.right, t.id!).toBeLessThanOrEqual(1920 - 96 + 12);
    expect(t.top, t.id!).toBeGreaterThanOrEqual(54);
    expect(t.bottom, t.id!).toBeLessThanOrEqual(1080 / 2);
  }
  expect(await smallText(page)).toEqual([]);
  // walking to the end moves nothing: the row never scrolls
  const before = tiles.map((t) => t.left);
  for (let i = 1; i < order.length; i++)
    await page.keyboard.press("ArrowRight");
  await expect(page.getByTestId(order[order.length - 1])).toHaveAttribute(
    "data-focused",
    "true",
  );
  await page.waitForTimeout(200);
  const after = (await boxes(page)).tiles.map((t) => t.left);
  for (let i = 0; i < before.length; i++)
    expect(Math.abs(after[i] - before[i])).toBeLessThan(20); // the 1.06 focus scale aside
}

test("TV-24 Do more: 6 tiles in the spec's order, all whole inside the safe zone", async ({
  page,
}) => {
  await openWatch(page);
  await page.keyboard.press("Space"); // pause: nothing moves while measuring
  await page.keyboard.press("ArrowUp");
  await expect(page.getByTestId("domore")).toBeVisible();
  // The old tiles: the angles family is one tile, Bookmark lives in Moments, the old
  // screens' tiles went to the phone.
  for (const id of [
    "action-free-view",
    "action-pov",
    "action-bookmark",
    "nav-clips",
    "nav-search",
    "nav-advice",
    "nav-pair",
  ])
    await expect(page.getByTestId(id)).toHaveCount(0);
  await expect(page.getByTestId("menu-watch")).toContainText("Highlights");
  await expect(page.getByTestId("nav-replays")).toContainText("Replay angles");
  await allWhole(page, ORDER);
});

test("TV-24 following: the player's card and Follow someone else lead, still 6 whole", async ({
  page,
}) => {
  await openWatch(page);
  await enterSelectMode(page);
  await expect.poll(() => focusedBoxId(page)).not.toBeNull(); // the markers are in
  await page.keyboard.press("Enter"); // follow the focused player
  await expect(page.getByTestId("watch")).toHaveAttribute(
    "data-mode",
    "follow",
  );
  await page.keyboard.press("Space");
  await page.keyboard.press("m");
  await expect(page.getByTestId("domore")).toBeVisible();
  await allWhole(page, FOLLOWING);
});

test("TV-24 a pending tile says when, cannot be chosen, and keeps the layout", async ({
  page,
}) => {
  await openWatch(page, "g_proc03");
  await page.keyboard.press("ArrowUp");
  const follow = page.getByTestId("action-follow");
  await expect(follow).toHaveAttribute("data-pending", "true");
  await expect(follow).toContainText(
    /Getting ready, (about\s\d+\smin|under\sa\sminute)/,
  );
  await expect(follow).toHaveAttribute("data-focused", "true");
  await page.keyboard.press("Enter"); // pending: no row opens, nothing changes
  await expect(page.getByTestId("domore")).toHaveAttribute("data-row", "main");
  await expect(page.getByTestId("watch")).toHaveAttribute("data-mode", "wide");
  await page.waitForTimeout(300);
  const b = (await follow.boundingBox())!;
  expect(b.x).toBeGreaterThanOrEqual(96 - 12);
  expect(await smallText(page)).toEqual([]);
});
