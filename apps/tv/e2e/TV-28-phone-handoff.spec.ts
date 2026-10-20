// Do more → On your phone: one QR code per job, the link the API mints for it
// (POST /games/{id}/phone-link: `{web_base}/p/{id}?job=..&t=..#k=<token>`). The screen
// shows host/path only, never the `#k=` token. A job's link is minted once while the panel
// is open; with no link (the server has no web base, or an error) it says so, no QR.
import { expect, test, type Page } from "@playwright/test";
import {
  GAME_ID,
  media,
  menuTo,
  mockCalls,
  openWatch,
  smallText,
} from "./helpers";

const SHOTS = process.env.REPLAY_TV_SHOTS;

const qrUrl = (page: Page) =>
  page.getByTestId("phone-qr").getAttribute("data-url");

async function openPanel(page: Page, before?: () => Promise<void>) {
  await openWatch(page, GAME_ID, "?t=12");
  await before?.();
  await expect
    .poll(async () => (await media(page)).t, { timeout: 10_000 })
    .toBeGreaterThan(12);
  await page.keyboard.press("Space");
  await expect.poll(async () => (await media(page)).paused).toBe(true);
  const t = Math.floor((await media(page)).t);
  await menuTo(page, "nav-phone");
  await page.keyboard.press("Enter");
  const panel = page.getByTestId("phone-panel");
  await expect(panel).toBeVisible();
  await expect(page.getByTestId("domore")).toHaveCount(0);
  return { panel, t };
}

const mints = async (page: Page) =>
  (await mockCalls(page)).filter(
    (c) => c.method === "POST" && c.path === `/games/${GAME_ID}/phone-link`,
  );

test("TV-28 On your phone: a QR per job, the API's phone link for this game and time", async ({
  page,
}) => {
  const { panel, t } = await openPanel(page);
  const origin = new URL(page.url()).origin;
  const host = origin.replace(/^https?:\/\//, "");

  for (const job of ["clip", "tag", "review", "search"]) {
    if (job !== "clip") await page.keyboard.press("ArrowRight");
    await expect(panel).toHaveAttribute("data-job", job);
    await expect(page.getByTestId(`phone-${job}`)).toHaveAttribute(
      "data-focused",
      "true",
    );
    await expect
      .poll(() => qrUrl(page))
      .toBe(
        `${origin}/p/${GAME_ID}?job=${job}&t=${t}#k=MOCK-phone-token.${GAME_ID}.${job}`,
      );
    // host/path only: no query, no token
    await expect(page.getByTestId("phone-url")).toHaveText(
      `${host}/p/${GAME_ID}`,
    );
    await expect(panel).not.toContainText("#k=");
    await expect(panel).not.toContainText("MOCK-phone-token");
    const qr = (await page.getByTestId("phone-qr").boundingBox())!;
    expect(qr.width).toBeGreaterThanOrEqual(400);
    expect(qr.x).toBeGreaterThanOrEqual(96);
    expect(qr.y + qr.height).toBeLessThanOrEqual(1080 - 54);
    expect(await smallText(page)).toEqual([]);
    if (SHOTS) await page.screenshot({ path: `${SHOTS}/phone-${job}.png` });
  }
  await page.keyboard.press("ArrowRight"); // the last job stays
  await expect(panel).toHaveAttribute("data-job", "search");

  // Back through the jobs: the cached links, no new mint.
  for (let i = 0; i < 3; i++) await page.keyboard.press("ArrowLeft");
  await expect(panel).toHaveAttribute("data-job", "clip");
  await expect.poll(() => qrUrl(page)).toContain("job=clip");
  const sent = await mints(page);
  expect(sent.map((c) => c.body)).toEqual(
    ["clip", "tag", "review", "search"].map((job) => ({ job, t })),
  );

  await page.keyboard.press("Escape");
  await expect(panel).toHaveCount(0);
  await expect(page.getByTestId("watch")).toHaveAttribute("data-layer", "");
  expect((await media(page)).paused).toBe(true);

  // Reopened at the same moment: still cached.
  await menuTo(page, "nav-phone");
  await page.keyboard.press("Enter");
  await expect.poll(() => qrUrl(page)).toContain("job=clip");
  expect(await mints(page)).toHaveLength(4);
});

test("TV-28 On your phone: no web address on the server, or an error, says so (no QR)", async ({
  page,
}) => {
  // Clip: the server has no web base (url null); Tag: the call fails.
  const { panel } = await openPanel(page, () =>
    page.evaluate(() => {
      const w = window as unknown as {
        __replayMock: {
          api: { phoneLink: (...a: unknown[]) => Promise<object> };
        };
      };
      const api = w.__replayMock.api;
      const mint = api.phoneLink;
      api.phoneLink = async (...a) => {
        if (a[1] === "tag") throw new Error("503");
        const link = await mint(...a);
        return a[1] === "clip" ? { ...link, url: null } : link;
      };
    }),
  );
  const none = page.getByTestId("phone-no-qr");

  await expect(panel).toHaveAttribute("data-job", "clip");
  await expect(none).toHaveText(
    "Phone handoff needs the web address set on the server",
  );
  await expect(page.getByTestId("phone-qr")).toHaveCount(0);
  await expect(page.getByTestId("phone-url")).toHaveCount(0);
  expect(await smallText(page)).toEqual([]);
  if (SHOTS) {
    await page.waitForTimeout(800); // the layer's slide-in and the transport's fade
    await page.screenshot({ path: `${SHOTS}/phone-error.png` });
  }

  await page.keyboard.press("ArrowRight");
  await expect(panel).toHaveAttribute("data-job", "tag");
  await expect(none).toBeVisible();
  await expect(page.getByTestId("phone-qr")).toHaveCount(0);

  // the others still work
  await page.keyboard.press("ArrowRight");
  await expect(panel).toHaveAttribute("data-job", "review");
  await expect.poll(() => qrUrl(page)).toContain("job=review");
  await expect(none).toHaveCount(0);
});
