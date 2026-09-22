import { expect, test, type Page } from "@playwright/test";
import { mockCalls } from "./helpers";

// S-03 upload progress, S-04/S-05 calibration, S-06 the gate, S-07/S-08 processing.
// The mock API is per-page state, so this walks the real in-app flow rather than
// deep-linking to a game that a reload would forget.

const LANDMARK_CLICKS = [
  { x: 0.12, y: 0.86 }, // corner_nl
  { x: 0.88, y: 0.86 }, // corner_nr
  { x: 0.34, y: 0.3 }, // corner_fl
  { x: 0.68, y: 0.3 }, // corner_fr
  { x: 0.5, y: 0.36 }, // rim
];

async function createAndUpload(page: Page, sport = "basketball") {
  await page.goto("/upload");
  await page.getByTestId("game-title-input").fill("Test Game");
  await page.getByTestId(`sport-option-${sport}`).check();
  await page.getByTestId("create-game").click();
  await expect.poll(() => new URL(page.url()).pathname).toMatch(/^\/upload\/g_/);

  await page.getByTestId("file-input").setInputFiles({
    name: "synth-bball-half-5v5.mp4",
    mimeType: "video/mp4",
    buffer: Buffer.from("not a real mp4, the mock never decodes it"),
  });

  // S-03: progress runs to 100 and the done marker appears.
  await expect(page.getByTestId("upload-progress")).toBeVisible();
  await expect(page.getByTestId("upload-done")).toBeVisible({ timeout: 10_000 });
  await expect(page.getByTestId("upload-progress")).toHaveJSProperty("value", 100);

  await page.getByTestId("go-calibrate").click();
  await expect(page.getByTestId("calib-image")).toBeVisible();
  return new URL(page.url()).pathname.split("/")[2];
}

async function clickLandmarks(page: Page, n = 5) {
  const img = page.getByTestId("calib-image");
  const box = (await img.boundingBox())!;
  for (const p of LANDMARK_CLICKS.slice(0, n)) {
    await img.click({ position: { x: box.width * p.x, y: box.height * p.y } });
  }
}

test("S-04/S-06 five landmarks give a reprojection error and unlock Start", async ({ page }) => {
  // The stage poll below waits up to 40 s; the default test timeout is 30 s, so under
  // load the test died before its own assertion could fail (bug 6).
  test.setTimeout(90_000);
  const id = await createAndUpload(page);

  // E-05: the gate is shut and the error field says what is missing, not a stale number.
  await expect(page.getByTestId("start-processing")).toBeDisabled();
  await expect(page.getByTestId("calib-error")).toContainText("need 5 more points");
  await expect(page.getByTestId("calib-prompt")).toContainText("corner nl");

  await clickLandmarks(page, 4);
  await expect(page.getByTestId("start-processing")).toBeDisabled();
  await expect(page.getByTestId("calib-prompt")).toContainText("rim");

  await clickLandmarks(page, 1);
  await expect(page.locator('[data-testid^="landmark-"]')).toHaveCount(5);

  // S-04: numeric error under the 5 px threshold, and the gate opens.
  await expect(page.getByTestId("calib-error")).toHaveAttribute("data-ok", "true");
  const px = Number((await page.getByTestId("calib-error").textContent())!.replace(/[^\d.]/g, ""));
  expect(px).toBeLessThan(5);
  await expect(page.getByTestId("start-processing")).toBeEnabled();
  // Bug 3: the API reports a residual per landmark, so the page can name the worst click
  // instead of only printing one number.
  await expect(page.getByTestId("calib-worst")).toContainText(/worst point: \w+.* · [\d.]+ px/);

  const calib = (await mockCalls(page)).filter((c) => c.path.endsWith("/calibration"));
  expect(calib).toHaveLength(1);
  const body = calib[0].body as {
    sport: string;
    court_variant: string;
    landmarks_px: Record<string, [number, number]>;
  };
  expect(body.sport).toBe("basketball");
  expect(body.court_variant).toBe("half");
  expect(Object.keys(body.landmarks_px)).toEqual([
    "corner_nl",
    "corner_nr",
    "corner_fl",
    "corner_fr",
    "rim",
  ]);
  // E-07: every click lands inside the frame.
  for (const [x, y] of Object.values(body.landmarks_px)) {
    expect(x).toBeGreaterThanOrEqual(0);
    expect(x).toBeLessThanOrEqual(1280);
    expect(y).toBeGreaterThanOrEqual(0);
    expect(y).toBeLessThanOrEqual(720);
  }

  // S-07/S-08: processing enqueues and every stage reaches a terminal state.
  await page.getByTestId("start-processing").click();
  await expect.poll(() => new URL(page.url()).pathname).toBe(`/upload/${id}/status`);
  await expect(page.getByTestId("stage-ingest")).toBeVisible();
  for (const stage of ["ingest", "detect", "track", "render", "label"]) {
    await expect
      .poll(() => page.getByTestId(`stage-${stage}`).getAttribute("data-state"), {
        timeout: 40_000,
      })
      .toMatch(/done|partial/);
  }
  await expect(page.getByTestId("game-status")).toHaveText("ready");
});

