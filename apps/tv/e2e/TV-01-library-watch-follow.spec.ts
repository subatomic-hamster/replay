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

  // W4: Select follows at the same timestamp; the crop transform scales by 1/0.5. The
  // player's chip takes the title's place top-left.
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
  expect(
    Math.abs((await video(page))!.currentTime - before),
  ).toBeLessThanOrEqual(FRAME);
  expect(sx).toBeCloseTo(2, 2);
  await expect(page.getByTestId("follow-frame")).toHaveAttribute(
    "data-pid",
    "p3",
  );

  // Do more now says who is followed.
  await menuTo(page, "action-follow");
  await expect(page.getByTestId("action-follow")).toContainText(
    "Following Player 3",
  );
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("domore")).toHaveCount(0);

  // Back stops following: wide shot at the same time, identity transform, the frame stays
  // on p3 (W4).
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("followcam-active")).toHaveCount(0);
  await expect.poll(async () => (await transform(page))[0]).toBeCloseTo(1, 3);
  expect(
    Math.abs((await video(page))!.currentTime - before),
  ).toBeLessThanOrEqual(FRAME);
  await expect(page.getByTestId("follow-frame")).toHaveAttribute(
    "data-pid",
    "p3",
  );
  await expect(page.getByTestId("watch-title")).toBeAttached();

  // Back hides the transport, then Back on bare video goes Home.
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("transport")).toHaveAttribute(
    "data-hidden",
    "true",
  );
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("game-card").first()).toBeVisible();
});

test("TV-02 Prev/Next jump moments; Spotlight on the picked player from Do more", async ({
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
  await menuTo(page, "action-spotlight");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("action-spotlight")).toHaveAttribute(
    "data-on",
    "true",
  );
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
