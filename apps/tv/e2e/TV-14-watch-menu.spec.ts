// The Watch action menu at 1080p: it used to be 16+ flat items that wrapped into two rows
// over the video. Now the top row holds a few entries and three groups ("Game ▸",
// "Playback ▸", "Players ▸") that open their own row in its place, so every row is one
// line above the badges, and every item is still reachable with the D-pad.
import { expect, test, type Page } from "@playwright/test";
import { focusedMenuItem, menuRowsOneLine, menuTo, openWatch, smallText } from "./helpers";

async function ring(page: Page, id: string) {
  return page.getByTestId(id).evaluate((el) => {
    const s = getComputedStyle(el);
    return `${s.borderTopColor}|${s.boxShadow}|${s.outlineStyle}|${s.backgroundColor}`;
  });
}

async function modePillTop(page: Page) {
  return (await page.getByTestId("mode-pill").boundingBox())?.y ?? 0;
}

test("TV-14 every menu row is one line above the badges, groups included", async ({ page }) => {
  await openWatch(page);
  await page.keyboard.press("ArrowUp");
  await expect(page.getByTestId("nav-library")).toHaveAttribute("data-focused", "true");
  await expect(page.getByTestId("nav-search")).toBeAttached(); // the menu data has loaded

  const top = await menuRowsOneLine(page);
  expect(top.spread, "top row wraps").toBeLessThan(top.height / 2);
  expect(top.n).toBeGreaterThanOrEqual(5);
  expect(top.bottom).toBeLessThan(200);
  expect(top.bottom).toBeLessThanOrEqual(await modePillTop(page));
  expect(await smallText(page)).toEqual([]);
  // focus ring: the focused pill looks different from its neighbour
  expect(await ring(page, "nav-library")).not.toBe(await ring(page, "action-broadcast"));

  for (const group of ["menu-game", "menu-playback", "menu-players"]) {
    for (let i = 0; i < 12 && (await focusedMenuItem(page)) !== group; i++) await page.keyboard.press("ArrowRight");
    await expect(page.getByTestId(group)).toHaveAttribute("data-focused", "true");
    await page.keyboard.press("Enter");
    await expect(page.getByTestId(`menu-row-${group}`)).toHaveAttribute("data-open", "true");
    await expect(page.getByTestId("menu-row")).toHaveAttribute("data-open", "false");
    const row = await menuRowsOneLine(page);
    expect(row.spread, `${group} row wraps`).toBeLessThan(row.height / 2);
    expect(row.bottom).toBeLessThan(200);
    expect(row.bottom).toBeLessThanOrEqual(await modePillTop(page));
    expect(await smallText(page)).toEqual([]);
    // Back closes the group onto the top row, focus back on the group entry
    await page.keyboard.press("Escape");
    await expect(page.getByTestId("menu-row")).toHaveAttribute("data-open", "true");
    await expect(page.getByTestId(group)).toHaveAttribute("data-focused", "true");
  }

  // Back from the top row closes the menu; the game is still on screen.
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("nav-library")).toHaveAttribute("data-focused", "false");
  await expect(page.getByTestId("video")).toBeAttached();
});

test("TV-14 every menu item is reachable with the D-pad", async ({ page }) => {
  await openWatch(page);
  await page.keyboard.press("ArrowUp");
  await expect(page.getByTestId("nav-search")).toBeAttached();
  const ids = await page.evaluate(() =>
    [...document.querySelectorAll('[data-testid^="nav-"], [data-testid^="action-"]')].map(
      (el) => el.getAttribute("data-testid") ?? "",
    ),
  );
  await page.keyboard.press("Escape");
  expect(ids.length).toBeGreaterThanOrEqual(15);
  for (const id of ids) {
    await menuTo(page, id);
    // Down closes the group, then the menu (and is a no-op on the wide shot)
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("ArrowDown");
    await expect(page.getByTestId("nav-library")).toHaveAttribute("data-focused", "false");
  }
});
