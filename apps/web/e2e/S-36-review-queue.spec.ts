import { expect, test } from "@playwright/test";
import { GAME_ID, NET_GAME_ID, mockCalls } from "./helpers";

// S-36 confirm, S-37 correct, E-19 confidence indicator, R1/R3 shot chart + box score.
// The queue is GET /review/queue (D-48): each option names the PATCH it sends.
test("S-36 confirming the low-confidence shot PATCHes it; the identity questions follow", async ({
  page,
}) => {
  await page.goto(`/tv/${GAME_ID}/review`);

  const item = page.getByTestId("review-item");
  await expect(item).toBeVisible();
  // E-19: only the sub-threshold, unconfirmed event is queued as an event question.
  await expect(item).toHaveAttribute("data-event-id", "e_0004");
  await expect(item).toHaveAttribute("data-kind", "low_confidence");
  await expect(item).toHaveAttribute("data-confidence", "0.55");
  expect((await mockCalls(page)).some((c) => c.path === `/games/${GAME_ID}/review/queue`)).toBe(
    true,
  );

  await page.keyboard.press("Enter"); // "Yes" is the focused option

  await expect(item).toHaveAttribute("data-kind", "identity");
  const patch = (await mockCalls(page)).filter(
    (c) => c.method === "PATCH" && c.path.includes("/events/e_0004"),
  );
  expect(patch).toHaveLength(1);
  expect(patch[0].body).toEqual({ confirmed: true });
});

test("S-37 No dismisses the event", async ({ page }) => {
  await page.goto(`/tv/${GAME_ID}/review`);
  await expect(page.getByTestId("review-item")).toBeVisible();

  await page.keyboard.press("ArrowRight");
  await expect(page.getByTestId("review-action-no")).toHaveAttribute("data-focused", "true");
  await page.keyboard.press("Enter");

  await expect(page.getByTestId("review-item")).toHaveAttribute("data-kind", "identity");
  const patch = (await mockCalls(page)).filter((c) => c.method === "PATCH");
  expect(patch[0].body).toEqual({ dismissed: true, confirmed: true });
});

test("R1/R3 the shot chart and box score render, labelled auto-detected", async ({ page }) => {
  await page.goto(`/tv/${GAME_ID}/review`);
  // mean of the four shots' confidences (0.82, 0.74, 0.91, 0.55)
  await expect(page.getByTestId("auto-detected-label")).toHaveText(
    /^Auto-detected · mean confidence 0\.7[56]$/,
  );
  await expect(page.getByTestId("shot-chart")).toBeVisible();
  await expect(page.getByTestId("shot-marker")).toHaveCount(4);
  await expect(page.getByTestId("shot-marker").first()).toHaveAttribute("data-outcome", "make");
  await expect(page.getByTestId("box-score-row")).toHaveCount(4);

  const marcus = page.locator('[data-testid="box-score-row"][data-player-id="p1"]');
  await expect(marcus).toContainText("Marcus");
  const cells = await marcus.locator("td").allTextContents();
  expect(cells.slice(0, 3)).toEqual(["Marcus", "2", "2"]);
  // M11 extended box score: points and distance columns when the stats carry them
  await expect(marcus.getByTestId("box-pts")).toHaveText("4");
  await expect(marcus.getByTestId("box-dist")).not.toHaveText("—");
});

test("R3 stats recompute after a review answer", async ({ page }) => {
  await page.goto(`/tv/${GAME_ID}/review`);
  await expect(page.getByTestId("review-item")).toBeVisible();
  const p3 = page.locator('[data-testid="box-score-row"][data-player-id="p3"]');
  await expect(p3).toBeVisible();
  await expect.poll(async () => (await p3.locator("td").allTextContents()).slice(1, 3)).toEqual([
    "1",
    "1",
  ]);

  await page.keyboard.press("ArrowRight"); // No: not a shot
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("review-item")).toHaveAttribute("data-kind", "identity");
  await expect
    .poll(async () => (await p3.locator("td").allTextContents()).slice(1, 3))
    .toEqual(["0", "0"]);
});

test("S-39 identity questions: type a name on the keyboard, or merge into a teammate", async ({
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
  await expect(page.getByTestId("review-name-key-SAVE")).toHaveAttribute("data-focused", "true");
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
  await expect(page.locator('[data-testid="box-score-row"][data-player-id="p3"]')).toHaveCount(0);
});

// Bug 4: `sport_ui.review` was ignored, so a net sport declaring `[heatmap]` still drew
// an empty shot chart and an empty box score.
test("S-33/S-35 only the panels in sport_ui.review are rendered", async ({ page }) => {
  await page.goto(`/tv/${GAME_ID}/review`);
  // basketball lists all three
  await expect(page.getByTestId("shot-chart")).toBeVisible();
  await expect(page.getByTestId("heatmap")).toBeVisible();
  await expect(page.getByTestId("box-score-row").first()).toBeVisible();

  await page.goto(`/tv/${NET_GAME_ID}/review`);
  // pickleball lists only the heatmap
  await expect(page.getByTestId("heatmap")).toBeVisible();
  await expect(page.getByTestId("shot-chart")).toHaveCount(0);
  await expect(page.getByTestId("box-score-row")).toHaveCount(0);
  // the queue is the screen's job, not a stat, so it stays for every sport
  await expect(
    page.getByTestId("review-item").or(page.getByTestId("review-empty")),
  ).toBeVisible();
});
