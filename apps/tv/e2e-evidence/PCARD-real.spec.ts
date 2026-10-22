// Player card (D-83) evidence: the RN TV app (web build) against a running services/api
// (REPLAY_TV_API=<base>) serving a game the worker processed from real footage. It follows
// the player the pipeline credited with the most events, presses Menu, checks the stat
// line against the game's own events.json, names the player (a PATCH to that local API),
// and Back. One 1080p screenshot per step to REPLAY_TV_EVIDENCE_DIR: footage of minors or
// standard-licence clips stays local (D-7, D-76), so keep that dir out of the repo.
//
//   REPLAY_TV_EVIDENCE_GAME  the processed game id
import { expect, test, type Page } from "@playwright/test";
import path from "node:path";
import { statLine } from "../../../packages/tv-core/src/display";
import type { Game, GameEvent } from "../../../packages/tv-core/src/types";
import { media, openWatch } from "../e2e/helpers";

const API = process.env.REPLAY_TV_API ?? "mock";
const OUT = process.env.REPLAY_TV_EVIDENCE_DIR ?? "test-results/evidence-pcard";
const GAME = process.env.REPLAY_TV_EVIDENCE_GAME ?? "g_mock01";

async function shot(page: Page, name: string) {
  await page.waitForTimeout(700);
  await page.screenshot({ path: path.join(OUT, `${name}.png`) });
}

test("PCARD real game: Menu on the followed player, stat line from events.json, name, Back", async ({
  page,
}) => {
  test.skip(API === "mock", "needs a real processed game");
  test.setTimeout(180_000);
  const game: Game = await (
    await page.request.get(`${API}/games/${GAME}`)
  ).json();
  const evUrl = new URL(game.events_url, `${API}/`).toString();
  const events: GameEvent[] = (await (await page.request.get(evUrl)).json())
    .events;
  // the player most events name, at their first credited event
  const tally = new Map<string, number>();
  for (const e of events)
    if (e.player_id && !e.dismissed && e.type !== "hype")
      tally.set(e.player_id, (tally.get(e.player_id) ?? 0) + 1);
  const pid = [...tally].sort((a, b) => b[1] - a[1])[0]?.[0] ?? "";
  expect(pid, "a player credited with an event").toBeTruthy();
  const at = events.find((e) => e.player_id === pid)?.t_key ?? 0;
  console.log(
    `${game.sport}: ${events.length} events, following ${pid} (${tally.get(pid)}) at ${at}s`,
  );

  await openWatch(
    page,
    GAME,
    `?mode=follow&pid=${pid}&t=${Math.max(0, at - 1)}`,
  );
  await expect(page.getByTestId("followcam-active")).toHaveAttribute(
    "data-player-id",
    pid,
  );
  await shot(page, "01-following");

  await page.keyboard.press("m");
  const card = page.getByTestId("player-card");
  await expect(card).toHaveAttribute("data-player-id", pid);
  await expect.poll(async () => (await media(page)).paused).toBe(true);
  await expect(page.getByTestId("player-card-loading")).toHaveCount(0);
  await shot(page, "02-card");

  // The line is exactly what the events support: labels and values.
  const line = statLine(events, pid);
  console.log(JSON.stringify(line));
  for (const c of line.cells)
    await expect(page.getByTestId(`player-stat-${c.label}`)).toHaveAttribute(
      "data-value",
      c.value,
    );
  const labels = await page
    .locator('[data-testid^="player-stat-"][data-value]')
    .evaluateAll((els) => els.map((e) => e.getAttribute("data-testid")));
  expect(labels).toEqual(line.cells.map((c) => `player-stat-${c.label}`));
  // independent of statLine: the credited block count
  if (line.cells.some((c) => c.label === "Blk"))
    await expect(page.getByTestId("player-stat-Blk")).toHaveAttribute(
      "data-value",
      String(
        events.filter(
          (e) => e.type === "block" && e.player_id === pid && !e.dismissed,
        ).length,
      ),
    );

  // Name them: A, B (the keyboard's first keys; a re-run, where they are "Ab" already,
  // adds C so the name changes), SAVE.
  const before = game.players.find((p) => p.id === pid)?.name;
  const name = before === "Ab" ? "Abc" : "Ab";
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("player-name-dialog")).toBeVisible();
  const value = page.getByTestId("player-name-value");
  for (let i = 0; i < 12; i++) await page.keyboard.press("Backspace"); // a name already there
  for (let i = 0; i < name.length; i++) {
    if (i) await page.keyboard.press("ArrowRight");
    await page.keyboard.press("Enter"); // A, B, C
  }
  await expect(value).toHaveText(name);
  await shot(page, "03-keyboard");
  for (let i = 0; i < 3; i++) await page.keyboard.press("ArrowDown");
  for (let i = 0; i < 3; i++) await page.keyboard.press("ArrowLeft");
  for (let i = 0; i < 2; i++) await page.keyboard.press("ArrowRight"); // SPACE DEL [SAVE]
  await expect(page.getByTestId("player-name-key-SAVE")).toHaveAttribute(
    "data-focused",
    "true",
  );
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("player-card-status")).toHaveText("Name saved");
  await expect(page.getByTestId("player-card-name")).toHaveText(name);
  await shot(page, "04-named");
  const saved: Game = await (
    await page.request.get(`${API}/games/${GAME}`)
  ).json();
  expect(saved.players.find((p) => p.id === pid)?.name).toBe(name);

  await page.keyboard.press("Escape");
  await expect(card).toHaveCount(0);
  await expect.poll(async () => (await media(page)).paused).toBe(false);
  await expect(page.getByTestId("followcam-active")).toContainText(
    `Following ${name}`,
  );
  await shot(page, "05-back");
});
