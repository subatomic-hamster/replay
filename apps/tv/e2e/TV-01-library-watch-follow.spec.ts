import { expect, test } from "@playwright/test";
import {
  FRAME,
  GAME_ID,
  enterSelectMode,
  failVideoAndCountPollers,
  focusedBoxId,
  menuTo,
  pollers,
  transform,
  video,
} from "./helpers";

// The DoD path on the RN TV app's web build: Home → player → Do more → Follow player →
// pick → follow → Back → Home, driven only by remote keys (Arrows, Enter = Select,
// Escape = Back, m = Menu).
test("TV-01 Home → player → follow a player → Back → Home", async ({
  page,
}) => {
  await page.goto("/");
  // Home starts on the newest watchable game's card (the processing one sits before it).
  const card = (id: string) =>
    page.locator(`[data-testid="game-card"][data-game-id="${id}"]`);
  await expect(card(GAME_ID)).toBeVisible();
  await expect(card(GAME_ID)).toHaveAttribute("data-focused", "true");

  // D-pad across the cards and back.
  await page.keyboard.press("ArrowRight");
  await expect(card("g_mock02")).toHaveAttribute("data-focused", "true");
  await page.keyboard.press("ArrowLeft");
  await expect(card(GAME_ID)).toHaveAttribute("data-focused", "true");

  // The player opens playing, with the moments cut into the court line.
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("video")).toBeAttached();
  await expect
    .poll(async () => (await video(page))?.readyState ?? 0, { timeout: 15_000 })
    .toBeGreaterThanOrEqual(2);
  await expect.poll(async () => (await video(page))?.paused).toBe(false);
  await expect(page.getByTestId("moment-notch")).toHaveCount(4);
  await expect(page.getByTestId("court-inset")).toHaveCount(0); // the old chrome is gone
  await expect(page.getByTestId("mode-pill")).toHaveCount(0);

  // Do more → Follow player pauses on the leftmost box.
  await enterSelectMode(page);
  await expect(page.getByTestId("watch")).toHaveAttribute(
    "data-mode",
    "select",
  );
  await expect.poll(() => focusedBoxId(page)).toBe("p1");
  await page.keyboard.press("ArrowRight");
  await expect.poll(() => focusedBoxId(page)).toBe("p2");
  await page.keyboard.press("ArrowDown");
  await expect.poll(() => focusedBoxId(page)).toBe("p4");
  await page.keyboard.press("ArrowUp");
  await expect.poll(() => focusedBoxId(page)).toBe("p2");
  await page.keyboard.press("ArrowRight");
  await expect.poll(() => focusedBoxId(page)).toBe("p3");

  // Boxes sit on the player: p3's box matches its normalized bb on the 16:9 surface.
  const surface = (await page.getByTestId("player-surface").boundingBox())!;
  const box = (await page.getByTestId("select-box-p3").boundingBox())!;
  expect(Math.abs((box.x - surface.x) / surface.width - 0.745)).toBeLessThan(
    0.02,
  );
  expect(Math.abs(box.width / surface.width - 0.06)).toBeLessThan(0.005);

  // W4: Select follows from the same timestamp, playing again (it was playing before the
  // pick); the camera zooms to 2.5 × the box height (0.5 → scale 2). The player's chip
  // takes the title's place top-left.
  const before = (await video(page))!.currentTime;
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("followcam-active")).toBeVisible();
  await expect(page.getByTestId("followcam-active")).toHaveAttribute(
    "data-player-id",
    "p3",
  );
  await expect(page.getByTestId("watch-title")).toHaveCount(0);
  await expect(page.locator('[data-testid^="select-box-"]')).toHaveCount(0);
  await expect
    .poll(async () => (await transform(page))[0], { timeout: 5_000 })
    .toBeCloseTo(2, 2);
  const [sx, sy, tx] = await transform(page);
  expect(sy).toBeCloseTo(2, 2);
  expect(tx).toBeLessThan(0); // panned right, toward p3
  const resumed = await video(page);
  expect(resumed!.paused).toBe(false);
  expect(resumed!.currentTime).toBeGreaterThanOrEqual(before - FRAME);
  expect(resumed!.currentTime).toBeLessThan(before + 6);
  expect(sx).toBeCloseTo(2, 2);
  await expect(page.getByTestId("follow-frame")).toHaveAttribute(
    "data-pid",
    "p3",
  );

  // The context chip says who is followed; the legend says how to stop.
  await expect(page.getByTestId("followcam-active")).toContainText(
    "Following Player 3",
  );
  await expect(page.getByTestId("context-chip")).toHaveAttribute(
    "data-kind",
    "follow",
  );
  await expect(page.getByTestId("legend-Back")).toHaveAttribute(
    "data-label",
    "Stop following",
  );

  // Menu is Do more here too: the followed player's card leads, the picker second.
  await page.keyboard.press("m");
  await expect(page.getByTestId("domore")).toBeVisible();
  await expect(page.getByTestId("follow-card")).toContainText("Player 3");
  await expect(page.getByTestId("follow-card")).toContainText("Player card");
  await expect(page.getByTestId("follow-pick")).toContainText(
    "Follow someone else",
  );
  await expect(page.getByTestId("action-follow")).toHaveCount(0);
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("domore")).toHaveCount(0);

  // Back stops following: the camera eases back to the wide shot (identity transform),
  // playback goes on, the ring is gone (D-89; it remembers p3 for the next Select).
  const leaving = (await video(page))!.currentTime;
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("followcam-active")).toHaveCount(0);
  await expect.poll(async () => (await transform(page))[0]).toBeCloseTo(1, 3);
  expect((await video(page))!.currentTime).toBeGreaterThanOrEqual(leaving);
  await expect(page.getByTestId("follow-frame")).toHaveAttribute(
    "data-pid",
    "p3",
  );
  await expect(page.getByTestId("follow-frame")).toHaveCSS("opacity", "0");
  await expect(page.getByTestId("watch-title")).toBeAttached();

  // One more Back goes Home (hiding the transport is not a step).
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("game-card").first()).toBeVisible();
});

