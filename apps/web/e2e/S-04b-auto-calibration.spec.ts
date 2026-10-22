import { expect, test, type Page } from "@playwright/test";
import { mockCalls } from "./helpers";

// S-04b (D-23): the calibration page proposes the landmarks instead of making the user
// click them. Accept, adjust, or fall back to the manual walk that S-04 covers.

async function createUploadAndCalibrate(page: Page, title = "Auto calib") {
  await page.goto("/upload");
  await page.getByTestId("game-title-input").fill(title);
  await page.getByTestId("sport-option-basketball").check();
  await page.getByTestId("create-game").click();
  await expect
    .poll(() => new URL(page.url()).pathname)
    .toMatch(/^\/upload\/g_/);

  await page.getByTestId("file-input").setInputFiles({
    name: "synth-bball-half-5v5.mp4",
    mimeType: "video/mp4",
    buffer: Buffer.from("not a real mp4, the mock never decodes it"),
  });
  await expect(page.getByTestId("upload-done")).toBeVisible({
    timeout: 10_000,
  });
  await page.getByTestId("go-calibrate").click();
  await expect(page.getByTestId("calib-image")).toBeVisible();
  return new URL(page.url()).pathname.split("/")[2];
}

async function waitForProposal(page: Page) {
  await expect(page.getByTestId("autocalib-accept")).toBeVisible({
    timeout: 15_000,
  });
  await expect(page.getByTestId("autocalib-status")).toContainText(
    "Found 5 points",
  );
}

test("S-04b a proposal appears and accepting it opens the gate", async ({
  page,
}) => {
  const id = await createUploadAndCalibrate(page);

  // The page asks for a proposal by itself, with a spinner over the frame meanwhile.
  await expect
    .poll(async () =>
      ((await mockCalls(page)) ?? []).some(
        (c) => c.path === `/games/${id}/calibration/auto`,
      ),
    )
    .toBe(true);
  await waitForProposal(page);
  // UI pass: plain words, no pixel residual on the proposal line
  await expect(page.getByTestId("autocalib-status")).not.toContainText("px");

  // Five dots, and the low-confidence one is drawn hollow for the user to place.
  await expect(page.locator('[data-testid^="landmark-"]')).toHaveCount(5);
  await expect(page.getByTestId("landmark-rim")).toHaveClass(/hollow/);
  await expect(page.getByTestId("landmark-corner_nl")).not.toHaveClass(
    /hollow/,
  );
  await expect(page.getByTestId("landmark-corner_nl")).toHaveAttribute(
    "data-confidence",
    "0.93",
  );

  // Nothing has been committed yet: the proposal is not a calibration (D-23).
  expect(
    (await mockCalls(page)).filter((c) => c.path.endsWith("/calibration")),
  ).toHaveLength(0);
  await expect(page.getByTestId("start-processing")).toBeDisabled();

  await page.getByTestId("autocalib-accept").click();

  const calib = (await mockCalls(page)).filter((c) =>
    c.path.endsWith("/calibration"),
  );
  expect(calib).toHaveLength(1);
  // Only the confident points are committed; `rim` stayed hollow.
  expect(
    Object.keys(
      (calib[0].body as { landmarks_px: object }).landmarks_px,
    ).sort(),
  ).toEqual(["corner_fl", "corner_fr", "corner_nl", "corner_nr"]);
  await expect(page.getByTestId("calib-error")).toHaveAttribute(
    "data-ok",
    "true",
  );
  await expect(page.getByTestId("start-processing")).toBeEnabled();
  await expect(page.getByTestId("autocalib-accept")).toHaveCount(0);
});

