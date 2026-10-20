// D-80: a QR code drawn with plain Views (one per dark run of a row), so it is the same on
// react-native-web and the Fire TV with no SVG dependency. Black on white (inverted codes
// trip some phone scanners), the standard 4-module quiet zone, and a module size of whole
// physical pixels so neighbouring runs never show a seam.
import { useMemo } from "react";
import { PixelRatio, View } from "react-native";
import qrcode from "qrcode-generator";
import { px } from "../theme";

const QUIET = 4;

/** Module count and, per row, the dark runs as [first column, length]. EC level M: the
 *  ~170-char upload URL fits in version 9 (53 modules). */
export function qrRuns(text: string): {
  n: number;
  rows: [number, number][][];
} {
  const qr = qrcode(0, "M");
  qr.addData(text);
  qr.make();
  const n = qr.getModuleCount();
  const rows = Array.from({ length: n }, (_, r) => {
    const runs: [number, number][] = [];
    for (let c = 0; c < n; c++) {
      if (!qr.isDark(r, c)) continue;
      const last = runs[runs.length - 1];
      if (last && last[0] + last[1] === c) last[1]++;
      else runs.push([c, 1]);
    }
    return runs;
  });
  return { n, rows };
}

/** `size`: the target edge in design px (1920x1080), quiet zone included. At 640 a v9 code
 *  gets 10 px modules on a 1080p TV — a ~33 cm code on a 55-inch set, easy from the couch. */
export function QrCode({
  text,
  size,
  testID,
}: {
  text: string;
  size: number;
  testID?: string;
}) {
  const { n, rows } = useMemo(() => qrRuns(text), [text]);
  const ratio = PixelRatio.get();
  const cell =
    Math.max(1, Math.floor((px(size) * ratio) / (n + 2 * QUIET))) / ratio;
  const edge = cell * (n + 2 * QUIET);
  return (
    <View
      testID={testID}
      dataSet={{ modules: n, cell }}
      style={{
        width: edge,
        height: edge,
        backgroundColor: "#fff",
        borderRadius: px(12),
      }}
    >
      {rows.flatMap((runs, r) =>
        runs.map(([c, len]) => (
          <View
            key={`${r}.${c}`}
            style={{
              position: "absolute",
              left: (QUIET + c) * cell,
              top: (QUIET + r) * cell,
              width: len * cell,
              height: cell,
              backgroundColor: "#000",
            }}
          />
        )),
      )}
    </View>
  );
}
