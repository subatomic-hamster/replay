// §4.8 platform adapter rule: this module is the ONLY place that reads KeyboardEvent.
// Screens and components speak in DpadAction. Swapping in a real remote (Fire OS /
// Vega, Phase 3) means replacing this file, nothing else.
import { useEffect } from "react";

export type DpadAction =
  | "up"
  | "down"
  | "left"
  | "right"
  | "select"
  | "back"
  | "playpause"
  | "seek-back"
  | "seek-fwd"
  | "prev-event"
  | "next-event"
  | "bookmark"
  | "spotlight"
  | "tag"
  /** Backspace, only when a handler opted into splitting it from "back" (S-25). */
  | "delete";

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
  // Beyond D-1's remote map: on a real remote these hang off the on-screen menu.
  // ponytail: extra letter keys instead of a menu layer; give them buttons when the
  // Fire TV remote port lands.
  s: "spotlight",
  t: "tag",
};

export function keyToAction(e: KeyboardEvent, splitDelete = false): DpadAction | null {
  if (e.metaKey || e.ctrlKey || e.altKey) return null;
  if (splitDelete && e.key === "Backspace") return "delete";
  return MAP[e.key] ?? null;
}

export type DpadHandler = (action: DpadAction) => void;

// A stack, so a dialog (TagDialog) takes the whole input surface while it is open —
// which is how S-25's Backspace-deletes-a-character precedence is implemented.
const stack: { handler: DpadHandler; splitDelete: boolean }[] = [];

function onKeyDown(e: KeyboardEvent) {
  const top = stack[stack.length - 1];
  if (!top) return;
  const action = keyToAction(e, top.splitDelete);
  if (!action) return;
  e.preventDefault();
  top.handler(action);
}

/**
 * Subscribe to D-pad input. The most recently mounted enabled handler wins.
 * `splitDelete` makes Backspace emit "delete" instead of "back" for that handler only.
 */
export function useDpad(handler: DpadHandler, enabled = true, splitDelete = false) {
  useEffect(() => {
    if (!enabled) return;
    if (stack.length === 0) window.addEventListener("keydown", onKeyDown);
    const entry = { handler, splitDelete };
    stack.push(entry);
    return () => {
      const i = stack.lastIndexOf(entry);
      if (i >= 0) stack.splice(i, 1);
      if (stack.length === 0) window.removeEventListener("keydown", onKeyDown);
    };
  }, [handler, enabled, splitDelete]);
}
