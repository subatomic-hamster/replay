// S-63: the phone page's Names tab says what a basket is worth in this game: "2s & 3s"
// (the default) or pickup "1s & 2s" (PUT /games/{id}/scoring; the API recounts the score
// and the stats from the same baskets). SYNTHETIC mock g_mock01 (basketball).
import { expect, test } from "@playwright/test";
import { GAME_ID, mockCalls } from "./helpers";

test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });

test("S-63 Names: switch the game to pickup 1s & 2s and back", async ({
  page,
}) => {
  await page.goto(`/p/${GAME_ID}?job=tag#k=tok_phone`);
  const picks = page.getByTestId("scoring-pick");
  await expect(picks).toHaveText(["Scoring 2s & 3s", "Scoring 1s & 2s"]);
  await expect(picks.nth(0)).toHaveAttribute("aria-checked", "true");

  await picks.nth(1).click();
  await expect(page.getByTestId("tag-note")).toHaveText("Scoring 1s & 2s.");
  await expect(picks.nth(1)).toHaveAttribute("aria-checked", "true");
  await expect(picks.nth(0)).toHaveAttribute("aria-checked", "false");
  await page.screenshot({ path: test.info().outputPath("names-scoring.png") });

  await picks.nth(0).click();
  await expect(page.getByTestId("tag-note")).toHaveText("Scoring 2s & 3s.");
  const put = (await mockCalls(page)).filter(
    (c) => c.method === "PUT" && c.path === `/games/${GAME_ID}/scoring`,
  );
  expect(put.map((c) => c.body)).toEqual([
    { mode: "pickup" },
    { mode: "standard" },
  ]);
});
