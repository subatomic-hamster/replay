import { expect, test, type Page } from "@playwright/test";
import { mockCalls } from "./helpers";

// S-04b (D-23): the calibration page proposes the landmarks instead of making the user
// click them. Accept, adjust, or fall back to the manual walk that S-04 covers.

async function createUploadAndCalibrate(page: Page) {
  await page.goto("/upload");
  await page.getByTestId("game-title-input").fill("Auto calib");
  await page.getByTestId("sport-option-basketball").check();
  await page.getByTestId("create-game").click();
  await expect.poll(() => new URL(page.url()).pathname).toMatch(/^\/upload\/g_/);

  await page.getByTestId("file-input").setInputFiles({
    name: "synth-bball-half-5v5.mp4",
    mimeType: "video/mp4",
    buffer: Buffer.from("not a real mp4, the mock never decodes it"),
  });
  await expect(page.getByTestId("upload-done")).toBeVisible({ timeout: 10_000 });
  await page.getByTestId("go-calibrate").click();
  await expect(page.getByTestId("calib-image")).toBeVisible();
  return new URL(page.url()).pathname.split("/")[2];
}

async function waitForProposal(page: Page) {
  await expect(page.getByTestId("autocalib-accept")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId("autocalib-status")).toContainText("Found 5 points");
}

test("S-04b a proposal appears and accepting it opens the gate", async ({ page }) => {
  const id = await createUploadAndCalibrate(page);

  // The page asks for a proposal by itself, with a spinner over the frame meanwhile.
  await expect
    .poll(async () =>
      ((await mockCalls(page)) ?? []).some((c) => c.path === `/games/${id}/calibration/auto`),
    )
    .toBe(true);
  await waitForProposal(page);
  await expect(page.getByTestId("autocalib-status")).toContainText("3.4 px");

  // Five dots, and the low-confidence one is drawn hollow for the user to place.
  await expect(page.locator('[data-testid^="landmark-"]')).toHaveCount(5);
  await expect(page.getByTestId("landmark-rim")).toHaveClass(/hollow/);
  await expect(page.getByTestId("landmark-corner_nl")).not.toHaveClass(/hollow/);
  await expect(page.getByTestId("landmark-corner_nl")).toHaveAttribute("data-confidence", "0.93");

  // Nothing has been committed yet: the proposal is not a calibration (D-23).
  expect((await mockCalls(page)).filter((c) => c.path.endsWith("/calibration"))).toHaveLength(0);
  await expect(page.getByTestId("start-processing")).toBeDisabled();

  await page.getByTestId("autocalib-accept").click();

  const calib = (await mockCalls(page)).filter((c) => c.path.endsWith("/calibration"));
  expect(calib).toHaveLength(1);
  // Only the confident points are committed; `rim` stayed hollow.
  expect(Object.keys((calib[0].body as { landmarks_px: object }).landmarks_px).sort()).toEqual([
    "corner_fl",
    "corner_fr",
    "corner_nl",
    "corner_nr",
  ]);
  await expect(page.getByTestId("calib-error")).toHaveAttribute("data-ok", "true");
  await expect(page.getByTestId("start-processing")).toBeEnabled();
  await expect(page.getByTestId("autocalib-accept")).toHaveCount(0);
});

test("S-04b adjust makes every point draggable and re-validates on release", async ({ page }) => {
  await createUploadAndCalibrate(page);
  await waitForProposal(page);
  await page.getByTestId("autocalib-adjust").click();

  await expect(page.getByTestId("autocalib-status")).toContainText("Drag any point");
  await expect(page.locator('[data-testid^="landmark-handle-"]')).toHaveCount(5);

  const handle = page.getByTestId("landmark-handle-corner_nl");
  const box = (await handle.boundingBox())!;
  // 44 px touch target (S-04b / accessibility floor).
  expect(box.width).toBeGreaterThanOrEqual(44);
  expect(box.height).toBeGreaterThanOrEqual(44);

  const before = await page.getByTestId("calib-error").textContent();
  const from = { x: box.x + box.width / 2, y: box.y + box.height / 2 };
  await page.mouse.move(from.x, from.y);
  await page.mouse.down();
  await page.mouse.move(from.x + 15, from.y - 15, { steps: 5 });
  await page.mouse.move(from.x + 30, from.y - 30, { steps: 5 });
  await page.mouse.up();

  // The dot followed the pointer...
  await expect
    .poll(async () => (await page.getByTestId("landmark-corner_nl").boundingBox())!.x)
    .toBeGreaterThan(box.x + 10);
  // ...and the release re-posted the calibration, so the error is a fresh number.
  await expect.poll(() => page.getByTestId("calib-error").textContent()).not.toBe(before);
  await expect(page.getByTestId("calib-error")).toHaveAttribute("data-ok", "true");
  await expect(page.getByTestId("start-processing")).toBeEnabled();

  const calib = (await mockCalls(page)).filter((c) => c.path.endsWith("/calibration"));
  expect(calib.length).toBeGreaterThanOrEqual(2);
  const first = (calib[0].body as { landmarks_px: Record<string, [number, number]> }).landmarks_px;
  const last = (calib.at(-1)!.body as { landmarks_px: Record<string, [number, number]> })
    .landmarks_px;
  expect(last.corner_nl[0]).toBeGreaterThan(first.corner_nl[0]);
});

test("S-04b the manual walk is still there for anyone who wants it", async ({ page }) => {
  await createUploadAndCalibrate(page);
  await waitForProposal(page);
  await page.getByTestId("autocalib-manual").click();

  // The proposal is off the frame and the walk starts from the first landmark.
  await expect(page.locator('[data-testid^="landmark-"]')).toHaveCount(0);
  await expect(page.getByTestId("autocalib-status")).toContainText("by hand");
  await expect(page.getByTestId("calib-prompt")).toContainText("corner nl");
  await expect(page.getByTestId("start-processing")).toBeDisabled();

  const img = page.getByTestId("calib-image");
  const frame = (await img.boundingBox())!;
  for (const p of [
    { x: 0.12, y: 0.86 },
    { x: 0.88, y: 0.86 },
    { x: 0.34, y: 0.3 },
    { x: 0.68, y: 0.3 },
    { x: 0.5, y: 0.36 },
  ]) {
    await img.click({ position: { x: frame.width * p.x, y: frame.height * p.y } });
  }
  await expect(page.locator('[data-testid^="landmark-"]')).toHaveCount(5);
  await expect(page.getByTestId("calib-error")).toHaveAttribute("data-ok", "true");
  await expect(page.getByTestId("start-processing")).toBeEnabled();
});
