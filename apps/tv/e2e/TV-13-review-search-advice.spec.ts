// M13: the post-game review wired to GET /review/queue + the extended box score (D-48),
// semantic search (POST /search, keyword fallback without an index) and the per-player
// advice panel (M7). Mock fixture g_mock01 (basketball) and g_pickle4 (no plays → the
// search falls back to the keyword route).
import { expect, test } from "@playwright/test";
import { GAME_ID, menuTo, mockCalls, openWatch } from "./helpers";

test("TV-13 review: confidence label, Pts + distance columns, unknown outcomes ringed", async ({
  page,
}) => {
  await page.goto(`/tv/${GAME_ID}/review`);
  // mean of the four shots' confidences (0.82, 0.74, 0.91, 0.55)
  await expect(page.getByTestId("auto-detected-label")).toHaveText(
    /^Auto-detected · mean confidence 0\.7[56]$/,
  );
  const marcus = page.locator(
    '[data-testid="box-score-row"][data-player-id="p1"]',
  );
  await expect(marcus.getByTestId("box-pts")).toHaveText("4");
  await expect(marcus.getByTestId("box-dist")).not.toHaveText("—");
  await expect(page.getByTestId("shot-marker").first()).toHaveAttribute(
    "data-outcome",
    "make",
  );
});

test("TV-13 identity questions: type a name, or merge into a teammate", async ({
  page,
}) => {
  await page.goto(`/tv/${GAME_ID}/review`);
  const item = page.getByTestId("review-item");
  await expect(item).toHaveAttribute("data-kind", "low_confidence");
  await page.keyboard.press("Enter"); // Yes, it was a shot
  await expect(item).toHaveAttribute("data-player-id", "p2");
  await expect(page.getByTestId("review-action-type-a-name")).toHaveAttribute(
    "data-focused",
    "true",
  );
  await expect(page.getByTestId("review-action-same-as-marcus")).toBeVisible();

  await page.keyboard.press("Enter"); // Type a name → on-screen keyboard
  await expect(page.getByTestId("review-name-dialog")).toBeVisible();
  const press = async (key: string, n = 1) => {
    for (let i = 0; i < n; i++) await page.keyboard.press(key);
  };
  await press("Enter"); // A
  await press("ArrowRight");
  await press("Enter"); // B
  await press("ArrowRight", 3);
  await press("Enter"); // E
  await expect(page.getByTestId("review-name-value")).toHaveText("Abe");
  await press("ArrowDown", 3); // control row (col clamps to CANCEL)
  await press("ArrowLeft"); // SAVE
  await press("Enter");
  await expect(page.getByTestId("review-name-dialog")).toHaveCount(0);
  await expect(item).toHaveAttribute("data-player-id", "p3");

  await page.keyboard.press("ArrowRight"); // Same as Marcus
  await page.keyboard.press("Enter");
  await expect(item).toHaveAttribute("data-player-id", "p4");

  const patches = (await mockCalls(page)).filter((c) => c.method === "PATCH");
  expect(patches.map((c) => [c.path, c.body])).toEqual([
    [`/games/${GAME_ID}/events/e_0004`, { confirmed: true }],
    [`/games/${GAME_ID}/players/p2`, { name: "Abe" }],
    [`/games/${GAME_ID}/players/p3`, { merge_into: "p1" }],
  ]);
  // the merged player is gone from the box score
  await expect(
    page.locator('[data-testid="box-score-row"][data-player-id="p3"]'),
  ).toHaveCount(0);
});

test("TV-13 Watch it: an event question opens the play, Back returns to answer it", async ({
  page,
}) => {
  // D-93: "Make or miss?" needs eyes on the shot; the answer is the user's own label
  await page.goto(`/tv/${GAME_ID}/review`);
  const item = page.getByTestId("review-item");
  await expect(item).toHaveAttribute("data-event-id", "e_0004");
  await page.keyboard.press("ArrowRight"); // No
  await page.keyboard.press("ArrowRight"); // Watch it
  await expect(page.getByTestId("review-watch")).toHaveAttribute(
    "data-focused",
    "true",
  );
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("watch")).toBeVisible();
  for (let i = 0; i < 4 && !(await item.isVisible()); i++) {
    await page.keyboard.press("Escape");
    await page.waitForTimeout(300);
  }
  await expect(item).toHaveAttribute("data-event-id", "e_0004");
});