test("S-04b adjust makes every point draggable and re-validates on release", async ({
  page,
}) => {
  await createUploadAndCalibrate(page);
  await waitForProposal(page);
  await page.getByTestId("autocalib-adjust").click();

  await expect(page.getByTestId("autocalib-status")).toContainText(
    "Drag any point",
  );
  await expect(page.locator('[data-testid^="landmark-handle-"]')).toHaveCount(
    5,
  );

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
    .poll(
      async () =>
        (await page.getByTestId("landmark-corner_nl").boundingBox())!.x,
    )
    .toBeGreaterThan(box.x + 10);
  // ...and the release re-posted the calibration, so the error is a fresh number.
  await expect
    .poll(() => page.getByTestId("calib-error").textContent())
    .not.toBe(before);
  await expect(page.getByTestId("calib-error")).toHaveAttribute(
    "data-ok",
    "true",
  );
  await expect(page.getByTestId("start-processing")).toBeEnabled();

  const calib = (await mockCalls(page)).filter((c) =>
    c.path.endsWith("/calibration"),
  );
  expect(calib.length).toBeGreaterThanOrEqual(2);
  const first = (
    calib[0].body as { landmarks_px: Record<string, [number, number]> }
  ).landmarks_px;
  const last = (
    calib.at(-1)!.body as { landmarks_px: Record<string, [number, number]> }
  ).landmarks_px;
  expect(last.corner_nl[0]).toBeGreaterThan(first.corner_nl[0]);
});

// D-23: ok=false is dots to drag, not dots to accept. The CC pickleball run used a 0.74
// fit unchecked: court 100-400 px too high, 0 events.
test("S-04b-10 a not-ok proposal needs a drag or an explicit confirm", async ({
  page,
}) => {
  // The mock answers a game titled "low confidence" with the same dots at ok=false.
  await createUploadAndCalibrate(page, "Auto calib low confidence");
  await waitForProposal(page);
  await expect(page.getByTestId("autocalib-status")).toContainText(
    "needs a check",
  );
  await expect(page.getByTestId("autocalib-weak")).toContainText(
    "score 0.74 < 0.90",
  );
  // The dots are still there to drag; Accept is not, until the user confirms.
  await expect(page.locator('[data-testid^="landmark-"]')).toHaveCount(5);
  await expect(page.getByTestId("autocalib-accept")).toBeDisabled();

  const posts = async () =>
    (await mockCalls(page)).filter((c) => c.path.endsWith("/calibration")) as {
      body: {
        landmarks_px: Record<string, [number, number]>;
        accept_low_confidence?: boolean;
      };
    }[];

  // Adjust without moving anything: the unmoved dots are refused, the gate stays shut.
  await page.getByTestId("autocalib-adjust").click();
  await expect(page.getByTestId("calib-error")).toHaveAttribute(
    "data-ok",
    "false",
  );
  await expect(page.getByTestId("calib-error")).toContainText("not ok");
  await expect(page.getByTestId("start-processing")).toBeDisabled();

  // A drag is a manual adjustment: accepted without the confirm.
  const handle = page.getByTestId("landmark-handle-corner_nl");
  const box = (await handle.boundingBox())!;
  const from = { x: box.x + box.width / 2, y: box.y + box.height / 2 };
  await page.mouse.move(from.x, from.y);
  await page.mouse.down();
  await page.mouse.move(from.x + 15, from.y - 15, { steps: 5 });
  await page.mouse.up();
  await expect(page.getByTestId("calib-error")).toHaveAttribute(
    "data-ok",
    "true",
  );
  await expect(page.getByTestId("start-processing")).toBeEnabled();
  expect((await posts()).at(-1)!.body.accept_low_confidence).toBe(false);
});

test("S-04b-11 a not-ok proposal can be accepted as-is only with the confirm ticked", async ({
  page,
}) => {
  await createUploadAndCalibrate(page, "Auto calib low confidence");
  await waitForProposal(page);
  await expect(page.getByTestId("autocalib-accept")).toBeDisabled();
  await page.getByTestId("autocalib-confirm").check();
  await page.getByTestId("autocalib-accept").click();

  const calib = (await mockCalls(page)).filter((c) =>
    c.path.endsWith("/calibration"),
  );
  expect(calib).toHaveLength(1);
  expect(
    (calib[0].body as { accept_low_confidence: boolean }).accept_low_confidence,
  ).toBe(true);
  await expect(page.getByTestId("calib-error")).toHaveAttribute(
    "data-ok",
    "true",
  );
  await expect(page.getByTestId("start-processing")).toBeEnabled();
});

