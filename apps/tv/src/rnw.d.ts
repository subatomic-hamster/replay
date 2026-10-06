// react-native-web renders `dataSet` as data-* attributes (the Playwright hooks shared
// with apps/web: data-focused, data-player-id, …). Native ignores the prop.
import "react-native";

declare module "react-native" {
  interface ViewProps {
    dataSet?: Record<string, string | number | undefined>;
  }
  interface TextProps {
    dataSet?: Record<string, string | number | undefined>;
  }
}
