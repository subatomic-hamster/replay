// Fire TV / Android TV remote. react-native-tvos emits remote keys through
// useTVEventHandler and the Back key through BackHandler. Unhandled Back (the library)
// falls through so the app exits, as Fire TV expects.
//
// What react-native-tvos 0.87 sends on Android (ReactAndroidHWInputDeviceHelper, with
// ReactFeatureFlags.enableKeyDownEvents off): a short press is one key-UP
// (eventKeyAction 1) named "left", "select", ...; a press held past the first key
// auto-repeat (~500 ms) becomes ONE "longLeft"/"longSelect"/... key-DOWN (action 0) and,
// on release, one "longLeft" key-UP, and nothing named "left" at all. Android's repeated
// key-DOWNs never reach JS. So arrows repeat on a JS timer between the long DOWN and its
// UP; every other key acts once on UP, long or short.
import { useEffect } from "react";
import { AppState, BackHandler, useTVEventHandler } from "react-native";
import { dispatch, type DpadAction } from "../input";

const MAP: Record<string, DpadAction> = {
  up: "up",
  down: "down",
  left: "left",
  right: "right",
  select: "select",
  longSelect: "select",
  playPause: "playpause",
  longPlayPause: "playpause",
  play: "playpause",
  pause: "playpause",
  rewind: "seek-back",
  longRewind: "seek-back",
  fastForward: "seek-fwd",
  longFastForward: "seek-fwd",
  previous: "prev-event",
  next: "next-event",
  menu: "menu",
  bookmark: "bookmark",
};

const REPEAT: Record<string, DpadAction> = {
  longUp: "up",
  longDown: "down",
  longLeft: "left",
  longRight: "right",
};

// ponytail: fixed rate, no acceleration; tune on a device if lists feel slow or jumpy.
const REPEAT_MS = 120;
const KEY_DOWN = 0;

// One remote, one held key: module state, like input.ts's handler stack.
let repeat: ReturnType<typeof setInterval> | null = null;
const stop = () => {
  if (repeat !== null) clearInterval(repeat);
  repeat = null;
};

export function usePlatformKeys() {
  useTVEventHandler((evt) => {
    if (!evt) return;
    // Any key event ends a repeat; a long arrow's UP is exactly that plus the release.
    stop();
    // Typed string in CoreEventTypes, number in TVEventHandler; Android sends an int.
    const down = Number(evt.eventKeyAction) === KEY_DOWN;
    const held = REPEAT[evt.eventType];
    if (held) {
      if (!down) {
        if (held === "left" || held === "right") dispatch("release");
        return;
      }
      dispatch(held);
      repeat = setInterval(() => dispatch(held), REPEAT_MS);
      return;
    }
    const action = MAP[evt.eventType];
    if (action && !down) {
      dispatch(action);
      // A short press is one UP: press and release at once (the player's seek resumes).
      if (action === "left" || action === "right") dispatch("release");
    }
  });

  useEffect(() => {
    const back = BackHandler.addEventListener("hardwareBackPress", () =>
      dispatch("back"),
    );
    // A key released while the app is backgrounded (Home mid-hold) never sends its UP.
    const app = AppState.addEventListener(
      "change",
      (s) => s !== "active" && stop(),
    );
    return () => {
      back.remove();
      app.remove();
      stop();
    };
  }, []);
}