test("S-04b the manual walk is still there for anyone who wants it", async ({
  page,
}) => {
  await createUploadAndCalibrate(page);
  await waitForProposal(page);
  await page.getByTestId("autocalib-manual").click();

  // The proposal is off the frame and the walk starts from the first landmark.
  await expect(page.locator('[data-testid^="landmark-"]')).toHaveCount(0);
  await expect(page.getByTestId("autocalib-status")).toContainText("by hand");
  await expect(page.getByTestId("calib-prompt")).toContainText(
    "Tap the near-left corner",
  );
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
    await img.click({
      position: { x: frame.width * p.x, y: frame.height * p.y },
    });
  }
  await expect(page.locator('[data-testid^="landmark-"]')).toHaveCount(5);
  await expect(page.getByTestId("calib-error")).toHaveAttribute(
    "data-ok",
    "true",
  );
  await expect(page.getByTestId("start-processing")).toBeEnabled();
});

// Recording R-07 hit a dead end: after "Adjust" the walk cursor was parked past the last
// landmark, so "Not visible" was disabled and a wrongly proposed required point (an
// invented off-frame corner) could only be removed by undoing back through every drag.
test("S-04b-7 in Adjust, a selected point can be marked not visible and the rest walked", async ({
  page,
}) => {
  await createUploadAndCalibrate(page);
  await waitForProposal(page);
  await page.getByTestId("autocalib-adjust").click();
  await expect(page.getByTestId("autocalib-status")).toHaveAttribute(
    "data-state",
    "applied",
  );

  // The walk carries on with what the proposal left uncommitted: `rim` is hollow.
  await expect(page.getByTestId("calib-prompt")).toContainText(
    "Tap the rim — point 5 of 5",
  );
  await expect(page.getByTestId("calib-skip")).toBeEnabled();
  // One chip per point: the list way to pick one, whatever the walk is waiting for.
  await expect(page.locator('[data-testid^="calib-point-"]')).toHaveCount(5);

  const posts = async () =>
    (await mockCalls(page)).filter((c) => c.path.endsWith("/calibration")) as {
      body: { landmarks_px: Record<string, [number, number]> };
    }[];
  const before = (await page.getByTestId("landmark-corner_fl").boundingBox())!;
  await page.getByTestId("calib-point-corner_fl").click();
  await expect(page.getByTestId("calib-point-corner_fl")).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await expect(page.getByTestId("landmark-handle-corner_fl")).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await expect(page.getByTestId("calib-prompt")).toHaveAttribute(
    "data-target",
    "corner_fl",
  );
  expect(
    (await page.getByTestId("landmark-corner_fl").boundingBox())!.x,
  ).toBeCloseTo(before.x, 0);

  // "Not visible" takes it off; three points are below the API's floor of four, so the
  // gate shuts and nothing is posted.
  const sent = (await posts()).length;
  await page.getByTestId("calib-skip").click();
  await expect(page.getByTestId("landmark-corner_fl")).toHaveCount(0);
  await expect(page.getByTestId("landmark-handle-corner_fl")).toHaveCount(0);
  await expect(page.getByTestId("calib-error")).toHaveAttribute(
    "data-ok",
    "false",
  );
  await expect(page.getByTestId("start-processing")).toBeDisabled();
  expect((await posts()).length).toBe(sent);

  // The walk does not ask for it again: next up is still the hollow rim. Tapping right on
  // rim's own handle places rim there — while a point is pending, a handle tap is a
  // frame tap (R-07: two landmarks 15 px apart share one 44 px handle's footprint).
  await expect(page.getByTestId("calib-prompt")).toHaveAttribute(
    "data-target",
    "rim",
  );
  await page.getByTestId("landmark-handle-rim").click();
  await expect(page.getByTestId("landmark-rim")).not.toHaveClass(/hollow/);
  await expect(page.getByTestId("calib-prompt")).toContainText(
    "All landmarks placed.",
  );
  await expect(page.getByTestId("calib-error")).toHaveAttribute(
    "data-ok",
    "true",
  );
  await expect(page.getByTestId("start-processing")).toBeEnabled();
  expect(Object.keys((await posts()).at(-1)!.body.landmarks_px).sort()).toEqual(
    ["corner_fr", "corner_nl", "corner_nr", "rim"],
  );

  // Nothing pending now, so tapping a handle (no drag) selects it; a frame tap re-places it.
  await page.getByTestId("landmark-handle-corner_nr").click();
  await expect(page.getByTestId("landmark-handle-corner_nr")).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  const img = page.getByTestId("calib-image");
  const frame = (await img.boundingBox())!;
  await img.click({
    position: { x: frame.width * 0.8, y: frame.height * 0.8 },
  });
  await expect(page.getByTestId("landmark-handle-corner_nr")).toHaveAttribute(
    "aria-pressed",
    "false",
  );
  const body = (await posts()).at(-1)!.body;
  expect(Object.keys(body.landmarks_px).sort()).toEqual([
    "corner_fr",
    "corner_nl",
    "corner_nr",
    "rim",
  ]);
  expect(body.landmarks_px.corner_nr[0]).toBeCloseTo(1280 * 0.8, -1);
  expect(body.landmarks_px.corner_nr[1]).toBeCloseTo(720 * 0.8, -1);
});

