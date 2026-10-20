// Do more → Follow player: the roster as chips (face or initials, name). Choosing one
// follows them in place, playback going on; a small "Following Marcus" chip stays while
// the transport hides; Spotlight, Tag and Link sit in the same row once a player is picked;
// Back stops following at the same time.
import { expect, test } from "@playwright/test";
import { media, menuTo, openWatch, smallText, transform } from "./helpers";

test("TV-25 follow a player from the chips; the Following chip; Back stops", async ({
  page,
}) => {
  await openWatch(page);
  await expect.poll(async () => (await media(page)).paused).toBe(false);
  await menuTo(page, "action-follow");
  await expect(page.getByTestId("action-follow")).toContainText(
    "Pick a player",
  );
  await page.keyboard.press("Enter");
  const domore = page.getByTestId("domore");
  await expect(domore).toHaveAttribute("data-row", "action-follow");
  const chips = page.locator('[data-testid="domore"] [data-testid^="follow-"]');
  await expect(chips).toHaveCount(5); // four players, then Pick on screen
  await expect(page.getByTestId("follow-p1")).toContainText("Marcus");
  await expect(page.getByTestId("follow-p2")).toContainText("Player 2");
  await expect(page.getByTestId("follow-p1").getByTestId("avatar")).toHaveText(
    "M",
  );
  await expect(page.getByTestId("follow-p1")).toHaveAttribute(
    "data-focused",
    "true",
  );
  await expect(page.getByTestId("follow-pick")).toContainText("Pick on screen");
  // Nothing picked yet: no Spotlight, Tag or Link.
  await expect(page.getByTestId("action-tag")).toHaveCount(0);
  await page.waitForTimeout(300);
  const chip = (await page.getByTestId("follow-p1").boundingBox())!;
  expect(chip.x).toBeGreaterThanOrEqual(96 - 12);
  expect(await smallText(page)).toEqual([]);

  // Marcus: followed in place, still playing; the layer closes.
  await page.keyboard.press("Enter");
  await expect(domore).toHaveCount(0);
  const watch = page.getByTestId("watch");
  await expect(watch).toHaveAttribute("data-mode", "follow");
  const following = page.getByTestId("followcam-active");
  await expect(following).toHaveAttribute("data-player-id", "p1");
  await expect(following).toContainText("Following Marcus");
  await expect.poll(async () => (await transform(page))[0]).toBeGreaterThan(1);
  expect((await media(page)).paused).toBe(false);
  await expect(page.getByText("Stop following")).toBeVisible();
  const box = (await following.boundingBox())!;
  expect(box.x).toBeGreaterThanOrEqual(96);
  expect(box.y).toBeGreaterThanOrEqual(54);

  // The transport hides after 5 s of playback; the chip stays.
  await expect(page.getByTestId("transport")).toHaveAttribute(
    "data-hidden",
    "true",
    { timeout: 8_000 },
  );
  await expect(following).toBeVisible();
  await expect(page.getByText("Stop following")).toHaveCount(0);

  // Do more again: says who; Marcus is marked; Spotlight, Tag, Link for him.
  await menuTo(page, "action-follow");
  await expect(page.getByTestId("action-follow")).toContainText(
    "Following Marcus",
  );
  await menuTo(page, "action-tag");
  await expect(page.getByTestId("follow-p1")).toHaveAttribute(
    "data-on",
    "true",
  );
  await expect(page.getByTestId("action-tag")).toContainText("Tag Marcus");
  await expect(page.getByTestId("action-spotlight")).toBeAttached();
  await expect(page.getByTestId("action-link-profile")).toBeAttached();
  await page.keyboard.press("Escape"); // the row → the main row
  await expect(domore).toHaveAttribute("data-row", "main");
  await page.keyboard.press("Escape"); // → closed
  await expect(domore).toHaveCount(0);

  // Back stops following: the wide shot, at the same time, still playing.
  const before = (await media(page)).t;
  await page.keyboard.press("Escape");
  await expect(following).toHaveCount(0);
  await expect(watch).toHaveAttribute("data-mode", "wide");
  await expect.poll(async () => (await transform(page))[0]).toBeCloseTo(1, 3);
  const after = await media(page);
  expect(after.t).toBeGreaterThanOrEqual(before - 0.1);
  expect(after.t).toBeLessThan(before + 2);
  expect(after.paused).toBe(false);
});
