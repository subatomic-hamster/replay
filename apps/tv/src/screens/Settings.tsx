// Settings: the Replay API address, set with the D-pad and kept on the device. Reached from
// the library's top row and from the "Could not reach the Replay API" banner; the app opens
// here on first run when the build has no default (REPLAY_API_BASE).
import { useCallback, useEffect, useRef, useState } from "react";
import { View } from "react-native";
import { apiBase, normalizeApiBase, probeApi, setApiBase } from "../api";
import { TextEntryDialog } from "../components/TextEntryDialog";
import { useDpad, type DpadAction } from "../input";
import { navigate } from "../nav";
import { color, px } from "../theme";
import { Hint, Pill, T, styles as ui } from "../ui";

const ITEMS = ["Change address", "Test connection", "Done"] as const;
const URL_KEYS = [
  ["http://", "192.168.", "10.0.", ":8000", ".local"],
  [..."1234567890"],
  [..."ABCDEFGHIJ"],
  [..."KLMNOPQRST"],
  [..."UVWXYZ.:/-"],
];

type Check = { state: "idle" | "checking" | "ok" | "error"; text: string };

export function Settings() {
  const [base, setBase] = useState(apiBase);
  const [focus, setFocus] = useState(base ? 1 : 0);
  const [editing, setEditing] = useState(!base);
  const [check, setCheck] = useState<Check>({ state: "idle", text: "" });

  // Only the latest check may report (an older, slower one must not overwrite it).
  const seq = useRef(0);
  const test = useCallback((url: string) => {
    const n = ++seq.current;
    const report = (c: Check) => n === seq.current && setCheck(c);
    setCheck({ state: "checking", text: "Checking…" });
    probeApi(url)
      .listGames()
      .then(
        (games) => report({ state: "ok", text: `Connected · ${games.length} game${games.length === 1 ? "" : "s"}` }),
        (e: Error) => report({ state: "error", text: `Not reachable: ${e.message}` }),
      );
  }, []);

  // Show whether the saved address works as soon as the screen opens.
  useEffect(() => {
    if (base) test(base);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onAction = useCallback(
    (a: DpadAction) => {
      if (a === "left") setFocus((i) => Math.max(0, i - 1));
      else if (a === "right") setFocus((i) => Math.min(ITEMS.length - 1, i + 1));
      else if (a === "select" && focus === 0) setEditing(true);
      else if (a === "select" && focus === 1 && base) test(base);
      else if ((a === "select" && focus === 2) || a === "back") {
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
        setEditing(false);
        setFocus(0);
        return;
      }
      setApiBase(url);
      setBase(url);
      setEditing(false);
      setFocus(1);
      test(url);
    },
    [test],
  );

  return (
    <View style={ui.screen} testID="settings">
      <T style={ui.h1}>Settings</T>
      <T style={{ color: color.dim }}>Replay API address (the computer running services/api):</T>
      <T testID="settings-api-base" style={{ fontSize: px(44), fontWeight: "700", marginVertical: px(16) }}>
        {base || "not set"}
      </T>
      <T
        testID="settings-check"
        dataSet={{ state: check.state }}
        style={{ color: check.state === "ok" ? color.made : check.state === "error" ? color.missed : color.dim, minHeight: px(40) }}
      >
        {check.text}
      </T>
      <View style={{ flexDirection: "row", marginTop: px(32) }}>
        {ITEMS.map((label, i) => (
          <Pill key={label} label={label} focused={!editing && focus === i} testID={`settings-item-${i}`} />
        ))}
      </View>
      <Hint>Left/Right move · Select picks · Back returns · The address is kept on this device</Hint>
      {editing ? (
        <TextEntryDialog
          idPrefix="api-base"
          title="Replay API address"
          initial={base}
          keys={URL_KEYS}
          onSubmit={save}
          onCancel={() => setEditing(false)}
        />
      ) : null}
    </View>
  );
}
