// M10 profiles on the RN TV app (mock API, synthetic profiles: Marcus is linked in two
// games, Jordan opted into face enrollment, Sam did not). Library → Players → profile;
// stat corrections with the D-pad (PATCH, flagged EDITED, auto value kept); the card PNG +
// JSON; the career reel across games; link management and suggestions; linking a roster
// player from Watch and from Review. The mock state lives in the page, so each test walks
// inside the app instead of reloading.
import { expect, test, type Page } from "@playwright/test";
import {
  GAME_ID,
  enterSelectMode,
  failVideoAndCountPollers,
  menuTo,
  mockCalls,
  openWatch,
  pollers,
  smallText,
} from "./helpers";

const MARCUS = "pr_00000000a001";
const JORDAN = "pr_00000000a002";
const SAM = "pr_00000000a003";

async function openProfile(page: Page, id: string) {
  await page.goto(`/tv/players/${id}`);
  await expect(page.getByTestId("profile")).toHaveAttribute(
    "data-profile-id",
    id,
  );
  await expect(page.getByTestId("profile")).toHaveAttribute(
    "data-zone",
    "tabs",
  );
}

/** Tabs zone: Right to the tab, Down into it. */
async function openTab(page: Page, name: "stats" | "card" | "reel" | "links") {
  if ((await page.getByTestId("profile").getAttribute("data-zone")) === "body")
    await page.keyboard.press("Escape");
  await expect(page.getByTestId("profile")).toHaveAttribute(
    "data-zone",
    "tabs",
  );
  for (let i = 0; i < 4; i++) await page.keyboard.press("ArrowLeft");
  const order = ["stats", "card", "reel", "links"];
  for (let i = 0; i < order.indexOf(name); i++)
    await page.keyboard.press("ArrowRight");
  await expect(page.getByTestId("profile")).toHaveAttribute("data-tab", name);
  await page.keyboard.press("ArrowDown");
  await expect(page.getByTestId("profile")).toHaveAttribute(
    "data-zone",
    "body",
  );
}

const stat = (page: Page, key: string) =>
  page.locator(`[data-testid="stat-row"][data-key="${key}"]`);

async function focusStat(page: Page, key: string) {
  for (let i = 0; i < 12; i++) {
    if ((await stat(page, key).getAttribute("data-focused")) === "true") return;
    await page.keyboard.press("ArrowDown");
  }
  await expect(stat(page, key)).toHaveAttribute("data-focused", "true");
}

async function media(page: Page) {
  return page.evaluate(() => {
    const v = document.querySelector<HTMLVideoElement>('[data-testid="video"]');
    return v
      ? { t: v.currentTime, src: v.currentSrc, paused: v.paused }
      : { t: -1, src: "", paused: true };
  });
}

test("TV-15 Home → Players → profile → Back → Players → Home", async ({
  page,
}) => {
  await page.goto("/");
  await expect(
    page.locator('[data-testid="game-card"][data-focused="true"]'),
  ).toBeVisible();
  // Down to Home's Players row; "All players" closes it, after the three avatars.
  await page.keyboard.press("ArrowDown");
  await expect(page.getByTestId("home-player").first()).toHaveAttribute(
    "data-focused",
    "true",
  );
  for (let i = 0; i < 3; i++) await page.keyboard.press("ArrowRight");
  await expect(page.getByTestId("library-players")).toHaveAttribute(
    "data-focused",
    "true",
  );
  await page.keyboard.press("Enter");

  const cards = page.getByTestId("profile-card");
  await expect(cards).toHaveCount(3);
  await expect(cards.first()).toHaveAttribute("data-profile-id", MARCUS);
  await expect(cards.first()).toHaveAttribute("data-focused", "true");
  await expect(page.getByTestId("avatar").first()).toHaveText("M"); // initials, no photo
  await page.keyboard.press("ArrowRight");
  await expect(cards.nth(1)).toHaveAttribute("data-focused", "true");
  // focus ring: the focused card differs from the others
  const look = (i: number) =>
    cards
      .nth(i)
      .evaluate(
        (el) =>
          `${getComputedStyle(el).borderTopColor}|${getComputedStyle(el).backgroundColor}`,
      );
  expect(await look(1)).not.toBe(await look(0));
  expect(await smallText(page)).toEqual([]);

  await page.keyboard.press("Enter");
  await expect(page.getByTestId("profile")).toHaveAttribute(
    "data-profile-id",
    JORDAN,
  );
  await expect(page.getByTestId("profile-name")).toHaveText("Jordan");
  await expect(page.getByTestId("face-enrolled")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("players")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("game-card").first()).toBeVisible();
});

