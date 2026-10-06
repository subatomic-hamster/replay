// The Watch action menu on the browser TV harness (apps/tv's TV-14 is the RN twin): it
// used to be 16+ flat items that wrapped into two rows over the video at 1080p. Now the top
// row holds a few entries and three groups ("Game ▸", "Playback ▸", "Players ▸") that open
// their own row in its place: every row is one line, and every item is D-pad reachable.
import { expect, test, type Page } from "@playwright/test";
import { focusedMenuItem, menuRowsOneLine, menuTo, openWatch, smallText } from "./helpers";

async function ring(page: Page, id: string) {
  return page.getByTestId(id).evaluate((el) => {
    const s = getComputedStyle(el);
    return `${s.boxShadow}|${s.backgroundColor}`;
  });
}

test("S-50 every menu row is one line at the top of the screen, groups included", async ({ page }) => {
  await openWatch(page);
  await page.keyboard.press("ArrowUp");
  await expect(page.getByTestId("nav-library")).toHaveAttribute("data-focused", "true");
  await expect(page.getByTestId("nav-search")).toBeAttached();
  const nav = page.getByTestId("menu-row");

  const top = await menuRowsOneLine(page);
  expect(top.spread, "top row wraps").toBeLessThan(top.height / 2);
  expect(top.n).toBeGreaterThanOrEqual(5);
  expect(top.bottom).toBeLessThan(200);
  expect(await smallText(page)).toEqual([]);
  expect(await ring(page, "nav-library")).not.toBe(await ring(page, "action-broadcast"));

  for (const group of ["menu-game", "menu-playback", "menu-players"]) {
    for (let i = 0; i < 12 && (await focusedMenuItem(page)) !== group; i++) await page.keyboard.press("ArrowRight");
    await expect(page.getByTestId(group)).toHaveAttribute("data-focused", "true");
    await page.keyboard.press("Enter");
    await expect(nav).toHaveAttribute("data-group", group);
    await expect(page.getByTestId("nav-library")).toBeHidden();
    const row = await menuRowsOneLine(page);
    expect(row.spread, `${group} row wraps`).toBeLessThan(row.height / 2);
    expect(row.bottom).toBeLessThan(200);
    expect(await smallText(page)).toEqual([]);
    await page.keyboard.press("Escape"); // closes the group, focus back on its entry
    await expect(nav).toHaveAttribute("data-group", "");
    await expect(page.getByTestId(group)).toHaveAttribute("data-focused", "true");
  }

  await page.keyboard.press("Escape"); // closes the menu; still watching
  await expect(page.getByTestId("nav-library")).toHaveAttribute("data-focused", "false");
  await expect(page).toHaveURL(/\/tv\/g_mock01$/);
});

test("S-50 every menu item is reachable with the D-pad", async ({ page }) => {
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
    await page.keyboard.press("ArrowDown"); // closes the group, then the menu
    await page.keyboard.press("ArrowDown");
    await expect(page.getByTestId("nav-library")).toHaveAttribute("data-focused", "false");
  }
});
