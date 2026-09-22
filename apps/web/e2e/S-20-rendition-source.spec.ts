// Plan task 12 — follow-cam source selection. Pure logic, so no page: flipping the app
// into rendition mode would need a fourth Vite dev server for one boolean.
import { expect, test } from "@playwright/test";
import { followSource } from "../src/playback/followSource";

const WIDE = "http://api/media/games/g1/media/wide.mp4";
const P3 = "http://api/media/games/g1/media/p3.mp4";

test("S-20 client mode always transforms the wide shot", () => {
  expect(followSource("client", WIDE, true, P3)).toEqual({
    src: WIDE,
    useCrop: true,
    needsRender: false,
  });
});

test("S-20 rendition mode swaps the src when the game has one", () => {
  expect(followSource("rendition", WIDE, true, P3)).toEqual({
    src: P3,
    useCrop: false,
    needsRender: false,
  });
});

test("S-20 rendition mode falls back to the transform and asks for a render", () => {
  expect(followSource("rendition", WIDE, true, null)).toEqual({
    src: WIDE,
    useCrop: true,
    needsRender: true,
  });
});

test("S-20 not following is the plain wide shot in either mode", () => {
  for (const mode of ["client", "rendition"] as const) {
    expect(followSource(mode, WIDE, false, P3)).toEqual({
      src: WIDE,
      useCrop: false,
      needsRender: false,
    });
  }
});
