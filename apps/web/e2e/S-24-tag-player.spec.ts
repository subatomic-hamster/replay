import { expect, test } from "@playwright/test";
import { GAME_ID, enterSelectMode, mockCalls, openWatch } from "./helpers";

// S-24 preset name list, S-25 on-screen keyboard (D-pad only, Backspace deletes).
test("S-24 picking a preset PATCHes the player and relabels the box", async ({ page }) => {
  await openWatch(page);
  await enterSelectMode(page);
  await page.keyboard.press("ArrowRight"); // p2

  await page.keyboard.press("t");
  await expect(page.getByTestId("tag-dialog")).toBeVisible();
  await expect(page.getByTestId("tag-dialog")).toHaveAttribute("data-player-id", "p2");
  // Already-tagged names are not offered again.
  await expect(page.getByTestId("tag-key-Marcus")).toHaveCount(0);

  await page.keyboard.press("Enter"); // first preset: "Jordan"
  await expect(page.getByTestId("tag-dialog")).toHaveCount(0);
  await expect(page.getByTestId("player-label-p2")).toHaveText("Jordan");

  const patch = (await mockCalls(page)).filter(
    (c) => c.method === "PATCH" && c.path === `/games/${GAME_ID}/players/p2`,
  );
  expect(patch).toHaveLength(1);
  expect(patch[0].body).toEqual({ name: "Jordan" });
});

test("S-25 the on-screen keyboard types a name with arrows and Enter only", async ({ page }) => {
  await openWatch(page);
  await enterSelectMode(page);
  await page.keyboard.press("ArrowRight"); // p2, untagged, so the field starts empty
  await page.keyboard.press("t");
  await expect(page.getByTestId("tag-dialog")).toBeVisible();

  // Type "ZOE" using only D-pad keys.
  const press = async (key: string) => {
    await page.keyboard.press(key);
  };
  await press("ArrowDown"); // letters row 1
  await press("ArrowDown"); // letters row 2
  await press("ArrowDown"); // letters row 3: U V W X Y Z ' -
  for (let i = 0; i < 5; i++) await press("ArrowRight"); // → Z
  await press("Enter");
  await expect(page.getByTestId("tag-value")).toHaveText("Z");

  // A typo, then Backspace — which deletes a letter rather than navigating Back.
  await press("Enter");
  await expect(page.getByTestId("tag-value")).toHaveText("Zz");
  await press("Backspace");
  await expect(page.getByTestId("tag-value")).toHaveText("Z");
  await expect(page.getByTestId("tag-dialog")).toBeVisible();

  // O, then E.
  await press("ArrowUp"); // row K–T
  for (let i = 0; i < 1; i++) await press("ArrowLeft"); // index 4 → "O"
  await press("Enter");
  await expect(page.getByTestId("tag-value")).toHaveText("Zo");
  await press("ArrowUp"); // row A–J
  await press("ArrowLeft"); // index 3 → "D"? walk to index 4 = "E"
  await press("ArrowRight");
  await press("Enter");
  await expect(page.getByTestId("tag-value")).toHaveText("Zoe");

  // Save. Three rows down lands on the control row, where the column clamps to CANCEL.
  await press("ArrowDown");
  await press("ArrowDown");
  await press("ArrowDown");
  await expect(page.getByTestId("tag-key-CANCEL")).toHaveAttribute("data-focused", "true");
  await press("ArrowLeft");
  await expect(page.getByTestId("tag-key-SAVE")).toHaveAttribute("data-focused", "true");
  await press("Enter");

  await expect(page.getByTestId("tag-dialog")).toHaveCount(0);
  const patch = (await mockCalls(page)).filter((c) => c.method === "PATCH");
  expect(patch.at(-1)!.body).toEqual({ name: "Zoe" });
});