test("TV-15 stat correction with the D-pad: PATCH, EDITED with the auto value, use auto", async ({
  page,
}) => {
  await openProfile(page, MARCUS);
  await expect(page.getByTestId("face-enrolled")).toHaveCount(0);
  await openTab(page, "stats");
  // two sports (basketball + pickleball games): the sport pills come first
  await expect(page.getByTestId("stats-sport-basketball")).toHaveAttribute(
    "data-focused",
    "true",
  );
  await expect(page.getByTestId("stats-tab")).toHaveAttribute(
    "data-sport",
    "basketball",
  );
  await expect(page.getByTestId("stats-label")).toContainText("Auto-detected");

  // the seeded correction: rebounds 3 by the user, 0 auto-detected
  await expect(stat(page, "rebounds")).toHaveAttribute("data-edited", "true");
  await expect(stat(page, "rebounds").getByTestId("stat-edited")).toHaveText(
    "EDITED · auto 0",
  );
  await expect(stat(page, "points")).toHaveAttribute("data-edited", "false");
  await expect(stat(page, "points")).toHaveAttribute("data-value", "4");

  await focusStat(page, "points");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("stat-edit")).toHaveAttribute(
    "data-value",
    "4",
  );
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowLeft");
  await page.keyboard.press("ArrowRight");
  await expect(page.getByTestId("stat-edit")).toHaveAttribute(
    "data-value",
    "6",
  );
  await page.keyboard.press("Enter");
  await expect(stat(page, "points")).toHaveAttribute("data-value", "6");
  await expect(stat(page, "points")).toHaveAttribute("data-edited", "true");
  await expect(stat(page, "points").getByTestId("stat-edited")).toHaveText(
    "EDITED · auto 4",
  );
  await expect(page.getByTestId("stat-note")).toContainText("saved as 6");

  // Select again: Down reaches "Use auto", Select sends null → the auto value is back
  await page.keyboard.press("Enter");
  await page.keyboard.press("ArrowDown");
  await expect(page.getByTestId("stat-use-auto")).toHaveAttribute(
    "data-focused",
    "true",
  );
  await page.keyboard.press("Enter");
  await expect(stat(page, "points")).toHaveAttribute("data-edited", "false");
  await expect(stat(page, "points")).toHaveAttribute("data-value", "4");

  // `games` counts links; Select does not open an editor on it
  for (let i = 0; i < 10; i++) await page.keyboard.press("ArrowUp");
  await expect(page.getByTestId("profile")).toHaveAttribute(
    "data-zone",
    "tabs",
  );
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowDown");
  await expect(stat(page, "games")).toHaveAttribute("data-focused", "true");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("stat-edit")).toHaveCount(0);

  const patches = (await mockCalls(page)).filter((c) => c.method === "PATCH");
  expect(patches).toEqual([
    {
      method: "PATCH",
      path: `/profiles/${MARCUS}`,
      body: { stats: { basketball: { points: 6 } } },
    },
    {
      method: "PATCH",
      path: `/profiles/${MARCUS}`,
      body: { stats: { basketball: { points: null } } },
    },
  ]);
  expect(await smallText(page)).toEqual([]);
});

