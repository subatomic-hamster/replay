// Web build entry (react-native-web via Vite) — for Playwright and screenshots. The first
// route comes from the URL so tests can deep-link (`/tv/<id>?mode=follow&pid=p1&t=5`).
import { AppRegistry } from "react-native";
import { App } from "./App";
import { routeFromPath } from "./nav";

const initial = routeFromPath(window.location.pathname + window.location.search);
AppRegistry.registerComponent("ReplayTV", () => () => <App initial={initial} />);
// @ts-expect-error react-native-web's rootTag is a DOM node; the RN types say number.
AppRegistry.runApplication("ReplayTV", { rootTag: document.getElementById("root") });
