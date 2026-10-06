import { expect, test, type Page } from "@playwright/test";

// The API address on the TV: reached from the library with the D-pad, typed on the
// on-screen keyboard, normalized, tested against the API (GET /games) and kept on the device.
const BASE = "http://10.0.0.5:8000";

/** Walk the on-screen keyboard to each key label with the arrows, and Select it. */
async function typeKeys(page: Page, prefix: string, labels: string[]) {
  const rect = (sel: string) => page.locator(sel).first().evaluate((el) => el.getBoundingClientRect().toJSON());
  for (const label of labels) {
    const target = `[data-testid="${prefix}-key-${label}"]`;
    for (let i = 0; i < 30 && (await page.locator(target).getAttribute("data-focused")) !== "true"; i++) {
      const [from, to] = [await rect(`[data-testid^="${prefix}-key-"][data-focused="true"]`), await rect(target)];
      if (Math.abs(to.top - from.top) > 5) await page.keyboard.press(to.top > from.top ? "ArrowDown" : "ArrowUp");
      else await page.keyboard.press(to.left > from.left ? "ArrowRight" : "ArrowLeft");
    }
    await expect(page.locator(target)).toHaveAttribute("data-focused", "true");
    await page.keyboard.press("Enter");
  }
}

async function clear(page: Page) {
  for (let i = 0; i < 64; i++) await page.keyboard.press("Backspace"); // the dialog's DEL
  await expect(page.getByTestId("api-base-value")).toHaveText("type here…");
}

test("TV-16 settings: set the API address with the D-pad, test it, keep it", async ({ page }) => {
  await page.route(`${BASE}/games`, (route) =>
    route.fulfill({ json: [{ id: "g1" }, { id: "g2" }], headers: { "access-control-allow-origin": "*" } }),
  );
  await page.goto("/");
  await expect(page.getByTestId("game-card").first()).toHaveAttribute("data-focused", "true");
  await page.keyboard.press("ArrowUp");
  await page.keyboard.press("ArrowRight");
  await expect(page.getByTestId("library-settings")).toHaveAttribute("data-focused", "true");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("settings")).toBeVisible();
  const shown = page.getByTestId("settings-api-base");
  await expect(shown).not.toHaveText("not set"); // the build default

  // Change address: a bad one is refused and leaves the saved address alone.
  await page.keyboard.press("ArrowLeft");
  await expect(page.getByTestId("settings-item-0")).toHaveAttribute("data-focused", "true");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("api-base-dialog")).toBeVisible();
  const before = await shown.textContent();
  await clear(page);
  await typeKeys(page, "api-base", ["/", "SAVE"]);
  await expect(page.getByTestId("api-base-dialog")).toHaveCount(0);
  await expect(page.getByTestId("settings-check")).toHaveText("Not an http address: /");
  await expect(shown).toHaveText(before ?? "");

  // A LAN address without a scheme: http:// is added, then it is tested.
  await page.keyboard.press("Enter");
  await clear(page);
  await typeKeys(page, "api-base", ["10.0.", "0", ".", "5", ":8000"]);
  await expect(page.getByTestId("api-base-value")).toHaveText("10.0.0.5:8000");
  await typeKeys(page, "api-base", ["SAVE"]);
  await expect(shown).toHaveText(BASE);
  await expect(page.getByTestId("settings-check")).toHaveText("Connected · 2 games");
  await expect(page.getByTestId("settings-check")).toHaveAttribute("data-state", "ok");

  // Kept across a restart; Done returns to the library.
  await page.goto("/tv/settings");
  await expect(shown).toHaveText(BASE);
  await expect(page.getByTestId("settings-check")).toHaveAttribute("data-state", "ok");
  await page.keyboard.press("ArrowRight");
  await expect(page.getByTestId("settings-item-2")).toHaveAttribute("data-focused", "true");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("game-card").first()).toBeVisible();
});

test("TV-16 settings: an unreachable address says so", async ({ page }) => {
  await page.route(`${BASE}/games`, (route) => route.abort("connectionrefused"));
  await page.addInitScript((b) => localStorage.setItem("replay.apiBase", b), BASE);
  await page.goto("/tv/settings");
  await expect(page.getByTestId("settings-api-base")).toHaveText(BASE);
  await expect(page.getByTestId("settings-check")).toHaveAttribute("data-state", "error");
  await expect(page.getByTestId("settings-check")).toContainText("Not reachable");
});
