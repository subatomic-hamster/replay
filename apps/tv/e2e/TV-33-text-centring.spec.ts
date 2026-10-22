import { expect, test, type Locator, type Page } from "@playwright/test";
import { openWatch } from "./helpers";

// TV-33 text centring: a label in a pill, row, key cap or badge has its capitals on the
// box's middle. Measured from pixels, not layout: the first glyph's ink (its columns of a
// screenshot of the box, pixels far from the box's fill) must be centred on the box within
// 0.75 px. Barlow's line box puts capitals low, so without T's lift every label here but
// the key cap read 1–1.5 px low (and 2.5 px on a Fire TV, where Android also padded the
// text box); with it they measure 0–0.5 px.

/** Ink centre minus box centre, px (+ = low), for the first visible glyph inside `box`. */
async function capOffset(page: Page, box: Locator): Promise<number> {
  const rect = await box.boundingBox();
  if (!rect) throw new Error("no box");
  const glyph = await box.evaluate((el) => {
    const walk = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    let n: Node | null;
    while ((n = walk.nextNode()) && !n.textContent?.trim());
    if (!n?.textContent) throw new Error("no text");
    const i = n.textContent.search(/\S/);
    const r = document.createRange();
    r.setStart(n, i);
    r.setEnd(n, i + 1);
    const b = r.getBoundingClientRect();
    return { left: b.left, right: b.right };
  });
  const png = await page.screenshot({ clip: rect });
  const x0 = Math.ceil(glyph.left - rect.x) + 1;
  const x1 = Math.floor(glyph.right - rect.x) - 1;
  const ink = await page.evaluate(
    async ({ b64, x0, x1 }) => {
      const img = new Image();
      img.src = `data:image/png;base64,${b64}`;
      await img.decode();
      const c = document.createElement("canvas");
      [c.width, c.height] = [img.width, img.height];
      const g = c.getContext("2d");
      if (!g) throw new Error("no 2d canvas");
      g.drawImage(img, 0, 0);
      const d = g.getImageData(0, 0, c.width, c.height).data;
      const at = (x: number, y: number) => {
        const k = (y * c.width + x) * 4;
        return [d[k], d[k + 1], d[k + 2]];
      };
      // the fill: just left of the glyph, mid-height (padding or the gap before it)
      const fill = at(Math.max(0, x0 - 6), Math.floor(c.height / 2));
      let [top, bottom] = [-1, -1];
      for (let y = 0; y < c.height; y++)
        for (let x = x0; x < x1; x++) {
          const p = at(x, y);
          const far =
            Math.abs(p[0] - fill[0]) +
              Math.abs(p[1] - fill[1]) +
              Math.abs(p[2] - fill[2]) >
            150;
          if (far) {
            if (top < 0) top = y;
            bottom = y;
          }
        }
      return { top, bottom, h: c.height };
    },
    { b64: png.toString("base64"), x0, x1 },
  );
  expect(ink.top, "glyph ink found").toBeGreaterThanOrEqual(0);
  return (ink.top + ink.bottom + 1) / 2 - ink.h / 2;
}

async function expectCentred(page: Page, box: Locator, what: string) {
  await expect(box).toBeVisible();
  await page.waitForTimeout(300); // focus scale / fill transitions settle
  const off = await capOffset(page, box);
  expect(
    Math.abs(off),
    `${what}: capitals ${off.toFixed(1)} px off centre`,
  ).toBeLessThanOrEqual(0.75);
}

test("TV-33 labels sit on the middle of their pills, rows, key caps and badges", async ({
  page,
}) => {
  await page.goto("/tv/settings");
  await page.evaluate(() => document.fonts.ready);
  await expectCentred(
    page,
    page.getByTestId("settings-item-2"),
    "settings row",
  );
  await expectCentred(
    page,
    page.getByTestId("settings-item-0"),
    "focused settings row", // Settings opens on its first row
  );
  // a key legend's cap (the first box inside the entry)
  const cap = (k: string) =>
    page.getByTestId(`legend-${k}`).locator("div").first();
  await expectCentred(page, cap("Select"), "Select key cap");

  await page.keyboard.press("Escape"); // Home
  await expect(page.getByTestId("home")).toBeVisible();
  await expectCentred(page, page.getByTestId("hero-play"), "Play pill");
  await page.keyboard.press("ArrowUp");
  await expect(page.getByTestId("hero-play")).toHaveAttribute(
    "data-focused",
    "true",
  );
  await expectCentred(page, page.getByTestId("hero-play"), "focused Play pill");

  await openWatch(page);
  await page.keyboard.press("ArrowDown");
  await expect(page.getByTestId("moments-layer")).toBeVisible();
  await expectCentred(
    page,
    page.getByTestId("moment-filter").nth(1),
    "filter chip",
  );
  await expectCentred(
    page,
    page.getByTestId("moment-time").first(),
    "moment time badge",
  );
});

test("TV-33 a real game's many players add no Moments chips: the whole row and the legend sit on screen, clear of the cards", async ({
  page,
}) => {
  // A real game: 14 more tracked players, each with a moment (19 chips before the UI
  // pass). The mock is patched before the player mounts (Settings → Home → the featured
  // game).
  await page.goto("/tv/settings");
  await expect(page.getByTestId("settings")).toBeVisible();
  await page.evaluate(() => {
    type M = { id: string; t: number; player?: unknown };
    const api = (
      window as unknown as {
        __replayMock: { api: { getMoments: (id: string) => Promise<M[]> } };
      }
    ).__replayMock.api;
    const get = api.getMoments.bind(api);
    api.getMoments = async (id) => {
      const list = await get(id);
      return list.concat(
        Array.from({ length: 14 }, (_, k) => ({
          ...list[0],
          id: `extra${k}`,
          t: list[0].t + (k + 1) / 10,
          player: { id: `p${20 + k}`, name: null, color_hex: "#888888" },
        })),
      );
    };
  });
  await page.keyboard.press("Escape"); // Home
  await expect(page.getByTestId("home")).toBeVisible();
  await page.keyboard.press("Enter"); // the featured game
  await expect(page.getByTestId("video")).toBeAttached();
  await page.keyboard.press("ArrowDown");
  await expect(page.getByTestId("moment-card").first()).toBeVisible();
  await page.keyboard.press("ArrowUp"); // to the row
  const chips = page.getByTestId("moment-filter");
  expect(await chips.allTextContents()).toEqual(["All 18", "Scores"]);
  for (let i = 0; i < 4; i++) await page.keyboard.press("ArrowRight");
  const last = page.getByTestId("moment-bookmark");
  await expect(last).toHaveAttribute("data-focused", "true");
  const box = (await last.boundingBox())!;
  expect(box.x + box.width).toBeLessThanOrEqual(1920 - 96 + 1);
  // the legend: inside the right safe edge, below every card label, above the timeline
  const legend = (await page.getByTestId("key-legend").boundingBox())!;
  expect(legend.x + legend.width).toBeLessThanOrEqual(1920 - 96 + 1);
  const layer = (await page.getByTestId("moments-layer").boundingBox())!;
  expect(legend.y).toBeGreaterThanOrEqual(layer.y + layer.height - 1);
  const line = (await page.getByTestId("timeline").boundingBox())!;
  expect(legend.y + legend.height).toBeLessThanOrEqual(line.y + 1);
});
