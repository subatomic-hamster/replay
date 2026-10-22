"""D-89 eval harness: a calib.json for a clip with no visible court lines.

A level camera: a standing person's pixel height grows linearly with how far their feet
are below the horizon, h = k (y_foot - y_h). Fit k and y_h on the tracklets' tall boxes
(upper envelope per foot-y bin), then with a guessed focal length f the floor maps as
  Z = c / (y - y_h),  X = (x - cx) Z / f,  c = 1.8 f / k   (people are about 1.8 m).
Rough metres, enough for courtcam's merge and sprint gates; not a court fit.

Run on the 2v2 park clip (docs/test-data.md 3.1c):
  1. out/calib.json = any placeholder; courtcam run -i clip -o out --stages ingest,detect,track
  2. python ground_plane.py out            (overwrites out/calib.json)
  3. courtcam run -i clip -o out --stages court,identity,tracks
  4. python gt_eval.py samples/truth/basketball_2v2park_identity.json out/tracks
"""

# ttsr-ignore: py/no-print — command-line harness, prints are its output
import json
import sys
from pathlib import Path

import numpy as np

W, H = 1920, 1080


def main(out: Path, f: float = 1000.0) -> None:
    tl = json.loads((out / "_work/tracklets.json").read_text())
    ys, hs = [], []
    for t in tl["tracklets"]:
        b = np.asarray(t["boxes"], dtype=float)  # x, y, w, h
        tall = (b[:, 3] > 1.8 * b[:, 2]) & (b[:, 1] + b[:, 3] < H - 5)
        ys += list(b[tall, 1] + b[tall, 3])
        hs += list(b[tall, 3])
    ys, hs = np.asarray(ys), np.asarray(hs)
    edges = np.linspace(np.percentile(ys, 2), np.percentile(ys, 98), 15)
    xs, env = [], []
    for a, b in zip(edges[:-1], edges[1:], strict=True):
        m = (ys >= a) & (ys < b)
        if m.sum() > 20:  # a crouch or a cut-off box is shorter, never taller
            xs.append((a + b) / 2)
            env.append(np.percentile(hs[m], 80))
    k, b0 = np.polyfit(xs, env, 1)
    yh, c, cx = -b0 / k, 1.8 * f / k, W / 2
    hm = np.array([[c / f, 0.0, -cx * c / f], [0.0, 0.0, c], [0.0, 1.0, -yh]])
    calib = {
        "schema": "courtcam.calib.v1",
        "sport": "basketball",
        "variant": "half",
        "standard": "unknown",
        "landmarks_px": {},
        "H": hm.tolist(),
        "H_inv": np.linalg.inv(hm).tolist(),
        "reproj_error_px": 0.0,
        "residuals_px": {},
        "court_polygon_m": [[-15.0, 1.0], [15.0, 1.0], [15.0, 40.0], [-15.0, 40.0]],
        "court_polygon_px": [[0, yh + 5], [W, yh + 5], [W, H], [0, H]],
        "rim_m": [0.0, 1.575],
        "rim_px": [1400.0, 700.0],
        "k1": 0.0,
        "image_size": [W, H],
        "note": "eval harness: ground plane from people's heights, not a court fit",
    }
    (out / "calib.json").write_text(json.dumps(calib))
    print(json.dumps({"k": round(k, 4), "y_horizon": round(yh, 1), "boxes": len(ys)}))


if __name__ == "__main__":
    main(Path(sys.argv[1]), *(float(a) for a in sys.argv[2:3]))
