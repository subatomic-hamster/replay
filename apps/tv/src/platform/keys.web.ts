// Web build: the keyboard is the remote (D-1 map, same keys as apps/web /tv, plus `m`
// for the remote's Menu key). The only file in apps/tv that reads KeyboardEvent.
import { useEffect } from "react";
import { dispatch, wantsDelete, type DpadAction } from "../input";

const MAP: Record<string, DpadAction> = {
  ArrowUp: "up",
  ArrowDown: "down",
  ArrowLeft: "left",
  ArrowRight: "right",
  Enter: "select",
  Escape: "back",
  Backspace: "back",
  " ": "playpause",
  ",": "seek-back",
  ".": "seek-fwd",
  "[": "prev-event",
  "]": "next-event",
  b: "bookmark",
  s: "spotlight",
  t: "tag",
  p: "pair",
  m: "menu",
};

export function usePlatformKeys() {
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const action =
        e.key === "Backspace" && wantsDelete() ? "delete" : MAP[e.key];
      if (action && dispatch(action)) e.preventDefault();
    };
    // Held arrows arrive as repeated keydowns; the keyup ends a seek.
    const onKeyUp = (e: KeyboardEvent) => {
      if (e.key === "ArrowLeft" || e.key === "ArrowRight") dispatch("release");
    };
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", onKeyUp);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keyup", onKeyUp);
    };
  }, []);
}
