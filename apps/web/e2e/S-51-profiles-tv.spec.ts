// M10 profiles on the browser TV harness (apps/tv's TV-15 is the RN twin), mock API with
// synthetic profiles: Marcus is linked in two games, Jordan opted into face enrollment, Sam
// did not. The mock state lives in the page, so each test walks inside the app.
import { expect, test, type Page } from "@playwright/test";
import { GAME_ID, enterSelectMode, menuTo, mockCalls, openWatch, smallText } from "./helpers";

const MARCUS = "pr_00000000a001";
const JORDAN = "pr_00000000a002";
const SAM = "pr_00000000a003";

async function openProfile(page: Page, id: string) {
  await page.goto(`/tv/players/${id}`);
  await expect(page.getByTestId("profile")).toHaveAttribute("data-profile-id", id);
  await expect(page.getByTestId("profile")).toHaveAttribute("data-zone", "tabs");
}

async function openTab(page: Page, name: "stats" | "card" | "reel" | "links") {
  if ((await page.getByTestId("profile").getAttribute("data-zone")) === "body") await page.keyboard.press("Escape");
  await expect(page.getByTestId("profile")).toHaveAttribute("data-zone", "tabs");
  for (let i = 0; i < 4; i++) await page.keyboard.press("ArrowLeft");
  const order = ["stats", "card", "reel", "links"];
  for (let i = 0; i < order.indexOf(name); i++) await page.keyboard.press("ArrowRight");
  await expect(page.getByTestId("profile")).toHaveAttribute("data-tab", name);
  await page.keyboard.press("ArrowDown");
  await expect(page.getByTestId("profile")).toHaveAttribute("data-zone", "body");
}

const stat = (page: Page, key: string) => page.locator(`[data-testid="stat-row"][data-key="${key}"]`);
const writes = async (page: Page) =>
  (await mockCalls(page)).filter((c) => c.method !== "GET" && c.path.startsWith("/profiles"));

async function media(page: Page) {
  return page.evaluate(() => {
    const v = document.querySelector<HTMLVideoElement>('[data-testid="video"]');
    return v ? { t: v.currentTime, src: v.currentSrc, paused: v.paused } : { t: -1, src: "", paused: true };
  });
}

test("S-51 Library → Players → profile → Back → Players → Library", async ({ page }) => {
  await page.goto("/tv");
  await expect(page.getByTestId("game-card").first()).toHaveAttribute("data-focused", "true");
  await page.keyboard.press("ArrowUp");
  await expect(page.getByTestId("library-players")).toHaveAttribute("data-focused", "true");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/tv\/players$/);

  const cards = page.getByTestId("profile-card");
  await expect(cards).toHaveCount(3);
  await expect(cards.first()).toHaveAttribute("data-focused", "true");
  await page.keyboard.press("ArrowRight");
  await expect(cards.nth(1)).toHaveAttribute("data-profile-id", JORDAN);
  await expect(cards.nth(1)).toHaveAttribute("data-focused", "true");
  const look = (i: number) => cards.nth(i).evaluate((el) => `${getComputedStyle(el).boxShadow}|${getComputedStyle(el).backgroundColor}`);
  expect(await look(1)).not.toBe(await look(0));
  expect(await smallText(page)).toEqual([]);

  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(new RegExp(`/tv/players/${JORDAN}$`));
  await expect(page.getByTestId("face-enrolled")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page).toHaveURL(/\/tv\/players$/);
  await page.keyboard.press("Escape");
  await expect(page).toHaveURL(/\/tv$/);
});

