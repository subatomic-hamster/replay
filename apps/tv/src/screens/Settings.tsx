// Settings: the Replay API address and API key, set with the D-pad and kept on the device.
// Reached from Home's gear and from the "Could not reach the Replay API" banner; the app
// opens here on first run when the build has no default (REPLAY_API_BASE). A short list
// (docs/ux/redesign.md "Settings"): Up/Down (or Left/Right) move, Select edits or runs.
// The key (X-Replay-Key, D-80 cloud mode) is only ever shown masked to its last 4 characters.
// ponytail: address and key are typed on the on-screen keyboard; the spec's phone (QR)
// handoff for them needs a phone page route first.
import { useCallback, useEffect, useRef, useState } from "react";
import { ActivityIndicator, Platform, StyleSheet, View } from "react-native";
import {
  apiBase,
  apiKey,
  maskKey,
  normalizeApiBase,
  probeApi,
  setApiBase,
  setApiKey,
} from "../api";
import { TextEntryDialog } from "../components/TextEntryDialog";
import { useDpad, type DpadAction } from "../input";
import { navigate } from "../nav";
import { color, px, radius, safe, sp, type } from "../theme";
import { ContextChip, KeyLegend, T, styles as ui } from "../ui";

const ITEMS = ["Server address", "API key", "Test connection", "Done"] as const;
const [ADDRESS, KEY, TEST, DONE] = [0, 1, 2, 3];
const URL_KEYS = [
  ["http://", "192.168.", "10.0.", ":8000", ".local"],
  [..."1234567890"],
  [..."ABCDEFGHIJ"],
  [..."KLMNOPQRST"],
  [..."UVWXYZ.:/-"],
];
// The deploy's keys are `openssl rand -hex 32`; the letters type lowercase.
const KEY_KEYS = [
  [..."1234567890"],
  [..."ABCDEFGHIJ"],
  [..."KLMNOPQRST"],
  [..."UVWXYZ._-"],
];

type Check = { state: "idle" | "checking" | "ok" | "error"; text: string };