test("TV-15 card: JSON fields with EDITED tiles; Select renders the PNG", async ({
  page,
}) => {
  await openProfile(page, MARCUS);
  await openTab(page, "card");
  await expect(page.getByTestId("card-tab")).toHaveAttribute(
    "data-rendered",
    "false",
  );
  await expect(page.getByTestId("card-title")).toHaveText(
    "Marcus the scorer: 4 points in 1 game (mock)",
  );
  await expect(
    page.locator('[data-testid="card-tile"][data-key="rebounds"]'),
  ).toHaveAttribute("data-edited", "true");
  await expect(
    page.locator('[data-testid="card-tile"][data-key="points"]'),
  ).toHaveAttribute("data-edited", "false");
  await expect(page.getByTestId("card-best")).toContainText(GAME_ID);
  await expect(page.getByTestId("card-render")).toHaveAttribute(
    "data-focused",
    "true",
  );
  expect(await smallText(page)).toEqual([]);

  await page.keyboard.press("Enter");
  await expect(page.getByTestId("card-tab")).toHaveAttribute(
    "data-rendered",
    "true",
  );
  await expect(page.getByTestId("card-png")).toBeVisible();
  await expect
    .poll(() => page.getByTestId("card-png").evaluate((el) => el.outerHTML))
    .toMatch(/\/mock\/card\.svg\?v=\d+/);
  expect(
    (await mockCalls(page)).some(
      (c) => c.method === "POST" && c.path === `/profiles/${MARCUS}/card`,
    ),
  ).toBe(true);
});

test("TV-15 links: a declined suggestion is sent to the API and stays declined after reopening", async ({
  page,
}) => {
  await openProfile(page, MARCUS);
  await openTab(page, "links");
  const sug = page.getByTestId("suggestion-row");
  await expect(sug).toHaveCount(1);
  await expect(sug).toHaveAttribute("data-game-id", "g_mock02");

  // Decline (Right → Decline, Select): gone from the list
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowDown");
  await expect(sug).toHaveAttribute("data-focused", "true");
  await page.keyboard.press("ArrowRight");
  await expect(page.getByTestId("suggestion-decline")).toHaveAttribute(
    "data-focused",
    "true",
  );
  await page.keyboard.press("Enter");
  await expect(sug).toHaveCount(0);
  await expect(page.getByTestId("links-note")).toHaveText(
    "Suggestion declined",
  );
  expect((await mockCalls(page)).filter((c) => c.method !== "GET")).toEqual([
    {
      method: "POST",
      path: `/profiles/${MARCUS}/suggestions/decline`,
      body: { game_id: "g_mock02", player_id: "p1" },
    },
  ]);

  // Re-entering the profile does not ask again
  await page.keyboard.press("Escape"); // tabs
  await page.keyboard.press("Escape"); // players
  await expect(page.getByTestId("profile-card")).toHaveCount(3);
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("profile")).toHaveAttribute(
    "data-profile-id",
    MARCUS,
  );
  await openTab(page, "links");
  await expect(page.getByTestId("link-row")).toHaveCount(2);
  await expect(sug).toHaveCount(0);
});

