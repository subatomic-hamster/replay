// The player's layers (docs/ux/redesign.md "Player"; UI pass §2): Back peels one — Moments /
// Do more → Home (the transport showing is not a level); the transport hides after 5 s of playback (Media3's
// default) and pausing keeps it. Every layer keeps to the 24 px text floor, sits inside the
// 96/54 px safe zone and clears the court line.
import { expect, test, type Page } from "@playwright/test";
import { media, openWatch, smallText } from "./helpers";

const hidden = (page: Page) =>
  page.getByTestId("transport").getAttribute("data-hidden");

test("TV-23 Back peels one layer at a time, then goes Home", async ({
  page,
}) => {
  await openWatch(page);
  expect(await hidden(page)).toBe("false");
  await page.keyboard.press("ArrowDown");
  await expect(page.getByTestId("moments-layer")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("moments-layer")).toHaveCount(0);
  await page.keyboard.press("ArrowUp");
  await expect(page.getByTestId("domore")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("domore")).toHaveCount(0);
  expect(await hidden(page)).toBe("false");
  // Menu toggles Do more (it opens it in every mode, and closes it)
  await page.keyboard.press("m");
  await expect(page.getByTestId("domore")).toBeVisible();
  await page.keyboard.press("m");
  await expect(page.getByTestId("domore")).toHaveCount(0);
  // the transport showing is not a level: one Back goes Home
  expect(await hidden(page)).toBe("false");
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("home")).toBeVisible();
});

test("TV-23 the context chip and the first-open legend", async ({ page }) => {
  await openWatch(page);
  const chip = page.getByTestId("context-chip");
  await expect(chip).toHaveAttribute("data-kind", "title");
  await expect(page.getByTestId("watch-title")).toContainText(/\S/);
  // ▼ Moments ▲ Do more, bottom-right, only for the first 5 s
  await expect(page.getByTestId("legend-▼")).toHaveAttribute(
    "data-label",
    "Moments",
  );
  await expect(page.getByTestId("legend-▲")).toHaveAttribute(
    "data-label",
    "Do more",
  );
  const legend = (await page.getByTestId("key-legend").boundingBox())!;
  const line = (await page.getByTestId("time-remaining").boundingBox())!;
  expect(legend.x + legend.width).toBeLessThanOrEqual(1920 - 96 + 1);
  expect(legend.y + legend.height).toBeLessThanOrEqual(line.y);
  await expect(page.getByTestId("key-legend")).toHaveCount(0, {
    timeout: 8_000,
  });
  // a layer shows its own legend: Do more's
  await page.keyboard.press("ArrowUp");
  await expect(page.getByTestId("legend-Select")).toHaveAttribute(
    "data-label",
    "Choose",
  );
  await expect(page.getByTestId("legend-Back")).toHaveAttribute(
    "data-label",
    "Close",
  );
});

test("TV-23 the transport hides after 5 s of playback; pausing keeps it; a key brings it back", async ({
  page,
}) => {
  await openWatch(page);
  await expect.poll(async () => (await media(page)).paused).toBe(false);
  const shownAt = Date.now();
  await expect(page.getByTestId("transport")).toHaveAttribute(
    "data-hidden",
    "true",
    { timeout: 8_000 },
  );
  expect(Date.now() - shownAt).toBeGreaterThan(3_500); // not before ~5 s after the last key

  await page.keyboard.press("Enter"); // pause: any key shows it
  await expect(page.getByTestId("transport")).toHaveAttribute(
    "data-hidden",
    "false",
  );
  await expect.poll(async () => (await media(page)).paused).toBe(true);
  await page.waitForTimeout(6_000);
  expect(await hidden(page)).toBe("false"); // paused: it stays

  await page.keyboard.press("Enter"); // play again: hides 5 s later
  await expect(page.getByTestId("transport")).toHaveAttribute(
    "data-hidden",
    "true",
    { timeout: 8_000 },
  );
});

test("TV-23 every layer: no text under 24 px, inside the safe zone, clear of the court line", async ({
  page,
}) => {
  await openWatch(page);
  await page.keyboard.press("Space"); // pause: nothing moves while measuring
  const box = async (id: string) =>
    (await page.getByTestId(id).first().boundingBox())!;
  const line = await box("time-elapsed"); // the times row tops the court line
  const title = await box("context-chip");
  expect(title.x).toBeGreaterThanOrEqual(96);
  // T paints its glyphs 0.04 em up to centre the capitals (TV-33): the box, not the ink,
  // may start a pixel above the safe edge
  expect(title.y).toBeGreaterThanOrEqual(54 - 2);
  expect(line.x).toBeGreaterThanOrEqual(96);
  expect(
    (await box("time-remaining")).x + (await box("time-remaining")).width,
  ).toBeLessThanOrEqual(1920 - 96);
  expect(
    (await box("timeline")).y + (await box("timeline")).height,
  ).toBeLessThanOrEqual(1080 - 54);
  expect(await smallText(page)).toEqual([]);

  // Moments: above the times row.
  await page.keyboard.press("ArrowDown");
  await expect(page.getByTestId("moment-card")).toHaveCount(4);
  await page.waitForTimeout(300); // the 150 ms slide
  const row = await box("moments-layer");
  expect(row.y + row.height).toBeLessThanOrEqual(line.y);
  expect(row.x).toBeGreaterThanOrEqual(96);
  // only the focused card's 1.06 scale may reach a little into the margin
  expect((await box("moment-card")).x).toBeGreaterThanOrEqual(96 - 12);
  expect(await smallText(page)).toEqual([]);
  await page.keyboard.press("Escape");

  // Do more: under the title, inside the safe zone.
  await page.keyboard.press("ArrowUp");
  await page.waitForTimeout(300);
  const tiles = await box("domore");
  expect(tiles.y).toBeGreaterThan(title.y + title.height);
  // the row's clip keeps 12 px of room for the focused tile's 1.06 scale (TV-24)
  expect(tiles.x).toBeGreaterThanOrEqual(96 - 12);
  expect((await box("action-follow")).x).toBeGreaterThanOrEqual(96 - 12);
  expect(await smallText(page)).toEqual([]);
  await page.keyboard.press("Escape");

  // Seeking: the preview and its readout sit above the times row.
  await page.keyboard.press(".");
  await page.keyboard.press(".");
  await page.keyboard.press(".");
  const prev = await box("seek-preview");
  const readout = await box("seek-readout");
  expect(prev.y + prev.height).toBeLessThanOrEqual(line.y);
  expect(readout.y + readout.height).toBeLessThanOrEqual(line.y);
  expect(
    readout.x + readout.width <= prev.x || readout.x >= prev.x + prev.width,
  ).toBe(true); // beside, not on
  expect(await smallText(page)).toEqual([]);
});