test("TV-02 Prev/Next jump moments; Spotlight on the followed player from their card", async ({
  page,
}) => {
  await page.goto(`/tv/${GAME_ID}?t=0.5`);
  await expect
    .poll(async () => (await video(page))?.readyState ?? 0, { timeout: 15_000 })
    .toBeGreaterThanOrEqual(2);
  // `]` / `[` are the remote's Next / Previous: to each moment's start (t_key - 1.5 s).
  await page.keyboard.press("Space"); // pause, so the jumps are exact
  await expect.poll(async () => (await video(page))?.paused).toBe(true);
  await page.keyboard.press("]");
  await expect
    .poll(async () => (await video(page))!.currentTime)
    .toBeCloseTo(1.5, 1);
  await page.keyboard.press("]");
  await expect
    .poll(async () => (await video(page))!.currentTime)
    .toBeCloseTo(6.5, 1);
  await page.keyboard.press("[");
  await expect
    .poll(async () => (await video(page))!.currentTime)
    .toBeCloseTo(1.5, 1);

  await enterSelectMode(page);
  await expect.poll(() => focusedBoxId(page)).toBe("p1");
  await page.keyboard.press("Enter"); // follow p1
  await expect(page.getByTestId("watch")).toHaveAttribute(
    "data-mode",
    "follow",
  );
  await menuTo(page, "follow-card");
  await page.keyboard.press("Enter");
  const spot = page.getByTestId("player-card-spotlight");
  await expect(spot).toHaveText("Spotlight off");
  for (let i = 0; i < 6; i++) await page.keyboard.press("ArrowDown");
  await expect(spot).toHaveAttribute("data-focused", "true");
  await page.keyboard.press("Enter");
  await expect(spot).toHaveText("Spotlight on");
  await expect(page.getByTestId("spotlight-overlay")).toBeAttached();
  // Left closes the card, as on Stats; the spotlight stays on the followed player
  await page.keyboard.press("ArrowLeft");
  await expect(page.getByTestId("player-card")).toHaveCount(0);
  await expect(page.getByTestId("spotlight-overlay")).toBeVisible();
});

test("TV-01 a video that fails shows Video unavailable and the ?t= restore stops waiting for it", async ({
  page,
}) => {
  await failVideoAndCountPollers(page);
  await page.goto(`/tv/${GAME_ID}?t=5`);
  await expect(page.getByTestId("player-error")).toBeVisible();
  await expect(page.getByTestId("player-error")).toContainText(
    "Video unavailable",
  );
  await expect.poll(() => pollers(page)).toBe(0);
});
