import { expect, test, type Page } from "@playwright/test";

// The API address and key on the TV: reached from the library with the D-pad, typed on the
// on-screen keyboard, normalized, tested against the API (GET /games) and kept on the device.
// The key (D-80 X-Replay-Key) is sent on the test and never shown beyond its last 4 characters.
const BASE = "http://10.0.0.5:8000";
const KEY = "c0ffee42beef";

/** Walk the on-screen keyboard to each key label with the arrows, and Select it. */
async function typeKeys(page: Page, prefix: string, labels: string[]) {
  const rect = (sel: string) =>
    page
      .locator(sel)
      .first()
      .evaluate((el) => el.getBoundingClientRect().toJSON());
  for (const label of labels) {
    const target = `[data-testid="${prefix}-key-${label}"]`;
    for (
      let i = 0;
      i < 30 &&
      (await page.locator(target).getAttribute("data-focused")) !== "true";
      i++
    ) {
      const [from, to] = [
        await rect(`[data-testid^="${prefix}-key-"][data-focused="true"]`),
        await rect(target),
      ];
      if (Math.abs(to.top - from.top) > 5)
        await page.keyboard.press(to.top > from.top ? "ArrowDown" : "ArrowUp");
      else
        await page.keyboard.press(
          to.left > from.left ? "ArrowRight" : "ArrowLeft",
        );
    }
    await expect(page.locator(target)).toHaveAttribute("data-focused", "true");
    await page.keyboard.press("Enter");
  }
}

async function clear(page: Page) {
  for (let i = 0; i < 64; i++) await page.keyboard.press("Backspace"); // the dialog's DEL
  await expect(page.getByTestId("api-base-value")).toHaveText("type here…");
}

test("TV-16 settings: set the API address and key with the D-pad, test it, keep it", async ({
  page,
}) => {
  const sentKeys: (string | undefined)[] = [];
  await page.route(`${BASE}/games`, (route) => {
    const cors = {
      "access-control-allow-origin": "*",
      "access-control-allow-headers": "*",
      "access-control-allow-methods": "GET, OPTIONS",
    };
    if (route.request().method() === "OPTIONS")
      return route.fulfill({ status: 204, headers: cors });
    sentKeys.push(route.request().headers()["x-replay-key"]);
    return route.fulfill({ json: [{ id: "g1" }, { id: "g2" }], headers: cors });
  });
  await page.goto("/");
  await expect(
    page.locator('[data-testid="game-card"][data-focused="true"]'),
  ).toBeVisible();
  await page.keyboard.press("ArrowUp"); // the hero's Play
  await expect(page.getByTestId("hero-play")).toHaveAttribute(
    "data-focused",
    "true",
  );
  await page.keyboard.press("ArrowUp"); // the gear
  await expect(page.getByTestId("library-settings")).toHaveAttribute(
    "data-focused",
    "true",
  );
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("settings")).toBeVisible();
  const shown = page.getByTestId("settings-api-base");
  await expect(shown).not.toHaveText("not set"); // the build default
  await expect(page.getByTestId("settings-api-key")).toHaveText("none");
  await expect(page.getByTestId("settings-item-2")).toHaveAttribute(
    "data-focused",
    "true",
  ); // Test connection

  // Change address: a bad one is refused and leaves the saved address alone.
  await page.keyboard.press("ArrowLeft");
  await page.keyboard.press("ArrowLeft");
  await expect(page.getByTestId("settings-item-0")).toHaveAttribute(
    "data-focused",
    "true",
  );
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("api-base-dialog")).toBeVisible();
  const before = await shown.textContent();
  await clear(page);
  await typeKeys(page, "api-base", ["/", "SAVE"]);
  await expect(page.getByTestId("api-base-dialog")).toHaveCount(0);
  await expect(page.getByTestId("settings-check")).toHaveText(
    "Not an http address: /",
  );
  await expect(shown).toHaveText(before ?? "");

  // A LAN address without a scheme: http:// is added, then it is tested.
  await page.keyboard.press("Enter");
  await clear(page);
  await typeKeys(page, "api-base", ["10.0.", "0", ".", "5", ":8000"]);
  await expect(page.getByTestId("api-base-value")).toHaveText("10.0.0.5:8000");
  await typeKeys(page, "api-base", ["SAVE"]);
  await expect(shown).toHaveText(BASE);
  await expect(page.getByTestId("settings-check")).toHaveText(
    "Connected · 2 games",
  );
  await expect(page.getByTestId("settings-check")).toHaveAttribute(
    "data-state",
    "ok",
  );
  expect(sentKeys.at(-1)).toBeUndefined();

  // API key: typed masked (last 4 only), saved, sent on the next test.
  await page.keyboard.press("ArrowLeft");
  await expect(page.getByTestId("settings-item-1")).toHaveAttribute(
    "data-focused",
    "true",
  );
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("api-key-dialog")).toBeVisible();
  await typeKeys(page, "api-key", [...KEY.toUpperCase()]);
  await expect(page.getByTestId("api-key-value")).toHaveText("••••beef");
  await typeKeys(page, "api-key", ["SAVE"]);
  await expect(page.getByTestId("api-key-dialog")).toHaveCount(0);
  await expect(page.getByTestId("settings-api-key")).toHaveText("••••beef");
  await expect(page.getByTestId("settings-check")).toHaveText(
    "Connected · 2 games",
  );
  expect(sentKeys.at(-1)).toBe(KEY);
  await expect(page.locator("body")).not.toContainText(KEY);

  // Both kept across a restart (the key wins over the build's, which is empty here); Done
  // returns to the library.
  await page.goto("/tv/settings");
  await expect(shown).toHaveText(BASE);
  await expect(page.getByTestId("settings-api-key")).toHaveText("••••beef");
  await expect(page.getByTestId("settings-check")).toHaveAttribute(
    "data-state",
    "ok",
  );
  expect(sentKeys.at(-1)).toBe(KEY);
  expect(await page.evaluate(() => localStorage.getItem("replay.apiKey"))).toBe(
    KEY,
  );
  await page.keyboard.press("ArrowRight");
  await expect(page.getByTestId("settings-item-3")).toHaveAttribute(
    "data-focused",
    "true",
  );
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("game-card").first()).toBeVisible();
});

