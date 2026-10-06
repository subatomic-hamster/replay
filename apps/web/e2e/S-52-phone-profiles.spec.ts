// M10 phone companion (mock API): create and edit a profile, upload its photo, and the
// opt-in face enrollment — nothing is possible before the consent box is ticked, 1–10
// photos, "Delete my face data" removes it, and the TV stops showing face suggestions for
// a profile once its face data is gone. Images here are a synthetic 1x1 PNG.
import { expect, test, type Page } from "@playwright/test";
import { mockCalls } from "./helpers";

const JORDAN = "pr_00000000a002";
// synthetic 1x1 PNG, not a face
const PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFBQIAX8jx0gAAAABJRU5ErkJggg==",
  "base64",
);
const photo = (i: number) => ({ name: `synthetic-${i}.png`, mimeType: "image/png", buffer: PNG });
const photos = (n: number) => Array.from({ length: n }, (_, i) => photo(i));

const writes = async (page: Page) =>
  (await mockCalls(page)).filter((c) => c.method !== "GET" && c.path.startsWith("/profiles"));

const PHONE = { width: 430, height: 932 };
/** Opt-in screenshots of the phone pages (mock data, synthetic) for docs/evidence/M10-ui. */
async function evidence(page: Page, name: string) {
  const dir = process.env.REPLAY_WEB_EVIDENCE_DIR;
  if (dir) await page.screenshot({ path: `${dir}/${name}.png`, fullPage: true });
}

/** Client-side navigation, so the in-page mock keeps its state (page.goto would reset it). */
async function goInApp(page: Page, path: string) {
  await page.evaluate((p) => {
    window.history.pushState({}, "", p);
    window.dispatchEvent(new PopStateEvent("popstate"));
  }, path);
}

test("S-52 create a profile, edit name / sports / positions, upload a photo", async ({ page }) => {
  await page.setViewportSize(PHONE);
  await page.goto("/profiles");
  await evidence(page, "phone-01-profiles");
  await expect(page.getByTestId("phone-profile")).toHaveCount(3);
  await expect(page.getByTestId("profile-create")).toBeDisabled();
  await page.getByTestId("profile-name-input").fill("Riley");
  await page.getByTestId("profile-create").click();
  await expect(page).toHaveURL(/\/profiles\/pr_[0-9a-f]{12}$/);
  const id = (await page.getByTestId("profile-edit").getAttribute("data-profile-id")) ?? "";
  await expect(page.getByTestId("profile-edit-name")).toHaveText("Riley");
  await expect(page.getByTestId("avatar").first()).toHaveAttribute("data-photo", "false");

  await page.getByTestId("profile-name-input").fill("Riley Q");
  await page.getByTestId("profile-sport-basketball").check();
  await page.getByTestId("profile-positions-input").fill("wing, guard");
  await page.getByTestId("profile-save").click();
  await expect(page.getByTestId("profile-note")).toHaveText("Saved");
  await expect(page.getByTestId("profile-edit-name")).toHaveText("Riley Q");

  await page.getByTestId("profile-photo-input").setInputFiles(photo(0));
  await expect(page.getByTestId("profile-note")).toHaveText("Photo saved");
  await expect(page.getByTestId("avatar").first()).toHaveAttribute("data-photo", "true");
  await evidence(page, "phone-02-profile-edit");

  expect(await writes(page)).toEqual([
    { method: "POST", path: "/profiles", body: { name: "Riley" } },
    { method: "PATCH", path: `/profiles/${id}`, body: { name: "Riley Q", sports: ["basketball"], positions: ["wing", "guard"] } },
    { method: "PUT", path: `/profiles/${id}/photo`, body: { size: PNG.length, type: "image/png" } },
  ]);

  // the list shows it
  await goInApp(page, "/profiles");
  await expect(page.getByTestId("phone-profile")).toHaveCount(4);
  await expect(page.locator(`[data-testid="phone-profile"][data-profile-id="${id}"]`)).toContainText("Riley Q");
});

