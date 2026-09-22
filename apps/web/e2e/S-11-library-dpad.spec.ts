import { expect, test } from "@playwright/test";

// S-11 — Library browse via D-pad. Also E-01 (empty state markup exists) and E-16.
test.describe("S-11 library", () => {
  test("renders game cards and moves focus with the D-pad", async ({ page }) => {
    await page.goto("/tv");
    const cards = page.getByTestId("game-card");
    // 3 basketball + the pickleball fixture the sport_ui.review test uses.
    await expect(cards).toHaveCount(4);

    const focused = page.locator('[data-testid="game-card"][data-focused="true"]');
    await expect(focused).toHaveCount(1);
    const idOf = () => focused.getAttribute("data-game-id");

    expect(await idOf()).toBe("g_mock01");
    await page.keyboard.press("ArrowRight");
    expect(await idOf()).toBe("g_mock02");
    await page.keyboard.press("ArrowRight");
    expect(await idOf()).toBe("g_proc03");
    await page.keyboard.press("ArrowLeft");
    expect(await idOf()).toBe("g_mock02");
    await expect(focused).toHaveCount(1);
  });

  test("E-14 Back on the library is a no-op", async ({ page }) => {
    await page.goto("/tv");
    await page.keyboard.press("Escape");
    await page.keyboard.press("Backspace");
    expect(new URL(page.url()).pathname).toBe("/tv");
  });

  test("E-16 long titles ellipsize instead of breaking the card", async ({ page }) => {
    await page.goto("/tv");
    const long = page.locator('[data-game-id="g_mock02"] [data-testid="game-card-title"]');
    await expect(long).toHaveCSS("text-overflow", "ellipsis");
    // Both unfocused, so the focus-scale transform does not skew the comparison.
    const a = await page.locator('[data-game-id="g_proc03"]').boundingBox();
    const b = await page.locator('[data-game-id="g_mock02"]').boundingBox();
    expect(Math.abs((a?.height ?? 0) - (b?.height ?? 0))).toBeLessThan(2);
  });
});