test("TV-16 settings: an unreachable address says so", async ({ page }) => {
  await page.route(`${BASE}/games`, (route) =>
    route.abort("connectionrefused"),
  );
  await page.addInitScript(
    (b) => localStorage.setItem("replay.apiBase", b),
    BASE,
  );
  await page.goto("/tv/settings");
  await expect(page.getByTestId("settings-api-base")).toHaveText(BASE);
  await expect(page.getByTestId("settings-check")).toHaveAttribute(
    "data-state",
    "error",
  );
  await expect(page.getByTestId("settings-check")).toContainText(
    "Not reachable",
  );
});

test("TV-16 the library's error banner keeps the D-pad when a later request fails too", async ({
  page,
}) => {
  // Seen on a Fire TV Stick: /games failed first, /profiles a moment later; Home re-rendered
  // and its key handler went back above the banner's, so Right never reached Settings.
  await page.goto("/tv/settings");
  await expect(page.getByTestId("settings")).toBeVisible();
  await page.evaluate(() => {
    type Api = {
      listGames: () => Promise<unknown>;
      listProfiles: () => Promise<unknown>;
    };
    const m = (window as unknown as { __replayMock: { api: Api } }).__replayMock
      .api;
    const fail = () => new Error("Network request failed");
    m.listGames = () => Promise.reject(fail());
    m.listProfiles = () =>
      new Promise((_, reject) => setTimeout(() => reject(fail()), 800));
  });
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("api-error")).toBeVisible();
  await page.waitForTimeout(1200); // the /profiles failure has landed
  await page.keyboard.press("ArrowRight");
  await expect(page.getByTestId("api-error-settings")).toHaveAttribute(
    "data-focused",
    "true",
  );
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("settings")).toBeVisible();
});
