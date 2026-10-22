// Do more (docs/ux/redesign.md "Do more"): the tiles in the spec's order, a row that keeps
// to the 96/54 px safe zone (what does not fit peeks at the edge and scrolls in with focus),
// the 24 px text floor, and a tile whose feature is still processing: "Getting ready,
// about N min", focusable but not selectable.
import { expect, test, type Page } from "@playwright/test";
import { openWatch, smallText } from "./helpers";

const ORDER = [
  "action-follow",
  "nav-replays",
  "action-free-view",
  "action-pov",
  "menu-watch",
  "nav-review",
  "action-captions",
  "nav-phone",
  "action-bookmark",
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
    const clip = tiles[0]?.parentElement?.parentElement?.parentElement;
    const c = clip!.getBoundingClientRect();
    return {
      clip: { left: c.left, right: c.right },
      tiles: tiles.map((el) => {
        const r = el.getBoundingClientRect();
        return {
          id: el.getAttribute("data-testid"),
          focused: el.getAttribute("data-focused") === "true",
          left: r.left,
          right: r.right,
          top: r.top,
          // what shows through the clip
          shown: Math.max(
            0,
            Math.min(r.right, c.right) - Math.max(r.left, c.left),
          ),
          width: r.width,
        };
      }),
    };
  });

test("TV-24 Do more: spec order, inside the safe zone, the next tile peeks and scrolls in", async ({
  page,
}) => {
  await openWatch(page);
  await page.keyboard.press("Space"); // pause: nothing moves while measuring
  await page.keyboard.press("ArrowUp");
  await expect(page.getByTestId("domore")).toBeVisible();
  await expect.poll(() => rowIds(page)).toEqual(ORDER);
  // The old screens' tiles went to the phone.
  for (const id of ["nav-clips", "nav-search", "nav-advice", "nav-pair"])
    await expect(page.getByTestId(id)).toHaveCount(0);
  await page.waitForTimeout(300); // the 150 ms slide

  // The clip is the safe zone plus room for the focus ring; never off the screen.
  const first = await boxes(page);
  expect(first.clip.left).toBeGreaterThanOrEqual(96 - 24);
  expect(first.clip.right).toBeLessThanOrEqual(1920 - 96 + 24);
  const whole = first.tiles.filter((t) => t.shown >= t.width - 1);
  const cut = first.tiles.filter((t) => t.shown > 0 && t.shown < t.width - 1);
  // whole tiles sit in the safe zone (the focused one's 1.06 scale aside)
  for (const t of whole) {
    expect(t.left, t.id!).toBeGreaterThanOrEqual(96 - 12);
    expect(t.right, t.id!).toBeLessThanOrEqual(1920 - 96 + 24);
    expect(t.top, t.id!).toBeGreaterThanOrEqual(54);
  }
  expect(whole.length).toBeGreaterThanOrEqual(5);
  expect(cut.map((t) => t.id)).toEqual([ORDER[whole.length]]); // one peeks
  expect(cut[0].shown).toBeLessThan(cut[0].width * 0.6);
  expect(await smallText(page)).toEqual([]);

  // Right to the end: the focused tile is always whole and inside.
  for (let i = 1; i < ORDER.length; i++) {
    await page.keyboard.press("ArrowRight");
    await expect(page.getByTestId(ORDER[i])).toHaveAttribute(
      "data-focused",
      "true",
    );
    await page.waitForTimeout(200);
    const f = (await boxes(page)).tiles.find((t) => t.focused)!;
    expect(f.shown, f.id!).toBeGreaterThanOrEqual(f.width - 1);
    expect(f.left).toBeGreaterThanOrEqual(96 - 24);
    expect(f.right).toBeLessThanOrEqual(1920 - 96 + 24);
  }
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