// R-07 again: at 1920x1080 with the auto-calibration panel up, `100vh - 300px` left
// Start processing below the fold.
test("S-04b-8 frame and controls fit a 1080p viewport with the proposal panel up", async ({
  page,
}) => {
  await createUploadAndCalibrate(page);
  await waitForProposal(page);
  const bottom = async (id: string) => {
    const b = (await page.getByTestId(id).boundingBox())!;
    return b.y + b.height;
  };
  for (const id of [
    "calib-image",
    "autocalib-manual",
    "calib-skip",
    "start-processing",
  ]) {
    expect(await bottom(id), `${id} is on screen`).toBeLessThanOrEqual(1080);
  }
  const doc = await page.evaluate(() => ({
    h: document.documentElement.scrollHeight,
    w: document.documentElement.scrollWidth,
  }));
  expect(doc.h).toBeLessThanOrEqual(1080);
  expect(doc.w).toBeLessThanOrEqual(1920);
  // The frame still gets most of the screen: tap precision is the point (RESULTS.md).
  expect(
    (await page.getByTestId("calib-image").boundingBox())!.height,
  ).toBeGreaterThanOrEqual(700);
  // Adjust swaps the panel's buttons for the point chips; still no scrolling.
  await page.getByTestId("autocalib-adjust").click();
  await expect(page.getByTestId("calib-point-rim")).toBeVisible();
  for (const id of [
    "calib-image",
    "calib-point-rim",
    "calib-skip",
    "start-processing",
  ]) {
    expect(
      await bottom(id),
      `${id} is on screen in Adjust`,
    ).toBeLessThanOrEqual(1080);
  }
});

test("S-04b-9 on a phone the calibrate page stacks and never scrolls sideways", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await createUploadAndCalibrate(page);
  await waitForProposal(page);
  const img = (await page.getByTestId("calib-image").boundingBox())!;
  expect(img.x).toBeGreaterThanOrEqual(0);
  expect(img.x + img.width).toBeLessThanOrEqual(390);
  const prompt = (await page.getByTestId("calib-prompt").boundingBox())!;
  expect(prompt.y, "stacked: the prompt sits above the frame").toBeLessThan(
    img.y,
  );
  const w = await page.evaluate(() => document.documentElement.scrollWidth);
  expect(w).toBeLessThanOrEqual(390);
  await page.getByTestId("autocalib-accept").click();
  await page.getByTestId("start-processing").scrollIntoViewIfNeeded();
  await expect(page.getByTestId("start-processing")).toBeEnabled();
});
