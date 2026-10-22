// Root: installs the platform remote handler and renders the current route. Screens
// import only RN primitives, packages/tv-core and this app's modules — never a platform
// package (those stay in src/platform/ and playback/PlayerSurface's Media).
import { useState } from "react";
import { Platform, StatusBar, StyleSheet, View } from "react-native";
import { apiBase } from "./api";
import { navigate, useRoute, type Route } from "./nav";
import { usePlatformKeys } from "./platform/keys";
import { AddGame } from "./screens/AddGame";
import { Advice } from "./screens/Advice";
import { Clips } from "./screens/Clips";
import { Search } from "./screens/Search";
import { Home } from "./screens/Home";
import { Pair } from "./screens/Pair";
import { Players } from "./screens/Players";
import { Profile } from "./screens/Profile";
import { Review } from "./screens/Review";
import { Settings } from "./screens/Settings";
import { Watch } from "./screens/Watch";
import { color } from "./theme";

export function App({ initial }: { initial?: Route }) {
  // Seed the route once, before the first render reads it. No API address yet (a build
  // without REPLAY_API_BASE, first run): Settings first.
  useState(() =>
    navigate(
      initial ?? (apiBase() ? { name: "library" } : { name: "settings" }),
    ),
  );
  usePlatformKeys();
  const route = useRoute();

  return (
    <View style={styles.root} {...ROOT_FOCUS}>
      <StatusBar hidden />
      {screen(route)}
    </View>
  );
}

function screen(r: Route) {
  switch (r.name) {
    case "library":
      return <Home />;
    case "watch":
      return (
        <Watch
          key={`${r.gameId}/${r.way ?? ""}/${r.q ?? ""}/${r.play ?? ""}`}
          gameId={r.gameId}
          initialMode={r.mode}
          initialPid={r.pid}
          initialT={r.t}
          initialWay={r.way}
          initialPlay={r.play}
          initialCard={r.card}
          q={r.q}
        />
      );
    case "review":
      return <Review key={r.gameId} gameId={r.gameId} />;
    case "clips":
      return <Clips key={r.gameId} gameId={r.gameId} />;
    case "search":
      return <Search key={r.gameId} gameId={r.gameId} />;
    case "advice":
      return <Advice key={r.gameId} gameId={r.gameId} />;
    case "pair":
      return <Pair gameId={r.gameId} />;
    case "players":
      return <Players from={r.from} />;
    case "profile":
      return (
        <Profile
          key={r.profileId}
          profileId={r.profileId}
          from={r.from}
          back={r.back}
        />
      );
    case "settings":
      return <Settings />;
    case "add":
      return <AddGame />;
  }
}

// Android hands remote keys only down the focused-view chain, and nothing in the app is
// natively focusable (focus is app state, ui.tsx), so with no focused view no key ever
// reached JS (seen on a Fire TV Stick). The root, which never unmounts, holds focus.
const ROOT_FOCUS =
  Platform.OS === "web" ? {} : { focusable: true, hasTVPreferredFocus: true };

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: color.floor },
});
