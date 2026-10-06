// Root: installs the platform remote handler and renders the current route. Screens
// import only RN primitives, packages/tv-core and this app's modules — never a platform
// package (those stay in src/platform/ and playback/PlayerSurface's Media).
import { useState } from "react";
import { StatusBar, StyleSheet, View } from "react-native";
import { apiBase } from "./api";
import { navigate, useRoute, type Route } from "./nav";
import { usePlatformKeys } from "./platform/keys";
import { Advice } from "./screens/Advice";
import { Clips } from "./screens/Clips";
import { Highlights } from "./screens/Highlights";
import { Rallies } from "./screens/Rallies";
import { Search } from "./screens/Search";
import { Library } from "./screens/Library";
import { Pair } from "./screens/Pair";
import { Players } from "./screens/Players";
import { Profile } from "./screens/Profile";
import { Replay, ReplayList } from "./screens/Replay";
import { Review } from "./screens/Review";
import { Settings } from "./screens/Settings";
import { Watch } from "./screens/Watch";
import { color } from "./theme";

export function App({ initial }: { initial?: Route }) {
  // Seed the route once, before the first render reads it. No API address yet (a build
  // without REPLAY_API_BASE, first run): Settings first.
  useState(() => navigate(initial ?? (apiBase() ? { name: "library" } : { name: "settings" })));
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
    case "clips":
      return <Clips key={r.gameId} gameId={r.gameId} />;
    case "rallies":
      return <Rallies key={r.gameId} gameId={r.gameId} />;
    case "search":
      return <Search key={r.gameId} gameId={r.gameId} />;
    case "advice":
      return <Advice key={r.gameId} gameId={r.gameId} />;
    case "pair":
      return <Pair gameId={r.gameId} />;
    case "players":
      return <Players from={r.from} />;
    case "profile":
      return <Profile key={r.profileId} profileId={r.profileId} from={r.from} />;
    case "settings":
      return <Settings />;
  }
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: color.ink },
});