export function Settings() {
  const [base, setBase] = useState(apiBase);
  const [key, setKey] = useState(apiKey);
  const [focus, setFocus] = useState(ADDRESS); // the first row, as every list opens
  const [editing, setEditing] = useState<"base" | "key" | null>(
    base ? null : "base",
  );
  const [check, setCheck] = useState<Check>({ state: "idle", text: "" });

  // Only the latest check may report (an older, slower one must not overwrite it).
  const seq = useRef(0);
  const test = useCallback((url: string) => {
    const n = ++seq.current;
    const report = (c: Check) => n === seq.current && setCheck(c);
    setCheck({ state: "checking", text: "Checking" });
    probeApi(url)
      .listGames()
      .then(
        (games) =>
          report({
            state: "ok",
            text: `Connected · ${games.length} game${games.length === 1 ? "" : "s"}`,
          }),
        (e: Error) =>
          report({ state: "error", text: `Not reachable: ${e.message}` }),
      );
  }, []);

  // Show whether the saved address works as soon as the screen opens.
  useEffect(() => {
    if (base) test(base);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onAction = useCallback(
    (a: DpadAction) => {
      if (a === "up" || a === "left") setFocus((i) => Math.max(0, i - 1));
      else if (a === "down" || a === "right")
        setFocus((i) => Math.min(ITEMS.length - 1, i + 1));
      else if (a === "select" && focus === ADDRESS) setEditing("base");
      else if (a === "select" && focus === KEY) setEditing("key");
      else if (a === "select" && focus === TEST && base) test(base);
      else if ((a === "select" && focus === DONE) || a === "back") {
        // Nothing set yet: Back leaves the app (Fire TV convention), there is no library.
        if (!base) return false;
        navigate({ name: "library" });
      }
    },
    [focus, base, test],
  );
  useDpad(onAction, !editing);

  const save = useCallback(
    (value: string) => {
      const url = normalizeApiBase(value);
      if (!url) {
        seq.current++; // a pending check must not hide this
        setCheck({ state: "error", text: `Not an http address: ${value}` });
        setEditing(null);
        setFocus(ADDRESS);
        return;
      }
      setApiBase(url);
      setBase(url);
      setEditing(null);
      setFocus(TEST);
      test(url);
    },
    [test],
  );

  const saveKey = useCallback(
    (value: string) => {
      setApiKey(value.trim());
      setKey(value.trim());
      setEditing(null);
      setFocus(TEST);
      if (base) test(base);
    },
    [base, test],
  );

  const at = editing ? -1 : focus;
  return (
    <View style={ui.safe} testID="settings">
      <ContextChip
        parts={base ? ["Home", "Settings"] : ["Settings"]}
        kind="room"
      />
      <T style={[type.display, styles.head]}>Settings</T>
      <Row
        i={ADDRESS}
        focus={at}
        value={base || "not set"}
        valueID="settings-api-base"
      />
      <Row
        i={KEY}
        focus={at}
        value={key ? maskKey(key) : "none"}
        valueID="settings-api-key"
      />
      {/* Errors are plain text (no red), per the spec; the state is in data-state. */}
      <Row
        i={TEST}
        focus={at}
        value={check.text}
        valueID="settings-check"
        dataSet={{ state: check.state }}
        busy={check.state === "checking"}
      />
      <Row i={DONE} focus={at} />
      <T style={styles.note}>
        The server address is the computer or cloud running Replay. The API key
        is needed by a cloud server. Both are kept on this TV.
      </T>
      {editing ? null : (
        <KeyLegend
          items={[
            { k: "▲▼", label: "Move" },
            { k: "Select", label: focus === DONE ? "Done" : "Choose" },
            ...(base ? [{ k: "Back", label: "Home" }] : []),
          ]}
          style={{ bottom: safe.y }}
        />
      )}
      {editing === "base" ? (
        <TextEntryDialog
          idPrefix="api-base"
          title="Replay API address"
          initial={base}
          keys={URL_KEYS}
          onSubmit={save}
          onCancel={() => setEditing(null)}
        />
      ) : editing === "key" ? (
        <TextEntryDialog
          idPrefix="api-key"
          title="Replay API key"
          keys={KEY_KEYS}
          display={maskKey}
          onSubmit={saveKey}
          onCancel={() => setEditing(null)}
        />
      ) : null}
    </View>
  );
}

/** One list row: the item's label on the left, its value on the right; Chalk fill with
 *  Floor text when focused. */
function Row({
  i,
  focus,
  value,
  valueID,
  dataSet,
  busy,
}: {
  i: number;
  focus: number;
  value?: string;
  valueID?: string;
  dataSet?: Record<string, string>;
  /** a check is running: a spinner before the value */
  busy?: boolean;
}) {
  const on = i === focus;
  return (
    <View
      testID={`settings-item-${i}`}
      dataSet={{ focused: on ? "true" : "false" }}
      style={[styles.row, on && styles.rowOn]}
    >
      <T style={[styles.label, on && styles.ink]}>{ITEMS[i]}</T>
      {busy ? (
        <View style={styles.spin}>
          <ActivityIndicator
            size={Platform.OS === "web" ? px(40) : "small"}
            color={on ? color.floor : color.chalk}
            testID="settings-checking"
          />
        </View>
      ) : null}
      {valueID ? (
        <T
          testID={valueID}
          dataSet={dataSet}
          style={[styles.value, on && styles.ink]}
          numberOfLines={1}
        >
          {value}
        </T>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  head: { marginTop: px(64), marginBottom: sp(5) },
  row: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    width: px(1200),
    height: px(88),
    paddingHorizontal: sp(4),
    marginBottom: sp(2),
    borderRadius: radius.card,
    backgroundColor: color.bench,
  },
  rowOn: { backgroundColor: color.chalk },
  spin: { marginLeft: "auto", marginRight: sp(2) },
  label: { ...type.body, fontFamily: undefined, fontWeight: "600" },
  ink: { color: color.floor },
  value: {
    ...type.body,
    color: color.bleacher,
    maxWidth: px(720),
    textAlign: "right",
  },
  note: {
    ...type.meta,
    color: color.bleacher,
    marginTop: sp(4),
    maxWidth: px(1200),
  },
});
