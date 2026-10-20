// Web build entry (react-native-web via Vite) — for Playwright and screenshots. The first
// route comes from the URL so tests can deep-link (`/tv/<id>?mode=follow&pid=p1&t=5`).
// A deployed build lives under a subpath (VITE_BASE=/tvapp/) and reads its API base from
// `<base>config.json` (D-80); a missing file is fine. The dev server has none, so it skips it.
import { AppRegistry } from "react-native";
import { App } from "./App";
import { setDefaultApiBase } from "./api";
import { routeFromPath } from "./nav";
import { face } from "./theme";
import barlowMedium from "../android/app/src/main/assets/fonts/Barlow-Medium.ttf?url";
import barlowSemiBold from "../android/app/src/main/assets/fonts/Barlow-SemiBold.ttf?url";
import figures from "../android/app/src/main/assets/fonts/BarlowSemiCondensed-SemiBold.ttf?url";

// react-native-web's vendored Animated stops a running timing with
// `global.cancelAnimationFrame` (a focus move mid-animation); browsers have no `global`.
(globalThis as { global?: unknown }).global = globalThis;

// Barlow (OFL): the Android asset files, one @font-face per family name, the same names the
// native build resolves from assets/fonts (theme.ts `face`).
const faces: [string, string][] = [
  [face.medium, barlowMedium],
  [face.semibold, barlowSemiBold],
  [face.figures, figures],
];
const fontCss = document.createElement("style");
fontCss.textContent = faces
  .map(
    ([family, url]) =>
      `@font-face{font-family:"${family}";src:url(${url}) format("truetype");font-display:block}`,
  )
  .join("\n");
document.head.appendChild(fontCss);

const BASE = import.meta.env.BASE_URL;
const path = window.location.pathname.startsWith(BASE)
  ? window.location.pathname.slice(BASE.length - 1)
  : window.location.pathname;
const initial = routeFromPath(path + window.location.search);
AppRegistry.registerComponent("ReplayTV", () => () => (
  <App initial={initial} />
));

(import.meta.env.PROD
  ? fetch(`${BASE}config.json`, { cache: "no-store" })
  : Promise.reject()
)
  .then((r) => (r.ok ? r.json() : null))
  .then(
    (cfg: { apiBase?: string } | null) =>
      cfg?.apiBase && setDefaultApiBase(cfg.apiBase),
  )
  .catch(() => {})
  .finally(() =>
    AppRegistry.runApplication("ReplayTV", {
      // @ts-expect-error react-native-web's rootTag is a DOM node; the RN types say number.
      rootTag: document.getElementById("root"),
    }),
  );
