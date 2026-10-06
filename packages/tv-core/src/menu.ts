// The Watch action menu, shared by apps/web /tv and apps/tv. Sixteen-plus flat items
// wrapped into two rows over the video at 1080p, so the menu is one row of top-level
// entries, three of which open their own row ("Game ▸", "Playback ▸", "Players ▸").
// Left/Right move, Select runs or opens, Back/Down closes a group and then the menu.
// Items only show when the game has their data (D-60); nothing branches on the sport.

export type MenuAction =
  | "library"
  | "players"
  | "highlights"
  | "review"
  | "replays"
  | "clips"
  | "rallies"
  | "search"
  | "advice"
  | "pair"
  | "prev-event"
  | "next-event"
  | "bookmark"
  | "spotlight"
  | "tag"
  | "link-profile"
  | "broadcast"
  | "captions"
  | "hype-peak";

export interface MenuEntry {
  id: string;
  label: string;
  action?: MenuAction;
  /** a group: Select opens this row in place of the top one */
  items?: MenuEntry[];
}

export const WATCH_MENU: MenuEntry[] = [
  { id: "nav-library", label: "Library", action: "library" },
  { id: "action-broadcast", label: "Broadcast", action: "broadcast" },
  { id: "action-captions", label: "Commentary", action: "captions" },
  {
    id: "menu-game",
    label: "Game ▸",
    items: [
      { id: "nav-highlights", label: "Highlights", action: "highlights" },
      { id: "nav-review", label: "Review", action: "review" },
      { id: "nav-clips", label: "Clips", action: "clips" },
      { id: "nav-replays", label: "Replays", action: "replays" },
      { id: "nav-rallies", label: "Rallies", action: "rallies" },
      { id: "nav-search", label: "Search", action: "search" },
    ],
  },
  {
    id: "menu-playback",
    label: "Playback ▸",
    items: [
      { id: "action-prev-event", label: "◀ Event", action: "prev-event" },
      { id: "action-next-event", label: "Event ▶", action: "next-event" },
      { id: "action-bookmark", label: "Bookmark", action: "bookmark" },
      { id: "action-spotlight", label: "Spotlight", action: "spotlight" },
      { id: "action-hype-peak", label: "Hype peak", action: "hype-peak" },
    ],
  },
  {
    id: "menu-players",
    label: "Players ▸",
    items: [
      { id: "nav-players", label: "Profiles", action: "players" },
      { id: "action-tag", label: "Tag player", action: "tag" },
      { id: "action-link-profile", label: "Link profile", action: "link-profile" },
      { id: "nav-advice", label: "Advice", action: "advice" },
    ],
  },
  { id: "nav-pair", label: "Pair phone", action: "pair" },
];

/** The menu without the actions this game has no data for; an emptied group goes too. */
export function watchMenu(hidden: ReadonlySet<MenuAction>): MenuEntry[] {
  return WATCH_MENU.flatMap((e): MenuEntry[] => {
    if (!e.items) return e.action && hidden.has(e.action) ? [] : [e];
    const items = e.items.filter((i) => !i.action || !hidden.has(i.action));
    return items.length ? [{ ...e, items }] : [];
  });
}

/** Menu focus: which row (null = the top one) and the index in it. */
export interface MenuFocus {
  group: string | null;
  i: number;
}

/** The entries of the row `f` is on. */
export const menuRow = (menu: MenuEntry[], f: MenuFocus): MenuEntry[] =>
  f.group === null ? menu : (menu.find((e) => e.id === f.group)?.items ?? []);

/** One D-pad step on an open menu. `run` is the entry Select picked (an action, not a
 *  group); `focus` null closes the menu. */
export function menuStep(
  menu: MenuEntry[],
  f: MenuFocus,
  key: "left" | "right" | "select" | "back" | "down" | "up",
): { focus: MenuFocus | null; run?: MenuEntry } {
  const row = menuRow(menu, f);
  const close = (): MenuFocus | null =>
    f.group === null ? null : { group: null, i: Math.max(0, menu.findIndex((e) => e.id === f.group)) };
  switch (key) {
    case "left":
      return { focus: { ...f, i: Math.max(0, f.i - 1) } };
    case "right":
      return { focus: { ...f, i: Math.min(row.length - 1, f.i + 1) } };
    case "up":
      return { focus: f };
    case "back":
    case "down":
      return { focus: close() };
    case "select": {
      const e = row[f.i];
      if (!e) return { focus: f };
      if (e.items) return { focus: { group: e.id, i: 0 } };
      return { focus: f, run: e };
    }
  }
}
