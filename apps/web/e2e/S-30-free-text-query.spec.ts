import { expect, test, type Page } from "@playwright/test";
import { GAME_ID, mockCalls } from "./helpers";

// S-30 / H3 free text: the "Ask…" chip opens the same on-screen keyboard the tag dialog
// uses (TextEntryDialog) and submits to POST /query. E-20 covers the no-match answer.
const LETTER_ROWS = ["ABCDEFGHIJ", "KLMNOPQRST", "UVWXYZ'-"];
const CONTROL_ROW = 3; // SPACE DEL SAVE CANCEL — no preset row in the Ask dialog

let at = { row: 0, col: 0 };

async function moveTo(page: Page, row: number, col: number, width: number) {
  while (at.row < row) {
    await page.keyboard.press("ArrowDown");
    at.row++;
    at.col = Math.min(at.col, (LETTER_ROWS[at.row]?.length ?? 4) - 1);
  }
  while (at.row > row) {
    await page.keyboard.press("ArrowUp");
    at.row--;
    at.col = Math.min(at.col, (LETTER_ROWS[at.row]?.length ?? 4) - 1);
  }
  while (at.col < Math.min(col, width - 1)) {
    await page.keyboard.press("ArrowRight");
    at.col++;
  }
  while (at.col > col) {
    await page.keyboard.press("ArrowLeft");
    at.col--;
  }
}

/** Type a word with Arrow/Enter only (S-25's rule, reused by the Ask dialog). */
async function typeWord(page: Page, word: string) {
  for (const ch of word.toUpperCase()) {
    const row = LETTER_ROWS.findIndex((r) => r.includes(ch));
    await moveTo(page, row, LETTER_ROWS[row].indexOf(ch), LETTER_ROWS[row].length);
    await page.keyboard.press("Enter");
  }
}

async function save(page: Page) {
  await moveTo(page, CONTROL_ROW, 2, 4);
  await expect(page.getByTestId("ask-key-SAVE")).toHaveAttribute("data-focused", "true");
  await page.keyboard.press("Enter");
}

/** Walk the chip row to "Ask…" (always last) and open the dialog. */
async function openAsk(page: Page) {
  await page.goto(`/tv/${GAME_ID}/highlights`);
  const chips = page.getByTestId("query-chip");
  await expect(chips).toHaveCount(5); // 1 per-player reel + 3 sport_ui chips + Ask
  for (let i = 0; i < 4; i++) await page.keyboard.press("ArrowRight");
  await expect(page.locator('[data-chip="Ask…"]')).toHaveAttribute("data-focused", "true");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("ask-dialog")).toBeVisible();
  at = { row: 0, col: 0 };
}

test("S-30 the Ask chip types a free-text query with the D-pad and runs it", async ({ page }) => {
  await openAsk(page);
  await typeWord(page, "misses");
  await expect(page.getByTestId("ask-value")).toHaveText("misses");
  await save(page);

  await expect(page.getByTestId("ask-dialog")).toHaveCount(0);
  await expect(page.getByTestId("query-interpretation")).toBeVisible();
  await expect(page.getByTestId("reel-clip")).toHaveCount(1); // only e_0002 is a miss

  const q = (await mockCalls(page)).filter((c) => c.path.endsWith("/query"));
  expect(q).toHaveLength(1);
  expect(q[0].body).toEqual({ text: "misses" });
});

test("S-30/E-20 a free-text query with no match shows the no-clips state", async ({ page }) => {
  await openAsk(page);
  await typeWord(page, "qq");
  await save(page);
  await expect(page.getByTestId("no-clips")).toBeVisible();
  await expect(page.getByTestId("query-interpretation")).toContainText("No match");
  await expect(page.getByTestId("reel-clip")).toHaveCount(0);
});

test("S-30 Escape closes the Ask dialog without querying", async ({ page }) => {
  await openAsk(page);
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("ask-dialog")).toHaveCount(0);
  expect((await mockCalls(page)).filter((c) => c.path.endsWith("/query"))).toHaveLength(0);
});
