// Root: installs the platform remote handler and renders the current route. Screens
// import only RN primitives, packages/tv-core and this app's modules — never a platform
// package (those stay in src/platform/ and playback/PlayerSurface's Media).
import { useState } from "react";
import { StatusBar, StyleSheet, View } from "react-native";
import { navigate, useRoute, type Route } from "./nav";
import { usePlatformKeys } from "./platform/keys";
import { Highlights } from "./screens/Highlights";
import { Library } from "./screens/Library";
import { Pair } from "./screens/Pair";
import { Replay, ReplayList } from "./screens/Replay";
import { Review } from "./screens/Review";
import { Watch } from "./screens/Watch";
import { color } from "./theme";

export function App({ initial }: { initial?: Route }) {
  // Seed the route once, before the first render reads it.
  useState(() => initial && navigate(initial));
  usePlatformKeys();
  const route = useRoute();

  return (
    <View style={styles.root}>
      <StatusBar hidden />
      {screen(route)}
    </View>
  );
}

function screen(r: Route) {
  switch (r.name) {
    case "library":
      return <Library />;
    case "watch":
      return <Watch key={r.gameId} gameId={r.gameId} initialMode={r.mode} initialPid={r.pid} initialT={r.t} />;
    case "highlights":
      return <Highlights key={r.gameId} gameId={r.gameId} q={r.q} />;
    case "review":
      return <Review key={r.gameId} gameId={r.gameId} />;
    case "replays":
      return <ReplayList key={r.gameId} gameId={r.gameId} />;
    case "replay":
      return <Replay key={`${r.gameId}/${r.playId}`} gameId={r.gameId} playId={r.playId} />;
    case "pair":
      return <Pair gameId={r.gameId} />;
  }
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: color.ink },
});