test("S-51 stat correction with the D-pad: PATCH, EDITED with the auto value, use auto", async ({ page }) => {
  await openProfile(page, MARCUS);
  await openTab(page, "stats");
  await expect(page.getByTestId("stats-sport-basketball")).toHaveAttribute("data-focused", "true");
  await expect(stat(page, "rebounds")).toHaveAttribute("data-edited", "true");
  await expect(stat(page, "rebounds").getByTestId("stat-edited")).toHaveText("EDITED · auto 0");
  await expect(stat(page, "points")).toHaveAttribute("data-value", "4");

  for (let i = 0; i < 12 && (await stat(page, "points").getAttribute("data-focused")) !== "true"; i++) {
    await page.keyboard.press("ArrowDown");
  }
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("stat-edit")).toHaveAttribute("data-value", "4");
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("Enter");
  await expect(stat(page, "points")).toHaveAttribute("data-value", "6");
  await expect(stat(page, "points")).toHaveAttribute("data-edited", "true");
  await expect(stat(page, "points").getByTestId("stat-edited")).toHaveText("EDITED · auto 4");

  await page.keyboard.press("Enter");
  await page.keyboard.press("ArrowDown");
  await expect(page.getByTestId("stat-use-auto")).toHaveAttribute("data-focused", "true");
  await page.keyboard.press("Enter");
  await expect(stat(page, "points")).toHaveAttribute("data-edited", "false");
  await expect(stat(page, "points")).toHaveAttribute("data-value", "4");
  expect(await writes(page)).toEqual([
    { method: "PATCH", path: `/profiles/${MARCUS}`, body: { stats: { basketball: { points: 6 } } } },
    { method: "PATCH", path: `/profiles/${MARCUS}`, body: { stats: { basketball: { points: null } } } },
  ]);
  expect(await smallText(page)).toEqual([]);
});

test("S-51 card: JSON fields with EDITED tiles; Enter renders the PNG", async ({ page }) => {
  await openProfile(page, MARCUS);
  await openTab(page, "card");
  await expect(page.getByTestId("card-tab")).toHaveAttribute("data-rendered", "false");
  await expect(page.getByTestId("card-title")).toHaveText("Marcus the scorer: 4 points in 1 game (mock)");
  await expect(page.locator('[data-testid="card-tile"][data-key="rebounds"]')).toHaveAttribute("data-edited", "true");
  await expect(page.getByTestId("card-render")).toHaveAttribute("data-focused", "true");
  expect(await smallText(page)).toEqual([]);
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("card-tab")).toHaveAttribute("data-rendered", "true");
  await expect(page.getByTestId("card-png")).toHaveAttribute("src", /\/mock\/card\.svg\?v=\d+/);
  await expect.poll(() => page.getByTestId("card-png").evaluate((el) => (el as HTMLImageElement).naturalWidth)).toBeGreaterThan(0);
  expect(await writes(page)).toEqual([{ method: "POST", path: `/profiles/${MARCUS}/card` }]);
});

test("S-51 links: decline, accept, unlink; the reel crosses games in order", async ({ page }) => {
  test.setTimeout(60_000);
  await openProfile(page, MARCUS);
  await openTab(page, "links");
  const sug = page.getByTestId("suggestion-row");
  await expect(page.getByTestId("link-row")).toHaveCount(2);
  await expect(sug).toHaveCount(1);
  await expect(sug).toHaveAttribute("data-face", "false");
  await expect(sug.getByTestId("suggestion-reason")).toContainText("SUGGESTION · needs your confirmation");

  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowRight");
  await expect(page.getByTestId("suggestion-decline")).toHaveAttribute("data-focused", "true");
  await page.keyboard.press("Enter");
  await expect(sug).toHaveCount(0);
  expect(await writes(page)).toEqual([]);

  // re-open the profile from Players (in-app): the declined suggestion is asked again
  await page.keyboard.press("Escape");
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("profile-card")).toHaveCount(3);
  await page.keyboard.press("Enter");
  await openTab(page, "links");
  await expect(sug).toHaveCount(1);
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowDown");
  await expect(page.getByTestId("suggestion-accept")).toHaveAttribute("data-focused", "true");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("link-row")).toHaveCount(3);

  const pickle = page.locator('[data-testid="link-row"][data-game-id="g_pickle4"]');
  for (let i = 0; i < 4 && (await pickle.getAttribute("data-focused")) !== "true"; i++) {
    await page.keyboard.press("ArrowDown");
  }
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("link-row")).toHaveCount(2);
  expect(await writes(page)).toEqual([
    { method: "POST", path: `/profiles/${MARCUS}/links`, body: { game_id: "g_mock02", player_id: "p1" } },
    { method: "DELETE", path: `/profiles/${MARCUS}/links/g_pickle4/p1` },
  ]);

  await page.keyboard.press("Escape");
  await page.keyboard.press("ArrowLeft");
  await expect(page.getByTestId("profile")).toHaveAttribute("data-tab", "reel");
  await page.keyboard.press("ArrowDown");
  const items = page.getByTestId("reel-item");
  await expect(items).toHaveCount(4);
  expect(await items.evaluateAll((els) => els.map((e) => `${e.getAttribute("data-game-id")}@${e.getAttribute("data-t-start")}`))).toEqual([
    "g_mock01@0.5",
    "g_mock01@11",
    "g_mock02@2",
    "g_mock02@12",
  ]);
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("Enter");
  const counter = page.getByTestId("reel-counter");
  await expect(counter).toHaveAttribute("data-index", "2");
  await expect.poll(async () => (await media(page)).t, { timeout: 10_000 }).toBeGreaterThan(11);
  await expect(counter).toHaveAttribute("data-game-id", "g_mock02", { timeout: 15_000 });
  await expect(counter).toHaveAttribute("data-index", "3");
  await expect.poll(async () => (await media(page)).src).toContain("game=g_mock02");
  await expect
    .poll(async () => {
      const m = await media(page);
      return m.t >= 2 && m.t < 6.5 && !m.paused;
    }, { timeout: 10_000 })
    .toBe(true);
});

