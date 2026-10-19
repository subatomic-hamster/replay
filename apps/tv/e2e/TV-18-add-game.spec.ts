import { expect, test, type Page } from "@playwright/test";
import qrcode from "qrcode-generator";
import { mockCalls } from "./helpers";

// TV-18 (D-80): Add game from the library with the D-pad: pick the sport, the TV creates
// the game and shows the QR code of the phone upload page, then follows the game (here
// driven through the in-page mock) until it is ready and opens it.

type Run = [row: number, col: number, len: number];

/** The dark runs the QR code should have, encoded here independently of the page. */
function expectedRuns(text: string): { n: number; runs: Run[] } {
  const qr = qrcode(0, "M");
  qr.addData(text);
  qr.make();
  const n = qr.getModuleCount();
  const runs: Run[] = [];
  for (let r = 0; r < n; r++)
    for (let c = 0; c < n; c++) {
      if (!qr.isDark(r, c)) continue;
      const last = runs[runs.length - 1];
      if (last && last[0] === r && last[1] + last[2] === c) last[2]++;
      else runs.push([r, c, 1]);
    }
  return { n, runs };
}

/** The drawn QR code read back from layout: edge, cell size and each black run in cells. */
const drawn = (page: Page) =>
  page.getByTestId("add-qr").evaluate((el) => {
    const box = el.getBoundingClientRect();
    const cell = Number(el.getAttribute("data-cell"));
    const kids = [...el.children].map((k) => {
      const r = k.getBoundingClientRect();
      return {
        x: (r.left - box.left) / cell,
        y: (r.top - box.top) / cell,
        w: r.width / cell,
        h: r.height / cell,
        bg: getComputedStyle(k).backgroundColor,
      };
    });
    return { edge: box.width, height: box.height, cell, bg: getComputedStyle(el).backgroundColor, kids };
  });

async function openAddGame(page: Page) {
  await page.goto("/");
  await expect(page.getByTestId("game-card").first()).toHaveAttribute("data-focused", "true");
  await page.keyboard.press("ArrowUp");
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowRight");
  await expect(page.getByTestId("library-add")).toHaveAttribute("data-focused", "true");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("add-sport-basketball")).toHaveAttribute("data-focused", "true");
}

test("TV-18 add game: sport by D-pad, QR of the upload page, follow it to ready", async ({ page }) => {
  test.setTimeout(90_000);
  await openAddGame(page);
  // Keep what POST /games returned, to know the full upload_page_url (token included).
  await page.evaluate(() => {
    const w = window as unknown as {
      __replayMock: { api: { createGame: (...a: unknown[]) => Promise<{ upload_page_url: string }> } };
      __created?: { upload_page_url: string };
    };
    const create = w.__replayMock.api.createGame;
    w.__replayMock.api.createGame = async (...a) => (w.__created = await create(...a));
  });
  await page.keyboard.press("ArrowRight");
  await expect(page.getByTestId("add-sport-pickleball")).toHaveAttribute("data-focused", "true");
  await page.keyboard.press("Enter");

  await expect(page.getByTestId("add-qr")).toBeVisible();
  const created = (await mockCalls(page)).filter((c) => c.method === "POST" && c.path === "/games");
  expect(created).toHaveLength(1);
  expect(created[0].body).toMatchObject({ sport: "pickleball", title: expect.stringMatching(/^Pickleball · /) });

  const url = await page.evaluate(
    () => (window as unknown as { __created: { upload_page_url: string } }).__created.upload_page_url,
  );
  expect(url).toMatch(/^http:\/\/localhost:\d+\/u\/g_[a-z0-9]+#t=[\w-]{40,}$/);
  const [id, token] = url.match(/\/u\/(g_[a-z0-9]+)#t=(.+)$/)!.slice(1);
  // On screen: host and path only. The token is in the QR code and nowhere else.
  await expect(page.getByTestId("add-url")).toHaveText(new RegExp(`^localhost:\\d+/u/${id}$`));
  await expect(page.locator("body")).not.toContainText(token);
  await expect(page.locator("body")).not.toContainText("#t=");

  // The QR code: what qrcode-generator encodes for that URL, drawn cell for cell, black on
  // white, a 4-module quiet zone, and modules big enough to scan from the couch.
  const want = expectedRuns(url);
  const qr = await drawn(page);
  expect(qr.bg).toBe("rgb(255, 255, 255)");
  expect(qr.cell).toBeGreaterThanOrEqual(8);
  expect(qr.edge).toBeCloseTo(qr.cell * (want.n + 8), 1);
  expect(qr.height).toBeCloseTo(qr.edge, 1);
  expect((want.n - 17) % 4).toBe(0); // 4·version + 17 modules
  const got: Run[] = qr.kids.map((k) => {
    for (const v of [k.x, k.y, k.w, k.h]) expect(Math.abs(v - Math.round(v))).toBeLessThan(0.01);
    expect(k.bg).toBe("rgb(0, 0, 0)");
    expect(Math.round(k.h)).toBe(1);
    return [Math.round(k.y) - 4, Math.round(k.x) - 4, Math.round(k.w)];
  });
  for (const [r, c, len] of got) {
    expect(r >= 0 && c >= 0 && r < want.n && c + len <= want.n).toBe(true); // quiet zone stays white
  }
  expect(got.sort()).toEqual(want.runs.sort());

  // The game as the phone moves it along.
  const status = page.getByTestId("add-status");
  await expect(status).toHaveAttribute("data-status", "created");
  await expect(status).toContainText("Waiting for the upload");
  const set = (s: string) =>
    page.evaluate(
      ([gid, st]) => {
        (window as unknown as { __replayMock: { games: Map<string, { status: string }> } }).__replayMock.games.get(gid)!.status = st;
      },
      [id, s],
    );
  await set("uploaded");
  await expect(status).toHaveAttribute("data-status", "uploaded");
  await expect(status).toContainText("Calibrating on the phone");
  await set("calibrated");
  await expect(status).toHaveAttribute("data-status", "calibrated");
  await page.evaluate(
    (gid) =>
      (window as unknown as { __replayMock: { api: { startProcessing(id: string): Promise<void> } } }).__replayMock.api.startProcessing(gid),
    id,
  );
  await expect(status).toHaveAttribute("data-status", "processing");
  await expect(status).toContainText(/stage \d of 9 · \d+%/);
  await expect(page.getByTestId("add-progress")).toBeVisible();

  // Ready opens the game.
  await expect(page.getByTestId("video")).toBeAttached({ timeout: 45_000 });
  await expect(page.getByTestId("add-game")).toHaveCount(0);
  expect((await mockCalls(page)).some((c) => c.path === `/games/${id}`)).toBe(true);
});

test("TV-18 Back leaves Add game for the library", async ({ page }) => {
  await openAddGame(page);
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("add-game")).toHaveCount(0);
  await expect(page.getByTestId("library-add")).toBeVisible();
  expect((await mockCalls(page)).some((c) => c.method === "POST" && c.path === "/games")).toBe(false);
});
