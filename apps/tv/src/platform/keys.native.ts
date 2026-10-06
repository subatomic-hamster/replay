// Fire TV / Android TV remote. react-native-tvos emits remote keys through
// useTVEventHandler (Android sends key-UP events by default, eventKeyAction 1; key-down
// only with ReactFeatureFlags.enableKeyDownEvents, so act on up and ignore down) and the
// Back key through BackHandler. Unhandled Back (the library) falls through so the app
// exits, as Fire TV expects.
import { useEffect } from "react";
import { BackHandler, useTVEventHandler } from "react-native";
import { dispatch, type DpadAction } from "../input";

const MAP: Record<string, DpadAction> = {
  up: "up",
  down: "down",
  left: "left",
  right: "right",
  select: "select",
  playPause: "playpause",
  play: "playpause",
  pause: "playpause",
  rewind: "seek-back",
  fastForward: "seek-fwd",
  previous: "prev-event",
  next: "next-event",
  menu: "menu",
  bookmark: "bookmark",
};

const KEY_DOWN = 0;

export function usePlatformKeys() {
  useTVEventHandler((evt) => {
    // Typed string in CoreEventTypes, number in TVEventHandler; Android sends an int.
    if (!evt || Number(evt.eventKeyAction) === KEY_DOWN) return;
    const action = MAP[evt.eventType];
    if (action) dispatch(action);
  });

  useEffect(() => {
    const sub = BackHandler.addEventListener("hardwareBackPress", () => dispatch("back"));
    return () => sub.remove();
  }, []);
}
