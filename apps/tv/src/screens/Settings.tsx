// Settings: the Replay API address and API key, set with the D-pad and kept on the device.
// Reached from the library's top row and from the "Could not reach the Replay API" banner;
// the app opens here on first run when the build has no default (REPLAY_API_BASE).
// The key (X-Replay-Key, D-80 cloud mode) is only ever shown masked to its last 4 characters.
import { useCallback, useEffect, useRef, useState } from "react";
import { View } from "react-native";
import { apiBase, apiKey, maskKey, normalizeApiBase, probeApi, setApiBase, setApiKey } from "../api";
import { TextEntryDialog } from "../components/TextEntryDialog";
import { useDpad, type DpadAction } from "../input";
import { navigate } from "../nav";
import { color, px } from "../theme";
import { Hint, Pill, T, styles as ui } from "../ui";

const ITEMS = ["Change address", "API key", "Test connection", "Done"] as const;
const [ADDRESS, KEY, TEST, DONE] = [0, 1, 2, 3];
const URL_KEYS = [
  ["http://", "192.168.", "10.0.", ":8000", ".local"],
  [..."1234567890"],
  [..."ABCDEFGHIJ"],
  [..."KLMNOPQRST"],
  [..."UVWXYZ.:/-"],
];
// The deploy's keys are `openssl rand -hex 32`; the letters type lowercase.
const KEY_KEYS = [[..."1234567890"], [..."ABCDEFGHIJ"], [..."KLMNOPQRST"], [..."UVWXYZ._-"]];

type Check = { state: "idle" | "checking" | "ok" | "error"; text: string };

export function Settings() {
  const [base, setBase] = useState(apiBase);
  const [key, setKey] = useState(apiKey);
  const [focus, setFocus] = useState(base ? TEST : ADDRESS);
  const [editing, setEditing] = useState<"base" | "key" | null>(base ? null : "base");
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
      <T style={{ color: color.dim }}>API key (X-Replay-Key, needed by a cloud deploy):</T>
      <T testID="settings-api-key" style={{ fontSize: px(36), fontWeight: "700", marginVertical: px(12) }}>
        {key ? maskKey(key) : "none"}
      </T>
      <View style={{ flexDirection: "row", marginTop: px(32) }}>
        {ITEMS.map((label, i) => (
          <Pill key={label} label={label} focused={!editing && focus === i} testID={`settings-item-${i}`} />
        ))}
      </View>
      <Hint>Left/Right move · Select picks · Back returns · Both are kept on this device</Hint>
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
