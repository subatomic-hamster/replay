// M13 on the web TV: semantic search (POST /search; keyword fallback without an index),
// the per-player advice panel (M7), and the 10-foot text rule on every new screen.
// Mock fixture g_mock01 (basketball) and g_pickle4 (no plays → the search falls back to
// the keyword query route).
import { expect, test } from "@playwright/test";
import { GAME_ID, NET_GAME_ID, menuTo, mockCalls, openWatch, smallText } from "./helpers";

test("S-46 search: a chip runs POST /search; matches first; Enter plays the hit", async ({
  page,
}) => {
  await openWatch(page);
  await menuTo(page, "nav-search");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("search")).toBeVisible();
  await expect(page.locator('[data-chip="Marcus — all shots"]')).toHaveAttribute(
    "data-focused",
    "true",
  );

  await page.keyboard.press("Enter");
  await expect(page.getByTestId("search-interpretation")).toHaveAttribute("data-fallback", "false");
  await expect(page.getByTestId("search-interpretation")).toContainText("ranked by similarity");
  const hits = page.getByTestId("search-hit");
  await expect(hits).toHaveCount(4);
  await expect(hits.nth(0)).toHaveAttribute("data-match", "true");
  await expect(hits.nth(1)).toHaveAttribute("data-match", "true");
  await expect(hits.nth(2)).toHaveAttribute("data-match", "false");
  const post = (await mockCalls(page)).find((c) => c.path === `/games/${GAME_ID}/search`);
  expect(post?.body).toEqual({ text: "Marcus — all shots", k: 8 });

  await expect(hits.nth(0)).toHaveAttribute("data-focused", "true");
  const t0 = Number(await hits.nth(0).getAttribute("data-t-start"));
  await expect
    .poll(() => page.evaluate(() => document.querySelector("video")?.readyState ?? 0), {
      timeout: 15_000,
    })
    .toBeGreaterThanOrEqual(2);
  await page.keyboard.press("Enter");
  await expect
    .poll(() => page.evaluate(() => document.querySelector("video")?.currentTime ?? -1))
    .toBeGreaterThanOrEqual(t0);
  await expect.poll(() => page.evaluate(() => document.querySelector("video")?.paused)).toBe(false);
});

test("S-46 search: free text on the keyboard; no index → keyword fallback, labelled", async ({
  page,
}) => {
  await page.goto(`/tv/${NET_GAME_ID}/search`);
  const chips = page.getByTestId("search-chip");
  // the profile chips arrive after the first render: count once the last one is in
  await expect(page.locator('[data-chip="Bookmarks"]')).toBeVisible();
  const n = await chips.count();
  for (let i = 0; i < n - 1; i++) await page.keyboard.press("ArrowRight");
  await expect(chips.nth(n - 1)).toHaveAttribute("data-chip", "Type a search…");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("search-dialog")).toBeVisible();
  await page.keyboard.press("Enter"); // a
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowDown"); // control row, col 0 = SPACE
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowRight"); // SAVE
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("search-interpretation")).toHaveAttribute("data-fallback", "true");
  await expect(page.getByTestId("search-interpretation")).toContainText("keyword match");
  await expect(page.getByTestId("search-empty")).toBeVisible();
});

test("S-47 advice: per-player lines, labelled as written from that player's stats", async ({
  page,
}) => {
  await openWatch(page);
  await menuTo(page, "nav-advice");
  await page.keyboard.press("Enter");
  const panel = page.getByTestId("advice-panel");
  await expect(panel).toHaveAttribute("data-player-id", "p1");
  await expect(page.getByTestId("advice-line").first()).toContainText("Marcus made 2 of 2 shots");
  await expect(page.getByTestId("advice-source")).toContainText("written from this player's stats");

  await page.keyboard.press("ArrowRight");
  await expect(page.getByTestId("advice-player-p2")).toHaveAttribute("data-focused", "true");
  await expect(panel).toHaveAttribute("data-player-id", "p2");
  await expect(page.getByTestId("advice-line").first()).toContainText("made 0 of 1 shots");
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("watch")).toBeVisible();
});

test("S-49 10-foot UI: no rendered text below 24 px on the M13 screens", async ({ page }) => {
  for (const path of [
    `/tv/${GAME_ID}`,
    `/tv/${GAME_ID}/clips`,
    `/tv/${NET_GAME_ID}/rallies`,
    `/tv/${GAME_ID}/search`,
    `/tv/${GAME_ID}/advice`,
    `/tv/${GAME_ID}/review`,
  ]) {
    await page.goto(path);
    await page.waitForTimeout(600);
    expect(await smallText(page), path).toEqual([]);
  }
});
