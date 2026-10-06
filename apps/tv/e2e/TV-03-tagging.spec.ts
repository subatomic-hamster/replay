import { expect, test } from "@playwright/test";
import { GAME_ID, enterSelectMode, focusedBoxId, menuTo, mockCalls, openWatch } from "./helpers";

// W7 / S-24 / S-25 on the RN TV app: tag a player with only D-pad + Select.
test("TV-03 tag from the action row with a preset name (S-24)", async ({ page }) => {
  await openWatch(page);
  await enterSelectMode(page);
  await page.keyboard.press("ArrowRight");
  await expect.poll(() => focusedBoxId(page)).toBe("p2");
  await expect(page.getByTestId("player-label-p2")).toHaveText("p2");

  // Up from p2 (nothing above) → action menu; "Tag player" is in the "Players ▸" group.
  await menuTo(page, "action-tag");
  await page.keyboard.press("Enter");

  const dialog = page.getByTestId("tag-dialog");
  await expect(dialog).toBeVisible();
  await expect(dialog).toHaveAttribute("data-player-id", "p2");
  // Presets exclude names already on the roster (p1 is Marcus).
  await expect(page.getByTestId("tag-key-Marcus")).toHaveCount(0);
  await expect(page.getByTestId("tag-key-Jordan")).toHaveAttribute("data-focused", "true");
  await page.keyboard.press("Enter");

  await expect(dialog).toHaveCount(0);
  await expect(page.getByTestId("player-label-p2")).toHaveText("Jordan");
  const patch = (await mockCalls(page)).find((c) => c.method === "PATCH");
  expect(patch).toEqual({
    method: "PATCH",
    path: `/games/${GAME_ID}/players/p2`,
    body: { name: "Jordan" },
  });
});

test("TV-04 on-screen keyboard types a name; Backspace deletes a letter, not Back (S-25)", async ({
  page,
}) => {
  await openWatch(page);
  await enterSelectMode(page);
  await page.keyboard.press("ArrowRight"); // p2
  await page.keyboard.press("t");
  await expect(page.getByTestId("tag-dialog")).toBeVisible();

  // Down to the first letter row (A..J): Z is row 3 col 5, O row 2 col 4, E row 1 col 4.
  const press = async (key: string, n = 1) => {
    for (let i = 0; i < n; i++) await page.keyboard.press(key);
  };
  await press("ArrowDown", 3); // UVWXYZ row, col 0 = U
  await press("ArrowRight", 5); // Z
  await press("Enter");
  await press("ArrowUp"); // K..T row, col 5 = P
  await press("ArrowLeft"); // O
  await press("Enter");
  await press("ArrowUp"); // A..J row, col 4 = E
  await press("Enter");
  await press("Enter"); // a second E
  await expect(page.getByTestId("tag-value")).toHaveText("Zoee");
  await press("Backspace");
  await expect(page.getByTestId("tag-dialog")).toBeVisible();
  await expect(page.getByTestId("tag-value")).toHaveText("Zoe");

  await press("ArrowDown", 3); // control row; col 4 clamps to CANCEL (index 3)
  await press("ArrowLeft"); // SAVE
  await expect(page.getByTestId("tag-key-SAVE")).toHaveAttribute("data-focused", "true");
  await press("Enter");
  await expect(page.getByTestId("player-label-p2")).toHaveText("Zoe");
  const patch = (await mockCalls(page)).find((c) => c.method === "PATCH");
  expect(patch?.body).toEqual({ name: "Zoe" });
});
