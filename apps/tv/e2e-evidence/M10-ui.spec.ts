// M10 UI evidence: player profiles on the RN TV app (web build), against a running
// services/api (REPLAY_TV_API=<base>) whose data dir holds SYNTHETIC games and profiles
// made through the API (docs/evidence/M10/make_evidence.py games + cards), or the mock
// fixture (REPLAY_TV_API=mock). One 1080p screenshot per step to REPLAY_TV_EVIDENCE_DIR.
// Assertions are structural; the screenshots are the evidence.
//
//   REPLAY_TV_EVIDENCE_PROFILE   the profile with a user correction (default: Alex live, Marcus mock)
//   REPLAY_TV_EVIDENCE_PROFILE2  a second profile for the links screen (default Jordan)
import { expect, test, type Page } from "@playwright/test";
import path from "node:path";
import { enterSelectMode, menuTo, openWatch } from "../e2e/helpers";

const API = process.env.REPLAY_TV_API ?? "mock";
const LIVE = API !== "mock";
const OUT = process.env.REPLAY_TV_EVIDENCE_DIR ?? "test-results/evidence-m10";
const MAIN =
  process.env.REPLAY_TV_EVIDENCE_PROFILE ?? (LIVE ? "Alex" : "Marcus");
const OTHER = process.env.REPLAY_TV_EVIDENCE_PROFILE2 ?? "Jordan";

async function shot(page: Page, name: string) {
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(OUT, `${name}.png`) });
}

/** Library → Players, then Right to the card named `name` and open it. */
async function openByName(page: Page, name: string) {
  await page.goto("/");
  await expect(page.getByTestId("game-card").first()).toBeVisible({
    timeout: 20_000,
  });
  await page.keyboard.press("ArrowUp");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("profile-card").first()).toBeVisible();
  const names = await page.getByTestId("profile-card-name").allTextContents();
  const i = names.indexOf(name);
  expect(i, `profile ${name} in ${names.join(", ")}`).toBeGreaterThanOrEqual(0);
  for (let k = 0; k < i; k++) await page.keyboard.press("ArrowRight");
  return i;
}

async function tab(page: Page, to: "card" | "reel" | "links") {
  await page.keyboard.press("Escape"); // back to the tabs
  await page.keyboard.press("ArrowRight");
  await expect(page.getByTestId("profile")).toHaveAttribute("data-tab", to);
  await page.keyboard.press("ArrowDown");
}

test.describe.configure({ mode: "serial" });

test("M10 players, profile stats + correction, card, reel, links", async ({
  page,
}) => {
  test.setTimeout(150_000);
  await openByName(page, MAIN);
  await shot(page, "01-players");

  await page.keyboard.press("Enter");
  await expect(page.getByTestId("profile")).toBeVisible();
  await page.keyboard.press("ArrowDown");
  await expect(page.getByTestId("stat-row").first()).toBeVisible();
  await shot(page, "02-profile-stats");

  // a D-pad correction on the first editable stat that is not edited yet
  const rows = page.getByTestId("stat-row");
  const keys = await rows.evaluateAll((els) =>
    els.map((e) => [e.getAttribute("data-key"), e.getAttribute("data-edited")]),
  );
  const target =
    keys.find(([k, ed]) => k !== "games" && ed === "false")?.[0] ?? "";
  const row = page.locator(`[data-testid="stat-row"][data-key="${target}"]`);
  for (
    let i = 0;
    i < 12 && (await row.getAttribute("data-focused")) !== "true";
    i++
  )
    await page.keyboard.press("ArrowDown");
  await page.keyboard.press("Enter");
  await page.keyboard.press("ArrowRight");
  await expect(page.getByTestId("stat-edit")).toBeVisible();
  await shot(page, "03-stat-edit");
  await page.keyboard.press("Enter");
  await expect(row).toHaveAttribute("data-edited", "true");
  await shot(page, "04-stat-edited");

  await tab(page, "card");
  await page.keyboard.press("Enter"); // render (or re-render) the PNG
  await expect(page.getByTestId("card-tab")).toHaveAttribute(
    "data-rendered",
    "true",
    { timeout: 60_000 },
  );
  await page.waitForTimeout(1500); // the image itself
  await shot(page, "05-card");

  await tab(page, "reel");
  const items = page.getByTestId("reel-item");
  await expect(
    page
      .locator('[data-testid="reel-item"], [data-testid="reel-empty"]')
      .first(),
  ).toBeVisible();
  if (await items.count()) {
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("reel-counter")).toBeVisible();
    await page.waitForTimeout(2500);
  }
  await shot(page, "06-reel");
  await page.keyboard.press("Space"); // pause before leaving

  await tab(page, "links");
  await shot(page, "07-links");
});

test("M10 links and suggestions of a second profile", async ({ page }) => {
  await openByName(page, OTHER);
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("profile")).toBeVisible();
  for (let i = 0; i < 3; i++) await page.keyboard.press("ArrowRight");
  await expect(page.getByTestId("profile")).toHaveAttribute(
    "data-tab",
    "links",
  );
  await page.keyboard.press("ArrowDown");
  await shot(page, "08-links-second-profile");
});

test("M10 watch: one-row menu, the Players group, link a picked player", async ({
  page,
}) => {
  test.setTimeout(90_000);
  await page.goto("/");
  const ready = page.locator(
    '[data-testid="game-card"][data-processing="false"]',
  );
  await expect(ready.first()).toBeVisible({ timeout: 20_000 });
  const id = await ready.first().getAttribute("data-game-id");
  await openWatch(page, id ?? "g_mock01");
  await page.keyboard.press("ArrowUp");
  await expect(page.getByTestId("nav-library")).toHaveAttribute(
    "data-focused",
    "true",
  );
  await shot(page, "09-watch-menu-top-row");
  await page.keyboard.press("Escape");
  await menuTo(page, "action-link-profile");
  await shot(page, "10-watch-menu-players-group");
  await page.keyboard.press("Escape");
  await page.keyboard.press("Escape");

  await enterSelectMode(page);
  // Up walks the boxes until the top one, then opens the menu: park on the top player
  for (
    let i = 0;
    i < 8 &&
    (await page.getByTestId("nav-library").getAttribute("data-focused")) !==
      "true";
    i++
  ) {
    await page.keyboard.press("ArrowUp");
  }
  await page.keyboard.press("Escape");
  await menuTo(page, "action-link-profile");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("profile-picker")).toBeVisible();
  await shot(page, "11-link-profile-picker");
  await page.keyboard.press("Escape"); // cancel: nothing linked
  await expect(page.getByTestId("profile-picker")).toHaveCount(0);
});
