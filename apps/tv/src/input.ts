// Remote input, platform-neutral. platform/keys.{web,native}.ts turn raw key events into
// DpadActions and call `dispatch`; screens and components only ever see DpadActions.
// A stack, so a dialog takes the whole input surface while it is open.
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
  | "pair"
  /** Opens the Watch action row (remote Menu key; everything there is also D-pad reachable). */
  | "menu"
  /** Backspace on a keyboard, only for a handler that opted into splitting it from "back". */
  | "delete";

/** Return `false` to leave an action unhandled (Back on the library lets the app exit). */
export type DpadHandler = (action: DpadAction) => boolean | void;

const stack: { handler: DpadHandler; splitDelete: boolean }[] = [];

/** Whether the top handler wants Backspace as "delete" rather than "back". */
export function wantsDelete(): boolean {
  return stack[stack.length - 1]?.splitDelete ?? false;
}

/** Deliver an action to the most recently mounted handler. True when it was handled. */
export function dispatch(action: DpadAction): boolean {
  const top = stack[stack.length - 1];
  if (!top) return false;
  return top.handler(action) !== false;
}

export function useDpad(handler: DpadHandler, enabled = true, splitDelete = false) {
  useEffect(() => {
    if (!enabled) return;
    const entry = { handler, splitDelete };
    stack.push(entry);
    return () => {
      const i = stack.lastIndexOf(entry);
      if (i >= 0) stack.splice(i, 1);
    };
  }, [handler, enabled, splitDelete]);
}
