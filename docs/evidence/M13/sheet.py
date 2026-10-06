"""M13 evidence from the make-demo game: an 11-angle sheet of one highlight at one instant.
python sheet.py <game dir> <play id> <t in replay s> <out.jpg>"""

import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

gd, play, t, out = Path(sys.argv[1]), sys.argv[2], float(sys.argv[3]), sys.argv[4]
m = json.loads((gd / "replays" / play / "manifest.json").read_text())
W, H = 480, 270
tiles = []
for a in m["angles"]:
    png = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-ss",
            str(t),
            "-i",
            str(gd / a["url"]),
            "-frames:v",
            "1",
            "-vf",
            f"scale={W}:{H}",
            "-f",
            "image2pipe",
            "-vcodec",
            "png",
            "-",
        ],
        capture_output=True,
        check=True,
    ).stdout
    img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
    label = f"Tier {a['tier']}: {a['id']}"
    cv2.rectangle(img, (0, 0), (W, 26), (20, 17, 14), -1)
    cv2.putText(img, label, (8, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA)
    tiles.append(img)
while len(tiles) % 4:
    blank = np.full((H, W, 3), 20, np.uint8)
    cv2.putText(
        blank, "SYNTHETIC demo game", (60, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2
    )
    cv2.putText(
        blank, f"{play} at +{t:.1f} s", (60, 160), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 1
    )
    tiles.append(blank)
rows = [np.hstack(tiles[i : i + 4]) for i in range(0, len(tiles), 4)]
cv2.imwrite(out, np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 82])
print(out, len(m["angles"]), "angles")
