import { expect, test, type Page } from "@playwright/test";
import { openWatch, video } from "./helpers";

// S-13 — Space plays and pauses the wide shot. The second and third tests are the R-07
// regression: `toggle` was `v.play().catch(() => {})`, so a play() rejected while the
// element was still settling on its source reverted `paused` and the keypress was lost.

/** Make the next play() lose its race with a source (re)load, the way a settling source
 *  does: `paused` flips straight back to true. (Chromium does not even settle the play
 *  promise here, so a fix that only watches for the rejection is not enough.) */
async function abortNextPlay(page: Page) {
  await page.evaluate(() => {
    const proto = HTMLMediaElement.prototype;
    const orig = proto.play;
    proto.play = function (this: HTMLMediaElement) {
      proto.play = orig;
      const p = orig.call(this);
      this.load();
      return p;
    };
  });
}

test("S-13 Space plays, Space pauses, and a paused video does not drift", async ({ page }) => {
  await openWatch(page);
  await page.keyboard.press("Space");
  await expect.poll(async () => (await video(page))?.paused).toBe(false);
  await page.keyboard.press("Space");
  await expect.poll(async () => (await video(page))?.paused).toBe(true);
  const t = (await video(page))!.currentTime;
  await page.waitForTimeout(1000);
  expect((await video(page))!.currentTime).toBe(t);
});

test("S-13 a play rejected while the source settles is honoured once it can play", async ({
  page,
}) => {
  await openWatch(page);
  await abortNextPlay(page);
  await page.keyboard.press("Space");
  await expect
    .poll(async () => {
      const v = await video(page);
      return !!v && !v.paused && v.currentTime > 0;
    }, { timeout: 10_000 })
    .toBe(true);
  // Watch read the intent, not the momentary `paused`: no select boxes over a playing video.
  await expect(page.locator('[data-testid^="select-box-"]')).toHaveCount(0);
});

test("S-13 a second Space while that play is pending cancels it", async ({ page }) => {
  await openWatch(page);
  // Reject without a reload: the element stays ready, so the retry is a 100 ms timer —
  // a window the second keypress lands in.
  await page.evaluate(() => {
    const proto = HTMLMediaElement.prototype;
    const orig = proto.play;
    proto.play = function () {
      proto.play = orig;
      return Promise.reject(new DOMException("interrupted", "AbortError"));
    };
  });
  await page.keyboard.press("Space");
  await page.keyboard.press("Space");
  await expect(page.locator('[data-testid^="select-box-"]').first()).toBeVisible();
  await page.waitForTimeout(1500);
  expect((await video(page))!.paused).toBe(true);
});