test("S-51 face suggestions only for the face-enrolled profile", async ({ page }) => {
  await openProfile(page, JORDAN);
  await openTab(page, "links");
  const sug = page.getByTestId("suggestion-row");
  await expect(sug).toHaveCount(1);
  await expect(sug).toHaveAttribute("data-face", "true");
  await expect(sug.getByTestId("suggestion-reason")).toContainText("FACE SUGGESTION (opt-in) · confirm only if this is them");
  await expect(sug.getByTestId("suggestion-reason")).toContainText("Face match 58% · 4 votes");
  expect(await smallText(page)).toEqual([]);

  await openProfile(page, SAM);
  await expect(page.getByTestId("face-enrolled")).toHaveCount(0);
  await openTab(page, "links");
  await expect(page.getByTestId("links-empty")).toBeVisible();
});

test("S-51 Watch: Link profile on the picked player; without a pick it says so", async ({ page }) => {
  await openWatch(page);
  await menuTo(page, "action-link-profile");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("toast")).toHaveText("Pause and pick a player first");
  await expect(page.getByTestId("profile-picker")).toHaveCount(0);

  await enterSelectMode(page);
  await page.keyboard.press("ArrowRight"); // p2
  await page.keyboard.press("Escape"); // back to wide; the pick stays
  await menuTo(page, "action-link-profile");
  await page.keyboard.press("Enter");
  const picker = page.getByTestId("profile-picker");
  await expect(picker).toHaveAttribute("data-player-id", "p2");
  await expect(page.getByTestId("picker-profile")).toHaveCount(3);
  await page.keyboard.press("ArrowDown");
  await expect(page.getByTestId("picker-profile").nth(1)).toHaveAttribute("data-focused", "true");
  expect(await smallText(page)).toEqual([]);
  await page.keyboard.press("Enter");
  await expect(picker).toHaveCount(0);
  await expect(page.getByTestId("toast")).toHaveText("Linked to Jordan");
  expect(await writes(page)).toEqual([
    { method: "POST", path: `/profiles/${JORDAN}/links`, body: { game_id: GAME_ID, player_id: "p2" } },
  ]);
  await enterSelectMode(page);
  await expect(page.getByTestId("player-label-p2")).toHaveText("Jordan");
});

test("S-51 Review: an identity question links the player to a profile", async ({ page }) => {
  await page.goto(`/tv/${GAME_ID}/review`);
  const item = page.getByTestId("review-item");
  await expect(item).toHaveAttribute("data-kind", "low_confidence");
  await page.keyboard.press("Enter");
  await expect(item).toHaveAttribute("data-player-id", "p2");
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowRight");
  await expect(page.getByTestId("review-link-profile")).toHaveAttribute("data-focused", "true");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("profile-picker")).toHaveAttribute("data-player-id", "p2");
  await expect(page.getByTestId("picker-profile")).toHaveCount(3);
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("profile-picker")).toHaveCount(0);
  await expect(item).toHaveAttribute("data-player-id", "p3");
  expect(await writes(page)).toEqual([
    { method: "POST", path: `/profiles/${SAM}/links`, body: { game_id: GAME_ID, player_id: "p2" } },
  ]);
});