test("TV-15 links: accept a same-name suggestion, unlink; the reel crosses games in order", async ({
  page,
}) => {
  test.setTimeout(60_000);
  await openProfile(page, MARCUS);
  await openTab(page, "links");
  await expect(page.getByTestId("link-row")).toHaveCount(2);
  const sug = page.getByTestId("suggestion-row");
  await expect(sug).toHaveCount(1);
  await expect(sug).toHaveAttribute("data-game-id", "g_mock02");
  await expect(sug).toHaveAttribute("data-face", "false");
  await expect(sug.getByTestId("suggestion-reason")).toContainText(
    "SUGGESTION · needs your confirmation",
  );
  await expect(sug.getByTestId("suggestion-reason")).toContainText(
    "Same name tag",
  );

  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowDown");
  await expect(page.getByTestId("suggestion-accept")).toHaveAttribute(
    "data-focused",
    "true",
  );
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("link-row")).toHaveCount(3);
  await expect(sug).toHaveCount(0);

  // Unlink the pickleball game (the last link row)
  const pickle = page.locator(
    '[data-testid="link-row"][data-game-id="g_pickle4"]',
  );
  for (
    let i = 0;
    i < 4 && (await pickle.getAttribute("data-focused")) !== "true";
    i++
  ) {
    await page.keyboard.press("ArrowDown");
  }
  await expect(pickle).toHaveAttribute("data-focused", "true");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("link-row")).toHaveCount(2);
  await expect(page.getByTestId("links-note")).toContainText("Unlinked #p1");

  const writes = (await mockCalls(page)).filter((c) => c.method !== "GET");
  expect(writes).toEqual([
    {
      method: "POST",
      path: `/profiles/${MARCUS}/links`,
      body: { game_id: "g_mock02", player_id: "p1" },
    },
    { method: "DELETE", path: `/profiles/${MARCUS}/links/g_pickle4/p1` },
  ]);

  // Reel: Marcus's plays in g_mock01 then g_mock02, played back to back
  await page.keyboard.press("Escape");
  await page.keyboard.press("ArrowLeft");
  await expect(page.getByTestId("profile")).toHaveAttribute("data-tab", "reel");
  await page.keyboard.press("ArrowDown");
  const items = page.getByTestId("reel-item");
  await expect(items).toHaveCount(4);
  expect(
    await items.evaluateAll((els) =>
      els.map(
        (e) =>
          `${e.getAttribute("data-game-id")}@${e.getAttribute("data-t-start")}`,
      ),
    ),
  ).toEqual(["g_mock01@0.5", "g_mock01@11", "g_mock02@2", "g_mock02@12"]);
  await page.keyboard.press("ArrowDown"); // the second play (11–15.5 s in g_mock01)
  await page.keyboard.press("Enter");
  const counter = page.getByTestId("reel-counter");
  await expect(counter).toHaveAttribute("data-index", "2");
  await expect(counter).toHaveAttribute("data-game-id", GAME_ID);
  await expect
    .poll(async () => (await media(page)).t, { timeout: 10_000 })
    .toBeGreaterThan(11);
  // the play ends at 15.5 s → the next one, in the other game, starts at its own 2 s
  await expect(counter).toHaveAttribute("data-game-id", "g_mock02", {
    timeout: 15_000,
  });
  await expect(counter).toHaveAttribute("data-index", "3");
  await expect(items.nth(2)).toHaveAttribute("data-current", "true");
  await expect
    .poll(async () => (await media(page)).src)
    .toContain("game=g_mock02");
  await expect
    .poll(
      async () => {
        const m = await media(page);
        return m.t >= 2 && m.t < 6.5 && !m.paused;
      },
      { timeout: 10_000 },
    )
    .toBe(true);
  expect(await smallText(page)).toEqual([]);
});

test("TV-15 face suggestions only for the face-enrolled profile, labelled as suggestions", async ({
  page,
}) => {
  await openProfile(page, JORDAN);
  await expect(page.getByTestId("face-enrolled")).toHaveText(
    "FACE ENROLLED (OPT-IN)",
  );
  await openTab(page, "links");
  const sug = page.getByTestId("suggestion-row");
  await expect(sug).toHaveCount(1);
  await expect(sug).toHaveAttribute("data-face", "true");
  await expect(sug).toHaveAttribute("data-player-id", "p3");
  await expect(sug.getByTestId("suggestion-reason")).toContainText(
    "FACE SUGGESTION (opt-in) · confirm only if this is them",
  );
  await expect(sug.getByTestId("suggestion-reason")).toContainText(
    "Face match 58% · 4 votes",
  );
  expect(await smallText(page)).toEqual([]);

  // Sam never enrolled: no face suggestions, and no same-name ones either
  await page.keyboard.press("Escape");
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("profile-card")).toHaveCount(3);
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("profile")).toHaveAttribute(
    "data-profile-id",
    SAM,
  );
  await expect(page.getByTestId("face-enrolled")).toHaveCount(0);
  await openTab(page, "links");
  await expect(page.getByTestId("links-empty")).toBeVisible();
  await expect(sug).toHaveCount(0);
  await openTab(page, "reel");
  await expect(page.getByTestId("reel-empty")).toBeVisible();
});

