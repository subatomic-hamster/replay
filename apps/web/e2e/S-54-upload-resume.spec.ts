import { expect, test, type Page } from "@playwright/test";
import { fakeS3, mockCalls } from "./helpers";

// S-54 (TV redesign, docs/ux/redesign.md "Resumable phone upload"): the phone keeps the
// multipart upload id and finished parts' ETags in localStorage, so a reload (or a dropped
// connection) picks up where it left off instead of starting over. Mock API; page.route
// stands in for S3 and remembers which parts arrived (its state survives the reload).

const PHONE = { width: 360, height: 740 };
const GAME = "g_qr05";
const SIZE = 4096; // the mock splits any file into four 1024-byte parts
const KEY = `replay.upload.${GAME}`;

test.use({ viewport: PHONE });

// The same file both times (name and size identify it, as after a re-pick on a phone).
const pick = (page: Page) =>
  page
    .getByTestId("file-input")
    .setInputFiles({
      name: "game.mp4",
      mimeType: "video/mp4",
      buffer: Buffer.alloc(SIZE, 7),
    });

const stored = (page: Page) =>
  page.evaluate(
    (k) => JSON.parse(localStorage.getItem(k) ?? "null"),
    KEY,
  ) as Promise<{
    upload_id: string;
    etags: Record<string, string>;
  } | null>;

test("S-54 a reload resumes the upload: only the missing part is sent", async ({
  page,
}) => {
  test.setTimeout(60_000);
  let stall = true;
  const { attempts } = await fakeS3(page, { hang: (n) => stall && n === 3 });
  await page.goto(`/u/${GAME}#t=tok_test`);
  await pick(page);
  // parts 1, 2 and 4 land; part 3 hangs (the connection dropped mid-part)
  await expect
    .poll(async () => Object.keys((await stored(page))?.etags ?? {}).sort())
    .toEqual(["1", "2", "4"]);
  expect((await stored(page))?.upload_id).toBe(`mpu_${GAME}`);

  stall = false;
  await page.reload();
  const prompt = page.getByTestId("upload-resume-prompt");
  await expect(prompt).toContainText("Resuming your upload");
  await expect(prompt).toContainText("game.mp4 stopped at 75%");
  await expect(page.getByTestId("file-input")).toBeEnabled();

  await pick(page);
  await expect
    .poll(() => new URL(page.url()).pathname)
    .toBe(`/u/${GAME}/calibrate`);
  const calls = await mockCalls(page); // the mock's log restarted with the reload
  expect(calls.filter((c) => c.path.endsWith("/upload/multipart"))).toEqual([]); // no new upload
  expect(calls.filter((c) => c.path.endsWith("/upload/parts"))).toEqual([
    {
      method: "GET",
      path: `/games/${GAME}/upload/parts`,
      body: { upload_id: `mpu_${GAME}`, size: SIZE },
    },
  ]);
  const done = calls.filter((c) => c.path.endsWith("/upload/complete"));
  expect(done.map((c) => c.body)).toEqual([
    {
      upload_id: `mpu_${GAME}`,
      parts: [1, 2, 3, 4].map((n) => ({ n, etag: `"etag-${n}"` })),
    },
  ]);
  expect(attempts).toEqual({ 1: 1, 2: 1, 3: 2, 4: 1 }); // only part 3 went up again
  expect(await stored(page)).toBeNull(); // finished: nothing left to resume
});

test("S-54 the resume state shows while it runs; Start over and Cancel forget the upload", async ({
  page,
}) => {
  test.setTimeout(60_000);
  await fakeS3(page, { hang: (n) => n === 3 });
  await page.goto(`/u/${GAME}#t=tok_test`);
  await pick(page);
  await expect
    .poll(async () => Object.keys((await stored(page))?.etags ?? {}).length)
    .toBe(3);
  await page.reload();

  // re-pick: resumes (part 3 still hangs), showing the resume state, at 75%
  await pick(page);
  await expect(page.getByTestId("upload-resuming")).toHaveText(
    "Resuming your upload",
  );
  await expect(page.getByTestId("upload-pct")).toContainText("75%");
  await page.getByTestId("upload-cancel").click();
  await expect(page.getByTestId("upload-error")).toContainText(
    "Upload cancelled",
  );
  expect(
    (await mockCalls(page)).filter((c) => c.path.endsWith("/upload/abort")),
  ).toEqual([
    {
      method: "POST",
      path: `/games/${GAME}/upload/abort`,
      body: { upload_id: `mpu_${GAME}` },
    },
  ]);
  expect(await stored(page)).toBeNull();

  // a fresh start stalls again; after a reload, Start over aborts it and clears the prompt
  await page.getByTestId("upload-retry").click();
  await expect
    .poll(async () => Object.keys((await stored(page))?.etags ?? {}).length)
    .toBe(3);
  await page.reload();
  await expect(page.getByTestId("upload-resume-prompt")).toBeVisible();
  await page.getByTestId("upload-start-over").click();
  await expect(page.getByTestId("upload-resume-prompt")).toHaveCount(0);
  expect(
    (await mockCalls(page)).filter((c) => c.path.endsWith("/upload/abort")),
  ).toHaveLength(1);
  expect(await stored(page)).toBeNull();
});
