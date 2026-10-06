// M13 "Replay, clip that" on the web TV: the clips list (trigger type + attribution), the
// D-pad trimmer (PATCH /clips/{id}) and the 9:16 share export (POST /exports/vertical,
// polled until done, then a portrait preview + link). Mock fixture g_mock01: three clips —
// X gesture by Marcus, a phone tap (no attribution), voice "Replay, clip Marcus".
import { expect, test, type Page } from "@playwright/test";
import { GAME_ID, menuTo, mockCalls, openWatch } from "./helpers";

const CLIPS = `/tv/${GAME_ID}/clips`;

async function media(page: Page) {
  return page.evaluate(() => {
    const v = document.querySelector<HTMLVideoElement>('[data-testid="video"]');
    return v ? { t: v.currentTime, paused: v.paused, ready: v.readyState } : { t: -1, paused: true, ready: 0 };
  });
}

test("S-43 Watch → Clips: trigger type and who it belongs to", async ({ page }) => {
  await openWatch(page);
  await menuTo(page, "nav-clips");
  await page.keyboard.press("Enter");

  const cards = page.getByTestId("clip-card");
  await expect(cards).toHaveCount(3);
  await expect(cards.nth(0)).toHaveAttribute("data-trigger", "gesture");
  await expect(cards.nth(0).getByTestId("clip-trigger")).toHaveText("X gesture");
  await expect(cards.nth(0).getByTestId("clip-attribution")).toHaveText("by Marcus");
  await expect(cards.nth(1).getByTestId("clip-trigger")).toHaveText("Phone tap");
  await expect(cards.nth(1).getByTestId("clip-attribution")).toHaveText("unattributed");
  await expect(cards.nth(2).getByTestId("clip-trigger")).toHaveText("Voice");
  await expect(cards.nth(2).getByTestId("clip-attribution")).toHaveText("of Marcus");
  await expect(cards.nth(2)).toContainText("“Replay, clip Marcus”");
  await expect(cards.nth(0)).toHaveAttribute("data-focused", "true");

  // The focused clip previews from its start; Down moves to the next one.
  await expect.poll(async () => (await media(page)).paused, { timeout: 10_000 }).toBe(false);
  await page.keyboard.press("ArrowDown");
  await expect(cards.nth(1)).toHaveAttribute("data-focused", "true");
  await expect.poll(async () => (await media(page)).t).toBeGreaterThan(4.4);

  await page.keyboard.press("Escape");
  await expect(page.getByTestId("watch")).toBeVisible();
});

test("S-43 trim with the D-pad and save (PATCH /clips/{id})", async ({ page }) => {
  await page.goto(CLIPS);
  await expect(page.getByTestId("clip-card")).toHaveCount(3);
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowDown"); // c_v1, 10–16.5
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("clips")).toHaveAttribute("data-trimming", "true");
  await expect(page.getByTestId("trim-start")).toHaveAttribute("data-focused", "true");
  await expect(page.getByTestId("trim-start")).toHaveAttribute("data-t", "10");

  await page.keyboard.press("ArrowLeft"); // start −0.5 s: the picture shows the new edge, paused
  await expect(page.getByTestId("trim-start")).toHaveAttribute("data-t", "9.5");
  await expect(page.getByTestId("trim-start")).toContainText("0:09.5");
  await expect.poll(async () => (await media(page)).paused).toBe(true);
  await expect.poll(async () => (await media(page)).t).toBeCloseTo(9.5, 1);

  await page.keyboard.press("ArrowDown");
  await expect(page.getByTestId("trim-end")).toHaveAttribute("data-focused", "true");
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowRight");
  await expect(page.getByTestId("trim-end")).toHaveAttribute("data-t", "17.5");
  await expect(page.getByTestId("trim-length")).toHaveText("8.0 s");

  await page.keyboard.press("ArrowDown"); // actions: Save trim focused
  await expect(page.getByTestId("trim-save")).toHaveAttribute("data-focused", "true");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("trim-note")).toHaveText("Trim saved");
  const patch = (await mockCalls(page)).find((c) => c.method === "PATCH");
  expect(patch).toEqual({
    method: "PATCH",
    path: `/games/${GAME_ID}/clips/c_v1`,
    body: { t_start: 9.5, t_end: 17.5 },
  });

  await page.keyboard.press("Escape"); // back to the list, which shows the saved window
  const card = page.locator('[data-testid="clip-card"][data-clip-id="c_v1"]');
  await expect(card).toHaveAttribute("data-t-start", "9.5");
  await expect(card).toContainText("0:09.5–0:17.5 · 8.0 s · edited");
  // a phone-tap clip is user-sourced from birth: never labelled "edited"
  await expect(page.locator('[data-testid="clip-card"][data-clip-id="c_t1"]')).not.toContainText(
    "edited",
  );
});

test("S-43 Escape in the trimmer discards; Reset restores", async ({ page }) => {
  await page.goto(CLIPS);
  await expect(page.getByTestId("clip-card")).toHaveCount(3);
  await page.keyboard.press("Enter");
  await page.keyboard.press("ArrowRight");
  await expect(page.getByTestId("trim-start")).toHaveAttribute("data-t", "0.5");
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowRight"); // Reset
  await expect(page.getByTestId("trim-reset")).toHaveAttribute("data-focused", "true");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("trim-start")).toHaveAttribute("data-t", "0");
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("clips")).toHaveAttribute("data-trimming", "false");
  expect((await mockCalls(page)).filter((c) => c.method === "PATCH")).toEqual([]);
});

test("S-44 Share 9:16: a changed trim is saved first, then the export renders to a portrait preview + link", async ({
  page,
}) => {
  await page.goto(CLIPS);
  await expect(page.getByTestId("clip-card")).toHaveCount(3);
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowDown"); // c_v1, 10–16.5
  await page.keyboard.press("Enter");
  await page.keyboard.press("ArrowRight"); // start +0.5 s: a dirty trim
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowRight");
  await expect(page.getByTestId("trim-share")).toHaveAttribute("data-focused", "true");
  await page.keyboard.press("Enter");

  const panel = page.getByTestId("export-panel");
  await expect(panel).toBeVisible();
  const calls = await mockCalls(page);
  const patchAt = calls.findIndex((c) => c.method === "PATCH");
  const postAt = calls.findIndex((c) => c.path.endsWith("/exports/vertical"));
  expect(calls[patchAt]).toMatchObject({ path: `/games/${GAME_ID}/clips/c_v1`, body: { t_start: 10.5, t_end: 16.5 } });
  expect(calls[postAt]).toMatchObject({ method: "POST", body: { clip_id: "c_v1" } });
  expect(patchAt).toBeLessThan(postAt); // the export reads the saved clip

  await expect(panel).toHaveAttribute("data-status", "done", { timeout: 5_000 });
  const box = await page
    .getByTestId("vertical-preview")
    .locator('[data-testid="player-surface"]')
    .boundingBox();
  expect(box && box.height / box.width).toBeCloseTo(16 / 9, 1); // portrait
  await expect(page.getByTestId("export-url")).toContainText("export=v_");

  await page.keyboard.press("Escape");
  await expect(panel).toHaveCount(0);
  await expect(page.getByTestId("clips")).toHaveAttribute("data-trimming", "true");
});

test("S-43 a game without clips explains how to make one", async ({ page }) => {
  await page.goto(`/tv/g_mock02/clips`);
  await expect(page.getByTestId("clips-empty")).toContainText("Replay, clip that");
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("watch")).toBeVisible();
});
