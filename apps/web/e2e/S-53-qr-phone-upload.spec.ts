import { expect, test, type Page } from "@playwright/test";
import { fakeS3, mockCalls } from "./helpers";

// S-53 (D-80): the phone page the TV's QR code opens, `/u/:id#t=<token>`, at phone width
// against the mock API. The video goes up in presigned parts (answered here by page.route,
// standing in for S3), a failed part is retried, then calibration and processing run on
// the same token client.

const PHONE = { width: 360, height: 740 };
const GAME = "g_qr05"; // the mock's freshly created game
const SIZE = 4096; // the mock splits any file into four parts

test.use({ viewport: PHONE });

const pick = (page: Page) =>
  page.getByTestId("file-input").setInputFiles({
    name: "game.mp4",
    mimeType: "video/mp4",
    buffer: Buffer.alloc(SIZE, 7),
  });

const noSideScroll = (page: Page) =>
  page.evaluate(
    () => document.documentElement.scrollWidth <= window.innerWidth,
  );

test("S-53 phone page: multipart upload with a retried part, calibrate, process", async ({
  page,
}) => {
  test.setTimeout(90_000);
  const { attempts } = await fakeS3(page, {
    fail: (n, attempt) => n === 2 && attempt === 1,
  });
  await page.goto(`/u/${GAME}#t=tok_test`);
  await expect(page.getByTestId("qr-upload")).toBeVisible();
  await expect(page.getByTestId("file-input")).toHaveAttribute(
    "accept",
    "video/*",
  );
  expect(await noSideScroll(page)).toBe(true);

  await pick(page);
  await expect
    .poll(() => new URL(page.url()).pathname)
    .toBe(`/u/${GAME}/calibrate`);
  expect(new URL(page.url()).hash).toBe("#t=tok_test"); // the token rides along

  const calls = await mockCalls(page);
  const init = calls.filter(
    (c) => c.path === `/games/${GAME}/upload/multipart`,
  );
  expect(init).toEqual([
    {
      method: "POST",
      path: `/games/${GAME}/upload/multipart`,
      body: { size: SIZE, content_type: "video/mp4" },
    },
  ]);
  const done = calls.filter((c) => c.path === `/games/${GAME}/upload/complete`);
  expect(done).toHaveLength(1);
  expect(done[0].body).toEqual({
    upload_id: `mpu_${GAME}`,
    parts: [1, 2, 3, 4].map((n) => ({ n, etag: `"etag-${n}"` })),
  });
  expect(calls.some((c) => c.path.endsWith("/upload/abort"))).toBe(false);
  expect(attempts).toEqual({ 1: 1, 2: 2, 3: 1, 4: 1 }); // part 2 failed once and was retried

  // Calibration on the token client: accept the proposal, then process.
  await expect(page.getByTestId("autocalib-accept")).toBeVisible({
    timeout: 15_000,
  });
  await page.getByTestId("autocalib-accept").click();
  await expect(page.getByTestId("calib-error")).toHaveAttribute(
    "data-ok",
    "true",
  );
  expect(await noSideScroll(page)).toBe(true);
  await page.getByTestId("start-processing").click();
  await expect
    .poll(() => new URL(page.url()).pathname)
    .toBe(`/u/${GAME}/status`);
  await expect(page.getByTestId("game-status")).toHaveText("ready", {
    timeout: 40_000,
  });
  await expect(page.getByTestId("ready-note")).toContainText(
    "Watch it on the TV",
  );
  expect(await noSideScroll(page)).toBe(true);
});

test("S-53 a part that keeps failing pauses the upload; Resume sends only what is missing", async ({
  page,
}) => {
  test.setTimeout(60_000);
  let broken = true;
  const { attempts } = await fakeS3(page, { fail: (n) => broken && n === 3 });
  await page.goto(`/u/${GAME}#t=tok_test`);
  await pick(page);
  await expect(page.getByTestId("upload-progress")).toBeVisible();
  // Five tries with backoff (0.5 + 1 + 2 + 4 s), then the upload pauses: kept, not aborted.
  await expect(page.getByTestId("upload-error")).toContainText(
    "Upload paused",
    { timeout: 20_000 },
  );
  expect(
    (await mockCalls(page)).some((c) => c.path.endsWith("/upload/abort")),
  ).toBe(false);
  expect(
    (await mockCalls(page)).some((c) => c.path.endsWith("/upload/complete")),
  ).toBe(false);
  await expect(page.getByTestId("upload-retry")).toHaveText("Resume upload");

  broken = false;
  await page.getByTestId("upload-retry").click();
  await expect
    .poll(() => new URL(page.url()).pathname)
    .toBe(`/u/${GAME}/calibrate`);
  expect(attempts).toEqual({ 1: 1, 2: 1, 3: 6, 4: 1 }); // parts 1, 2, 4 were not sent again
  const inits = (await mockCalls(page)).filter((c) =>
    c.path.endsWith("/upload/multipart"),
  );
  expect(inits).toHaveLength(1);
});

test("S-53 an expired or missing upload code says what to do", async ({
  page,
}) => {
  await page.goto(`/u/${GAME}#t=expired`);
  await expect(page.getByTestId("qr-problem")).toContainText("expired");
  await expect(page.getByTestId("qr-problem")).toContainText("Add game");
  await page.goto(`/u/${GAME}`);
  await page.reload(); // a hash-only change does not reload
  await expect(page.getByTestId("qr-problem")).toContainText(
    "missing its upload code",
  );
});
