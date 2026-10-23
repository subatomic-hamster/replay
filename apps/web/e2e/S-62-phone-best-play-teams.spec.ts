// S-62: the phone page's Names tab sets each player's team (two sides, the kit colour
// beside each), and the Clip tab shows the game's best play and makes the chosen moment
// the best play ("★ Make this the best play", PUT /games/{id}/best-play). SYNTHETIC mock
// g_mock01: p1 Marcus (team 0), p2 unnamed with a mixed kit, p3 a brief fragment, p4
// unnamed (team 1); makes at 3, 14 and 17 s, so the automatic pick is the 17 s game winner.
import { expect, test, type Page } from "@playwright/test";
import { GAME_ID, mockCalls } from "./helpers";

test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });

const row = (page: Page, pid: string) =>
  page.locator(`[data-testid="tag-player"][data-player-id="${pid}"]`);
const calls = async (page: Page, method: string, path: string) =>
  (await mockCalls(page)).filter((c) => c.method === method && c.path === path);

test("S-62 Names: put each player on a team and name them", async ({
  page,
}) => {
  await page.goto(`/p/${GAME_ID}?job=tag#k=tok_phone`);
  await expect(row(page, "p1").getByTestId("tag-team")).toHaveText("Team 1");
  // a mixed kit is a guess: no team shown until someone says
  await expect(row(page, "p2").getByTestId("tag-team")).toHaveCount(0);

  await row(page, "p2").click();
  const panel = page.getByTestId("tag-panel");
  const picks = panel.getByTestId("tag-team-pick");
  await expect(picks).toHaveText(["Team 1", "Team 2"]);
  await expect(picks.nth(1)).toHaveAttribute("aria-checked", "false");
  await picks.nth(1).click();
  await expect(page.getByTestId("tag-note")).toHaveText(
    "Player 2 is on Team 2.",
  );
  await expect(picks.nth(1)).toHaveAttribute("aria-checked", "true");
  await expect(row(page, "p2").getByTestId("tag-team")).toHaveText("Team 2");
  expect(
    (await calls(page, "PATCH", `/games/${GAME_ID}/players/p2`)).map(
      (c) => c.body,
    ),
  ).toEqual([{ team: 1 }]);
  // then the name, in the same panel
  await page.getByTestId("tag-new-name").fill("Ana");
  await page.getByTestId("tag-new-save").click();
  await expect(page.getByTestId("tag-note")).toHaveText("Named Ana.");
  await expect(row(page, "p2")).toHaveAttribute("data-name", "Ana");
  await expect(row(page, "p2").getByTestId("tag-team")).toHaveText("Team 2");

  // move Marcus to the other side
  await row(page, "p1").click();
  await page
    .getByTestId("tag-panel")
    .getByTestId("tag-team-pick")
    .nth(1)
    .click();
  await expect(page.getByTestId("tag-note")).toHaveText("Marcus is on Team 2.");
  await expect(row(page, "p1").getByTestId("tag-team")).toHaveText("Team 2");
  await page.screenshot({ path: test.info().outputPath("names-teams.png") });
});

test("S-62 Clip: the best play now, then make the chosen moment the best play", async ({
  page,
}) => {
  await page.goto(`/p/${GAME_ID}?job=clip&t=3#k=tok_phone`);
  const now = page.getByTestId("clip-best-now");
  await expect(now).toHaveAttribute("data-source", "auto:last_make");
  await expect(now).toHaveText("★ Best play now: 0:17 · Basket (Last basket)");

  await expect(page.getByTestId("clip-moment")).toHaveValue("e_0001");
  await page.getByTestId("clip-best").click();
  await expect(page.getByTestId("clip-best-note")).toHaveText(
    "This is now the best play of the game. Highlights on the TV end with it.",
  );
  await expect(now).toHaveAttribute("data-source", "user");
  await expect(now).toHaveAttribute("data-moment-id", "e_0001");
  await expect(now).toContainText("Basket, Marcus (your pick)");
  const put = await calls(page, "PUT", `/games/${GAME_ID}/best-play`);
  expect(put).toHaveLength(1);
  expect(put[0].body).toMatchObject({ t: 3, moment_id: "e_0001" });
  await page.screenshot({ path: test.info().outputPath("clip-best.png") });
});
