// Shared screen bits: async loading, the API error banner (E-22), text and focusable
// "buttons" at 10-foot sizes. Buttons are not native-focusable: focus is app state moved by
// the D-pad, so the native focus engine never fights the spatial algorithm.
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { StyleSheet, Text, View, type StyleProp, type TextStyle, type ViewStyle } from "react-native";
import { useDpad } from "./input";
import { navigate } from "./nav";
import { color, focusRing, font, px } from "./theme";

export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [nonce, setNonce] = useState(0);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const run = useCallback(fn, deps);

  useEffect(() => {
    let live = true;
    setError(null);
    run().then(
      (v) => live && setData(v),
      (e: Error) => live && setError(e),
    );
    return () => {
      live = false;
    };
  }, [run, nonce]);

  return { data, error, reload: () => setNonce((n) => n + 1) };
}

export function T({
  children,
  style,
  testID,
  dataSet,
  numberOfLines,
}: {
  children: ReactNode;
  style?: StyleProp<TextStyle>;
  testID?: string;
  dataSet?: Record<string, string | number | undefined>;
  numberOfLines?: number;
}) {
  return (
    <Text style={[styles.text, style]} testID={testID} dataSet={dataSet} numberOfLines={numberOfLines}>
      {children}
    </Text>
  );
}

/** A focusable pill: ring + filled amber when focused (a shape change, not colour only). */
export function Pill({
  label,
  focused,
  active,
  testID,
  dataSet,
  style,
}: {
  label: string;
  focused: boolean;
  active?: boolean;
  testID?: string;
  dataSet?: Record<string, string | number | undefined>;
  style?: StyleProp<ViewStyle>;
}) {
  return (
    <View
      testID={testID}
      dataSet={{ focused: focused ? "true" : "false", ...dataSet }}
      style={[
        styles.pill,
        focusRing(focused),
        focused && { backgroundColor: color.accent },
        !focused && active && { backgroundColor: color.line },
        style,
      ]}
    >
      <T style={[styles.pillText, focused && { color: color.onAccent }]}>{label}</T>
    </View>
  );
}

export function Hint({ children }: { children: ReactNode }) {
  return <T style={styles.hint}>{children}</T>;
}

/** E-22: every screen that fetches renders this instead of a blank screen. */
export function ApiErrorBanner({ error, onRetry }: { error: Error; onRetry: () => void }) {
  // Right reaches Settings: a wrong API address must be fixable from here.
  const [onSettings, setOnSettings] = useState(false);
  useDpad(
    useCallback(
      (a) => {
        if (a === "left" || a === "right") setOnSettings(a === "right");
        else if (a === "select") {
          if (onSettings) navigate({ name: "settings" });
          else onRetry();
        } else if (a === "back") navigate({ name: "library" });
      },
      [onRetry, onSettings],
    ),
  );
  return (
    <View style={styles.screen} testID="api-error">
      <T style={{ fontSize: font.h2 }}>Could not reach the Replay API.</T>
      <T style={{ color: color.dim }}>{error.message}</T>
      <View style={{ flexDirection: "row", marginTop: px(24) }}>
        <Pill label="Retry" focused={!onSettings} testID="api-error-retry" />
        <Pill label="Settings" focused={onSettings} testID="api-error-settings" />
      </View>
    </View>
  );
}

export function Loading() {
  return (
    <View style={styles.screen}>
      <T>Loading…</T>
    </View>
  );
}

export const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: color.ink, padding: px(64) },
  text: { color: color.fg, fontSize: font.body },
  h1: { color: color.fg, fontSize: font.title, fontWeight: "700", marginBottom: px(24) },
  h2: { color: color.fg, fontSize: font.h2, fontWeight: "700", marginBottom: px(12) },
  hint: { color: color.dim, fontSize: font.small, marginTop: px(24) },
  pill: {
    paddingHorizontal: px(24),
    paddingVertical: px(10),
    borderRadius: px(40),
    backgroundColor: color.raised,
    marginRight: px(16),
    marginBottom: px(12),
  },
  pillText: { color: color.fg, fontSize: font.body, fontWeight: "600" },
});