test("TV-13 search: a chip runs POST /search; matches first; Select plays the hit", async ({
  page,
}) => {
  // The Search tile went to the phone (TV-28); the screen stays for its deep link.
  await page.goto(`/tv/${GAME_ID}/search`);
  await expect(page.getByTestId("search")).toBeVisible();

  await page.keyboard.press("Enter"); // "Marcus — all shots"
  await expect(page.getByTestId("search-interpretation")).toHaveAttribute(
    "data-fallback",
    "false",
  );
  await expect(page.getByTestId("search-interpretation")).toContainText(
    "ranked by similarity",
  );
  const hits = page.getByTestId("search-hit");
  await expect(hits).toHaveCount(4);
  await expect(hits.nth(0)).toHaveAttribute("data-match", "true");
  await expect(hits.nth(1)).toHaveAttribute("data-match", "true");
  await expect(hits.nth(2)).toHaveAttribute("data-match", "false");
  const post = (await mockCalls(page)).find(
    (c) => c.path === `/games/${GAME_ID}/search`,
  );
  expect(post?.body).toEqual({ text: "Marcus — all shots", k: 8 });

  await expect(hits.nth(0)).toHaveAttribute("data-focused", "true");
  const t0 = Number(await hits.nth(0).getAttribute("data-t-start"));
  await expect
    .poll(
      () =>
        page.evaluate(() => document.querySelector("video")?.readyState ?? 0),
      { timeout: 15_000 },
    )
    .toBeGreaterThanOrEqual(2);
  await page.keyboard.press("Enter");
  await expect
    .poll(() =>
      page.evaluate(() => document.querySelector("video")?.currentTime ?? -1),
    )
    .toBeGreaterThanOrEqual(t0);
  await expect
    .poll(() => page.evaluate(() => document.querySelector("video")?.paused))
    .toBe(false);
});

test("TV-13 search: free text on the keyboard; no index → keyword fallback, labelled", async ({
  page,
}) => {
  await page.goto(`/tv/g_pickle4/search`);
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
  await expect(page.getByTestId("search-interpretation")).toHaveAttribute(
    "data-fallback",
    "true",
  );
  await expect(page.getByTestId("search-interpretation")).toContainText(
    "keyword match",
  );
  await expect(page.getByTestId("search-empty")).toBeVisible();
});

test("TV-13 advice: per-player lines, labelled as written from that player's stats", async ({
  page,
}) => {
  // Advice is "Tips for players" in the Stats panel now.
  await openWatch(page);
  await menuTo(page, "nav-review");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("stats-panel")).toBeVisible();
  await page.keyboard.press("ArrowDown");
  await expect(page.getByTestId("stats-advice")).toHaveAttribute(
    "data-focused",
    "true",
  );
  await page.keyboard.press("Enter");
  const panel = page.getByTestId("advice-panel");
  await expect(panel).toHaveAttribute("data-player-id", "p1");
  await expect(page.getByTestId("advice-line").first()).toContainText(
    "Marcus made 2 of 2 shots",
  );
  await expect(page.getByTestId("advice-source")).toContainText(
    "written from this player's stats",
  );

  await page.keyboard.press("ArrowRight");
  await expect(page.getByTestId("advice-player-p2")).toHaveAttribute(
    "data-focused",
    "true",
  );
  await expect(panel).toHaveAttribute("data-player-id", "p2");
  await expect(page.getByTestId("advice-line").first()).toContainText(
    "made 0 of 1 shots",
  );
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("watch")).toBeVisible();
});
