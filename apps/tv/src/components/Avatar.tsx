// A profile's photo in a circle, or its initials when it has none.
import { Image, StyleSheet, View } from "react-native";
import { initials } from "../../../../packages/tv-core/src/profiles";
import { api } from "../api";
import { color, px } from "../theme";
import { T } from "../ui";

export function Avatar({ name, photo, size }: { name: string; photo: string | null; size: number }) {
  const box = { width: px(size), height: px(size), borderRadius: px(size / 2) };
  return (
    <View style={[styles.avatar, box]} testID="avatar" dataSet={{ photo: photo ? "true" : "false" }}>
      {photo ? (
        <Image source={{ uri: api.profileMediaUrl(photo) }} style={[StyleSheet.absoluteFill, box]} resizeMode="cover" />
      ) : (
        <T style={{ fontSize: px(Math.max(24, size * 0.38)), fontWeight: "800", color: color.dim }}>{initials(name)}</T>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  avatar: { backgroundColor: color.line, alignItems: "center", justifyContent: "center", overflow: "hidden" },
});