test("S-05 the full-court variant is carried in the calibration body", async ({ page }) => {
  await createAndUpload(page);
  await page.getByTestId("variant-full").check();
  await clickLandmarks(page, 5);

  await expect(page.getByTestId("calib-error")).toHaveAttribute("data-ok", "true");
  await expect(page.getByTestId("start-processing")).toBeEnabled();
  const calib = (await mockCalls(page)).filter((c) => c.path.endsWith("/calibration"));
  const body = calib.at(-1)!.body as { court_variant: string };
  expect(body.court_variant).toBe("full");
});

test("S-04 undo removes the last landmark and reshuts the gate", async ({ page }) => {
  await createAndUpload(page);
  await clickLandmarks(page, 5);
  await expect(page.getByTestId("start-processing")).toBeEnabled();

  await page.getByTestId("calib-undo").click();
  await expect(page.locator('[data-testid^="landmark-"]')).toHaveCount(4);
  await expect(page.getByTestId("start-processing")).toBeDisabled();
});

test("E-03 a non-video file is rejected before it is uploaded", async ({ page }) => {
  await page.goto("/upload");
  await page.getByTestId("game-title-input").fill("Bad upload");
  await page.getByTestId("create-game").click();
  await expect.poll(() => new URL(page.url()).pathname).toMatch(/^\/upload\/g_/);

  await page.getByTestId("file-input").setInputFiles({
    name: "non-video.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("nope"),
  });
  await expect(page.getByTestId("upload-error")).toBeVisible();
  const uploads = (await mockCalls(page)).filter((c) => c.method === "PUT");
  expect(uploads).toHaveLength(0);
});

// Bug 1: `variant` was `useState("half")` — basketball's. A sport whose only variant is
// `doubles` had no radio checked and still posted `half`, which the API 400s.
test("S-05b a single-variant sport hides the picker and posts its own variant", async ({
  page,
}) => {
  await createAndUpload(page, "pickleball");

  // One variant is not a choice: no radios at all, for any name.
  await expect(page.locator('input[name="variant"]')).toHaveCount(0);
  await expect(page.getByTestId("variant-half")).toHaveCount(0);
  await expect(page.getByTestId("variant-doubles")).toHaveCount(0);

  // pickleball asks for 6 landmarks, not basketball's 5
  await expect(page.getByTestId("calib-prompt")).toContainText("point 1 of 6");
  await expect(page.getByTestId("calib-prompt")).toContainText("corner nl");
  await clickLandmarks(page, 5);
  const img = page.getByTestId("calib-image");
  const box = (await img.boundingBox())!;
  await img.click({ position: { x: box.width * 0.2, y: box.height * 0.55 } });

  await expect(page.getByTestId("calib-error")).toHaveAttribute("data-ok", "true");
  const calib = (await mockCalls(page)).filter((c) => c.path.endsWith("/calibration"));
  const body = calib.at(-1)!.body as {
    sport: string;
    court_variant: string;
    landmarks_px: Record<string, [number, number]>;
  };
  expect(body.sport).toBe("pickleball");
  // D-13: the client's `court_variant` is `variant` on the wire.
  expect(body.court_variant).toBe("doubles");
  expect(Object.keys(body.landmarks_px)).toEqual([
    "corner_nl",
    "corner_nr",
    "corner_fl",
    "corner_fr",
    "net_post_l",
    "net_post_r",
  ]);
});