test("S-52 face enrollment: consent gates everything, 1–10 photos, then delete my face data", async ({ page }) => {
  await page.setViewportSize(PHONE);
  await page.goto("/profiles");
  await page.getByTestId("profile-name-input").fill("Casey");
  await page.getByTestId("profile-create").click();
  await expect(page.getByTestId("profile-edit")).toBeVisible();
  const id = (await page.getByTestId("profile-edit").getAttribute("data-profile-id")) ?? "";

  const section = page.getByTestId("face-section");
  await expect(section).toHaveAttribute("data-enrolled", "false");
  const consentText = page.getByTestId("face-consent-text");
  await expect(consentText).toContainText("one face embedding");
  await expect(consentText).toContainText("then deleted");
  await expect(consentText).toContainText("people who did not enroll are never matched");
  await expect(consentText).toContainText("Delete my face data");

  // no consent: the picker and the button are both off
  await expect(page.getByTestId("face-consent")).not.toBeChecked();
  await expect(page.getByTestId("face-photos")).toBeDisabled();
  await expect(page.getByTestId("face-enroll")).toBeDisabled();
  await page.getByTestId("face-section").scrollIntoViewIfNeeded();
  await evidence(page, "phone-03-face-consent-step");

  await page.getByTestId("face-consent").check();
  await expect(page.getByTestId("face-photos")).toBeEnabled();
  await expect(page.getByTestId("face-enroll")).toBeDisabled(); // no photos yet
  await page.getByTestId("face-photos").setInputFiles(photos(11));
  await expect(page.getByTestId("face-photo-count")).toHaveText("Pick at most 10 photos.");
  await expect(page.getByTestId("face-enroll")).toBeDisabled();
  await page.getByTestId("face-photos").setInputFiles(photos(2));
  await expect(page.getByTestId("face-photo-count")).toHaveText("2 photos picked");
  await expect(page.getByTestId("face-enroll")).toBeEnabled();

  // withdrawing consent drops the picked photos and disables enrollment again
  await page.getByTestId("face-consent").uncheck();
  await expect(page.getByTestId("face-photo-count")).toHaveCount(0);
  await expect(page.getByTestId("face-photos")).toBeDisabled();
  await expect(page.getByTestId("face-enroll")).toBeDisabled();
  expect((await writes(page)).filter((c) => c.path.endsWith("/face"))).toEqual([]);

  await page.getByTestId("face-consent").check();
  await expect(page.getByTestId("face-enroll")).toBeDisabled(); // the picker was emptied too
  await page.getByTestId("face-photos").setInputFiles(photos(3));
  await page.getByTestId("face-enroll").click();
  await expect(section).toHaveAttribute("data-enrolled", "true");
  await expect(page.getByTestId("face-note")).toContainText("Your photos were deleted; one face embedding is stored.");
  await expect(page.getByTestId("face-status")).toBeVisible();
  await evidence(page, "phone-04-face-enrolled");

  await page.getByTestId("face-delete").click();
  await expect(section).toHaveAttribute("data-enrolled", "false");
  await expect(page.getByTestId("face-note")).toHaveText("Your face data was deleted.");
  await expect(page.getByTestId("face-consent")).not.toBeChecked();

  expect((await writes(page)).filter((c) => c.path.endsWith("/face"))).toEqual([
    { method: "POST", path: `/profiles/${id}/face`, body: { consent: true, photos: 3 } },
    { method: "DELETE", path: `/profiles/${id}/face` },
  ]);
});

test("S-52 after Delete my face data the TV shows no face suggestion for that profile", async ({ page }) => {
  await page.goto(`/tv/players/${JORDAN}`);
  await page.keyboard.press("ArrowLeft");
  for (let i = 0; i < 3; i++) await page.keyboard.press("ArrowRight");
  await expect(page.getByTestId("profile")).toHaveAttribute("data-tab", "links");
  await expect(page.locator('[data-testid="suggestion-row"][data-face="true"]')).toHaveCount(1);

  await goInApp(page, `/profiles/${JORDAN}`);
  await expect(page.getByTestId("face-section")).toHaveAttribute("data-enrolled", "true");
  await page.getByTestId("face-delete").click();
  await expect(page.getByTestId("face-section")).toHaveAttribute("data-enrolled", "false");

  await goInApp(page, `/tv/players/${JORDAN}`);
  await expect(page.getByTestId("profile")).toHaveAttribute("data-profile-id", JORDAN);
  await expect(page.getByTestId("face-enrolled")).toHaveCount(0);
  for (let i = 0; i < 3; i++) await page.keyboard.press("ArrowRight");
  await expect(page.getByTestId("profile")).toHaveAttribute("data-tab", "links");
  await expect(page.getByTestId("links-empty")).toBeVisible();
  await expect(page.getByTestId("suggestion-row")).toHaveCount(0);
});