test("TV-15 Watch: Link profile on the picked player; without a pick there is no tile", async ({
  page,
}) => {
  await openWatch(page);
  // no player picked yet: Do more has no Link profile tile (only actions that exist now)
  await page.keyboard.press("ArrowUp");
  await expect(page.getByTestId("action-follow")).toBeAttached();
  await expect(page.getByTestId("action-link-profile")).toHaveCount(0);
  await page.keyboard.press("Escape");

  await enterSelectMode(page);
  await page.keyboard.press("ArrowRight"); // p2
  await menuTo(page, "action-link-profile");
  await page.keyboard.press("Enter");
  const picker = page.getByTestId("profile-picker");
  await expect(picker).toHaveAttribute("data-player-id", "p2");
  await expect(page.getByTestId("picker-profile")).toHaveCount(3);
  // Back cancels without linking
  await page.keyboard.press("Escape");
  await expect(picker).toHaveCount(0);
  await expect(page.getByTestId("watch")).toBeVisible();

  await menuTo(page, "action-link-profile");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("picker-profile")).toHaveCount(3);
  await page.keyboard.press("ArrowDown");
  await expect(page.getByTestId("picker-profile").nth(1)).toHaveAttribute(
    "data-profile-id",
    JORDAN,
  );
  await expect(page.getByTestId("picker-profile").nth(1)).toHaveAttribute(
    "data-focused",
    "true",
  );
  expect(await smallText(page)).toEqual([]);
  await page.keyboard.press("Enter");
  await expect(picker).toHaveCount(0);
  await expect(page.getByTestId("toast")).toHaveText("Linked to Jordan");
  await expect(page.getByTestId("player-label-p2")).toHaveText("Jordan");
  const posts = (await mockCalls(page)).filter(
    (c) => c.method !== "GET" && c.path.startsWith("/profiles"),
  );
  expect(posts).toEqual([
    {
      method: "POST",
      path: `/profiles/${JORDAN}/links`,
      body: { game_id: GAME_ID, player_id: "p2" },
    },
  ]);
});

test("TV-15 Review: an identity question links the player to a profile", async ({
  page,
}) => {
  await page.goto(`/tv/${GAME_ID}/review`);
  const item = page.getByTestId("review-item");
  await expect(item).toHaveAttribute("data-kind", "low_confidence");
  await page.keyboard.press("Enter"); // Yes, it was a shot
  await expect(item).toHaveAttribute("data-kind", "identity");
  await expect(item).toHaveAttribute("data-player-id", "p2");
  await page.keyboard.press("ArrowRight"); // Same as Marcus
  await page.keyboard.press("ArrowRight"); // Link to profile…
  await expect(page.getByTestId("review-link-profile")).toHaveAttribute(
    "data-focused",
    "true",
  );
  await page.keyboard.press("ArrowRight"); // the last pill is a wall
  await expect(page.getByTestId("review-link-profile")).toHaveAttribute(
    "data-focused",
    "true",
  );
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("profile-picker")).toHaveAttribute(
    "data-player-id",
    "p2",
  );
  await expect(page.getByTestId("picker-profile")).toHaveCount(3);
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowDown");
  await expect(page.getByTestId("picker-profile").nth(2)).toHaveAttribute(
    "data-profile-id",
    SAM,
  );
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("profile-picker")).toHaveCount(0);
  // p2 now has a name, so the queue moves on to the next unnamed player
  await expect(item).toHaveAttribute("data-player-id", "p3");
  const posts = (await mockCalls(page)).filter(
    (c) => c.method !== "GET" && c.path.startsWith("/profiles"),
  );
  expect(posts).toEqual([
    {
      method: "POST",
      path: `/profiles/${SAM}/links`,
      body: { game_id: GAME_ID, player_id: "p2" },
    },
  ]);
});

test("TV-15 reel: a reel video that fails shows Video unavailable and stops waiting for it", async ({
  page,
}) => {
  await failVideoAndCountPollers(page);
  await openProfile(page, MARCUS);
  await openTab(page, "reel");
  await expect(page.getByTestId("reel-item").first()).toBeVisible();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("reel-counter")).toBeAttached();
  await expect(page.getByTestId("player-error")).toContainText(
    "Video unavailable",
  );
  await expect.poll(() => pollers(page)).toBe(0);
});
