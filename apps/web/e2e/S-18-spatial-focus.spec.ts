import { expect, test } from "@playwright/test";
import { enterSelectMode, focusedBoxId, openWatch } from "./helpers";

// S-18 — D-pad spatial focus. Fixture layout (normalized centers):
//   p1 (0.11, 0.50)  p2 (0.47, 0.50)  p3 (0.77, 0.48)  p4 (0.55, 0.80)
// Every read polls: the focus moves on the render after the key event, which under 4
// workers can trail the read, and a one-shot read flaked there.
test("S-18 ArrowRight walks the boxes left to right; E-11 the end is a wall", async ({ page }) => {
  await openWatch(page);
  await enterSelectMode(page);

  await expect.poll(() => focusedBoxId(page)).toBe("p1");

  await page.keyboard.press("ArrowRight");
  await expect.poll(() => focusedBoxId(page)).toBe("p2");

  await page.keyboard.press("ArrowRight");
  await expect.poll(() => focusedBoxId(page)).toBe("p3");

  // E-11: nothing further right — focus stays put.
  await page.keyboard.press("ArrowRight");
  await expect.poll(() => focusedBoxId(page)).toBe("p3");
});

test("S-18 ArrowDown picks the box below, not the one further right", async ({ page }) => {
  await openWatch(page);
  await enterSelectMode(page);
  await page.keyboard.press("ArrowRight"); // p2
  await page.keyboard.press("ArrowDown");
  await expect.poll(() => focusedBoxId(page)).toBe("p4");
  await page.keyboard.press("ArrowUp");
  await expect.poll(() => focusedBoxId(page)).toBe("p2");
});
