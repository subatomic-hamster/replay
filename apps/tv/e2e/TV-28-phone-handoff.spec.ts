// Do more → On your phone: one QR code per job, to the apps/web page for it (principle 4:
// typing and fine edits go to the phone). Clip and Search open the companion paired to
// this TV (POST /sessions, once); Review and Tag open this game's review page and its
// player at this moment. Replaces the Clips, Search, Advice and Pair tiles.
import { expect, test, type Page } from "@playwright/test";
import {
  GAME_ID,
  media,
  menuTo,
  mockCalls,
  openWatch,
  smallText,
} from "./helpers";

const qrUrl = (page: Page) =>
  page.getByTestId("phone-qr").getAttribute("data-url");

test("TV-28 On your phone: a QR per job, to the existing web pages for this game and time", async ({
  page,
}) => {
  await openWatch(page, GAME_ID, "?t=12");
  await expect
    .poll(async () => (await media(page)).t, { timeout: 10_000 })
    .toBeGreaterThan(12);
  await page.keyboard.press("Space");
  await expect.poll(async () => (await media(page)).paused).toBe(true);
  const t = Math.floor((await media(page)).t);
  const origin = new URL(page.url()).origin;

  await menuTo(page, "nav-phone");
  await page.keyboard.press("Enter");
  const panel = page.getByTestId("phone-panel");
  await expect(panel).toBeVisible();
  await expect(page.getByTestId("domore")).toHaveCount(0);

  // Clip (first): the companion, paired by this TV's code.
  await expect(panel).toHaveAttribute("data-job", "clip");
  await expect(page.getByTestId("phone-clip")).toHaveAttribute(
    "data-focused",
    "true",
  );
  await expect.poll(() => qrUrl(page)).toBe(`${origin}/companion/4821`);
  await expect(page.getByTestId("phone-url")).toHaveText(
    `${origin.replace(/^https?:\/\//, "")}/companion/4821`,
  );
  const qr = (await page.getByTestId("phone-qr").boundingBox())!;
  expect(qr.width).toBeGreaterThanOrEqual(400);
  expect(qr.x).toBeGreaterThanOrEqual(96);
  expect(qr.y + qr.height).toBeLessThanOrEqual(1080 - 54);
  expect(await smallText(page)).toEqual([]);

  await page.keyboard.press("ArrowRight");
  await expect(panel).toHaveAttribute("data-job", "tag");
  await expect
    .poll(() => qrUrl(page))
    .toBe(`${origin}/tv/${GAME_ID}?mode=select&t=${t}`);
  await page.keyboard.press("ArrowRight");
  await expect(panel).toHaveAttribute("data-job", "review");
  await expect.poll(() => qrUrl(page)).toBe(`${origin}/tv/${GAME_ID}/review`);
  await page.keyboard.press("ArrowRight");
  await expect(panel).toHaveAttribute("data-job", "search");
  await expect.poll(() => qrUrl(page)).toBe(`${origin}/companion/4821`);
  await page.keyboard.press("ArrowRight"); // the last job stays
  await expect(panel).toHaveAttribute("data-job", "search");

  // One pairing session for the whole panel.
  const sessions = (await mockCalls(page)).filter(
    (c) => c.method === "POST" && c.path === "/sessions",
  );
  expect(sessions).toHaveLength(1);

  await page.keyboard.press("Escape");
  await expect(panel).toHaveCount(0);
  await expect(page.getByTestId("watch")).toHaveAttribute("data-layer", "");
  expect((await media(page)).paused).toBe(true);
});
