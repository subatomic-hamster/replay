# samples/real/ — Real-footage test corpus

Per D-7 (docs/decisions.md): this footage is for **local testing only**. It is
Creative-Commons-unverified YouTube content under the standard YouTube
license (see per-clip notes below) — it is **never redistributed or
committed**; only this MANIFEST.md is tracked in git (`samples/real/*` is
gitignored except this file). All clips were downloaded with `yt-dlp` and
cut/re-encoded with `ffmpeg`. Every accepted clip below was verified by
extracting and looking at real frames, not just judged from the title.

Downloaded 2026-09-22. Total corpus size: ~855 MB (15 clips + 15 frame
JPGs). All full source downloads were deleted after cutting.

**2026-09-22 second pass (elevated whole-court basketball):** the first pass's
three basketball clips (`parkwide`, `powellgym`, `pavilion`) are all
ground-level or corner-level cameras framing only about half the court at a
time. This pass specifically searched for elevated (balcony/mezzanine/
wall-mounted/auto-camera) fixed cameras showing the **whole court** — both
baselines, all sidelines — in one shot, amateur/rec-league level. Two were
found and accepted (`kennesawwide`, `northsidewide`), both from the same
recreational-basketball videographer using a fixed ultra-wide/panoramic
stitched camera mounted high in a gym corner. See rejected list below for the
~25 candidates (Pixellot, Veo, drone, intramural, church-league, etc.) that
were probed and did not qualify.

**2026-09-22 third pass (ultra-wide/fisheye lens footage, per D-22):** D-22
found the existing badminton clip (`russiaclub`) has no lens distortion
problem — it fails on *resolution* (168 px far-baseline height), not barrel
distortion — and that no `distortion.py` undistortion model is planned unless
a genuinely wide-angle clip is found and fails the reprojection gate with
radius-dependent residuals. This pass specifically searched for phone
0.5x-ultra-wide or GoPro wide/superview footage — strong visible barrel
distortion (straight court lines curved) — from an elevated fixed camera
framing one whole court with the far baseline ≥ ~250 px wide and the court
≥ ~350 px tall, to give that undistortion-path decision a real clip to test
against. One badminton clip and one basketball clip were found and accepted;
no pickleball clip meeting the distortion bar was found (see rejects below —
plenty of elevated, clean, single-court pickleball footage exists, but nearly
all of it is shot on standard GoPro wide, which shows negligible barrel
curvature at the frame edges, not the strong fisheye the brief asked for).

**2026-10-06 fourth pass (volleyball — the corpus had none):** searched YouTube
(including its Creative-Commons filter) for amateur/rec/school indoor
volleyball from a fixed, elevated camera showing the whole court in one shot
(both end lines, the net, players on both sides), ≥1080p, no pan/zoom, no
scorebug. Of the ~16 candidates probed by real frames, one qualified
(`westwashington`, **Creative Commons Attribution**, so it is the first corpus
clip in `samples/real` whose licence would allow committed evidence — see its entry for the
attribution it needs; it is still not committed). Nearly all other volleyball
on YouTube is shot from a low sideline/endline tripod (partial court), is a
broadcast production with pans and a score bar, or is a 360° camera upload. See
the rejected list below. Tooling: `yt-dlp` lives in
`/workspace/wt/replay-env/venvs/ytdlp`; the box's static `ffmpeg` segfaults on
DNS lookups (it can only read local files), so the cut was made by fetching only
the needed HLS segments of the 1080p H.264 stream with a small script and
muxing locally, instead of downloading the whole 3.5 h stream.

Naming: `<sport>_<venue-slug>_<NNN>s.mp4` = a continuous stream-copied
segment of live play (`ffmpeg -c copy`, cut on the nearest keyframe).
`<sport>_<venue-slug>_smoke.mp4` = a short re-encoded (H.264/AAC, constant
30 fps, faststart) smoke-test cut of the same source. Each clip has a
matching `.jpg` — one representative extracted frame.

---

## Accepted clips

### 1. `basketball_parkwide_240s.mp4` + `basketball_parkwide_smoke.mp4` — **recommended primary basketball dev clip**

- **Source:** https://www.youtube.com/watch?v=z7YPEMBNV5w — "Full Court action outside wide angle shot Game 2"
- **Uploader:** Kash Money Kel (https://www.youtube.com/@KashMoneyKel)
- **License/terms:** Standard YouTube License (as observed on the video page; no CC marking). Local testing only, per D-7.
- **Resolution/fps:** 1920x1080, 30 fps (source; H.264 after our cut)
- **Duration:** main clip 240 s (240.03), smoke 45 s
- **Sport:** basketball, outdoor asphalt park court, London-area estate court (based on architecture in background)
- **Lighting/venue:** full sun, clear sky, late-afternoon shadows — best lighting of the three basketball clips
- **Camera:** fixed, mounted on a low wall/ledge along the sideline, not panning, whole court (both hoops) in frame
- **Players on court:** ~10 (5v5 full-court pickup)
- **Issues:** none significant. Why primary: cleanest wide shot, both hoops and full baseline-to-baseline visible in one frame, no overlays, no bystander clutter, good contrast for player detection.

### 2. `basketball_powellgym_240s.mp4` + `basketball_powellgym_smoke.mp4`

- **Source:** https://www.youtube.com/watch?v=b4JazHs43JA — "12/8/2022 Powell pickup 5 Wide Angle only"
- **Uploader:** Snipers Basketball (https://www.youtube.com/@SnipersBasketballVideos)
- **License/terms:** Standard YouTube License. Local testing only, per D-7.
- **Resolution/fps:** 1920x1080, 30 fps
- **Duration:** main clip 240 s, smoke 30 s
- **Sport:** basketball, indoor gym
- **Lighting/venue:** fluorescent gym lighting + natural light through high windows, honey-colored hardwood
- **Camera:** fixed, elevated corner position (looks tripod/wall-mounted), whole court visible including both baskets
- **Players on court:** ~10 (5v5 full-court)
- **Issues:** none significant.

### 3. `basketball_pavilion_240s.mp4` + `basketball_pavilion_smoke.mp4` + `basketball_pavilion4k_140s.mp4` (4K bonus)

- **Source:** https://www.youtube.com/watch?v=uc33gFpWEgs — "Wayne's World - Game 4 Saturday 07/11"
- **Uploader:** IMDABROWN (https://www.youtube.com/@IMDABROWN)
- **License/terms:** Standard YouTube License. Local testing only, per D-7.
- **Resolution/fps:** native source is 4K (3840x2160) 30 fps. `basketball_pavilion_240s.mp4` is downscaled to 1920x1080 (VP9, stream-copied from a 1080p yt-dlp format); `basketball_pavilion4k_140s.mp4` is native 3840x2160 (VP9), 140 s, for testing the 4K→1080 crop path per the task brief.
- **Duration:** main clip 240 s; 4K clip 140 s; smoke 35 s
- **Sport:** basketball, outdoor **covered pavilion** court (steel-roofed, open sides)
- **Lighting/venue:** overcast/diffuse daylight under the roof, distinct from the other two basketball venues
- **Camera:** fixed, elevated, mounted under the pavilion roof; whole primary court in frame, plus part of a neighboring court
- **Players on court:** ~8 on the primary court, several more visible on the adjacent court in the background
- **Issues:** a second game on the neighboring court is partially visible at the right edge of frame — not a problem for the primary court's tracking but worth knowing if on-court filtering is naive about frame edges. Source video/audio codec is VP9 (not H.264); re-encode may be needed if the processing pipeline assumes H.264 input.

### 4. `pickleball_legacypark_240s.mp4` + `pickleball_legacypark_smoke.mp4`

- **Source:** https://www.youtube.com/watch?v=clzJtKSMcbU — "Len Pickleball: Pickleball Meetup at Legacy Park in Kennesaw GA (8.09.2025) Game 1 #pickleball"
- **Uploader:** Len PickleBall (https://www.youtube.com/@lenpickleball)
- **License/terms:** Standard YouTube License. Local testing only, per D-7.
- **Resolution/fps:** native source 4K (3840x2160) 60 fps; our clip downscaled to 1920x1080, 60 fps (VP9, stream-copied)
- **Duration:** main clip 240 s, smoke 35 s
- **Sport:** pickleball, outdoor court, **night game under stadium/park lighting**
- **Venue:** Legacy Park, Kennesaw GA — real venue signage ("Legacy Park") painted on the perimeter wall, not a video overlay
- **Camera:** fixed, elevated on the fence/post at one end, whole court + net + far side in frame, additional courts visible in the background
- **Players on court:** 4 (doubles)
- **Issues:** a brief (~2-3 s) "DOUBLES" score-graphic overlay flashes intermittently at point-scoring moments — confirmed by sampling frames every 30 s through the whole 300 s source: clean at t=0,5,15,60,90,120,150,180,240s; overlay visible at t=30,210,270s. It is **not** a persistent scorebug (unlike a rejected candidate below) — most of the clip is clean gameplay. Within this specific 240 s cut, the overlay appears briefly around clip-relative t≈15s and t≈195s. Worth knowing if testing overlay-robustness of court/player detection.
- **Note:** this replaced an initially-selected pickleball clip (see rejected list) that turned out to have a persistent, live-updating scorebug.

### 5a. `basketball_kennesawwide_240s.mp4` + `basketball_kennesawwide_smoke.mp4` — **RECOMMENDED PRIMARY (elevated whole-court)**

- **Source:** https://www.youtube.com/watch?v=bSbik1JWcVs — "11.28.23 - Milf-Hunters vs 24% Skyhooks - Basketball Gym Recording - Ultra Wide - 8:3 - 4K 20 FPS"
- **Uploader:** Wong This Way (https://www.youtube.com/@wongthisway)
- **License/terms:** Standard YouTube License (as observed; no CC marking). Local testing only, per D-7.
- **Resolution/fps:** 2560x960 (8:3 ultra-wide panoramic stitch), VP9, **20 fps** (source; H.264 after our re-encode for the smoke clip). Note: this is a purpose-built wide/panoramic gym camera rig (not 16:9), so "height" is 960px rather than 1080 — total pixel count (2.46 MP) exceeds standard 1080p (2.07 MP), and this is the same category of exception the task brief explicitly allows for Veo-style stitched-panorama uploads. fps is 20, not 30 — flagged as an issue below.
- **Duration:** main clip 240 s, smoke 50 s
- **Sport:** basketball, indoor gym, Kennesaw/Acworth GA area (per companion uploads from the same channel: "Kennesaw Recreation Basketball", "Acworth Recreational Basketball" — confirms recreational-league play, not a private/paid production)
- **Camera:** fixed, mounted high in a gym corner (roof-truss height), ultra-wide/panoramic lens or stitch — captures the **entire court in one shot**: both baselines, both hoops, all four bleacher sections, scorer's table. Verified fixed (not panning) by comparing frames at t=300s and t=1800s of the source — identical framing.
- **Players on court:** ~10 (5v5 full-court), adult rec league (team names visible in title: "Milf-Hunters" vs "24% Skyhooks" — casual adult beer-league naming), referee and scorer's table present
- **Issues:** a small wall-mounted electronic scoreboard is visible in the top-left of frame — confirmed by close-up crop to be a real physical LED scoreboard (blurred/pixelated as filmed through the wide lens, partially occluded by a roof-truss shadow), not a video overlay, consistent with how physical venue signage is treated elsewhere in this manifest. 20 fps (not 30) and VP9 codec (not H.264) are the two deviations from spec — the smoke-test clip re-encodes to 30 fps H.264 via `libopenh264` per this box's ffmpeg build. No cuts, no software overlay, no commentary (ambient gym/crowd audio only; mean volume -24.9 dB, consistent with room ambience, not close-mic'd narration).

### 5b. `basketball_northsidewide_240s.mp4` + `basketball_northsidewide_smoke.mp4`

- **Source:** https://www.youtube.com/watch?v=xglRThRzdXM — "12.5.23 - 24% Skyhooks vs Hutters - Basketball Gym Whole Court Recording - Ultra Wide - 8:3"
- **Uploader:** Wong This Way (https://www.youtube.com/@wongthisway) — same channel/camera rig as 5a, different game/venue (Northside Hospital Cherokee-sponsored gym, per wall signage)
- **License/terms:** Standard YouTube License. Local testing only, per D-7.
- **Resolution/fps:** 2560x960 (8:3 ultra-wide panoramic), VP9, 20 fps (source); smoke clip re-encoded to 30 fps H.264 via `libopenh264`.
- **Duration:** main clip 240 s, smoke 50 s
- **Sport:** basketball, indoor gym, same recreational league as 5a (24% Skyhooks appear in both games)
- **Camera:** fixed, elevated gym-corner mount, ultra-wide/panoramic — whole court, both baselines and hoops, all bleachers in one shot. Same rig/style as 5a, different physical gym.
- **Players on court:** ~10 (5v5 full-court), adult rec league, referee and scorer's table present
- **Issues:** same 20 fps / VP9 deviations as 5a. Real physical wall scoreboard + "Northside Hospital Cherokee" sponsor banner visible (venue signage, not an overlay). No cuts, no software overlay, no commentary (ambient audio; mean volume -23.7 dB).

### 6. `badminton_russiaclub_240s.mp4` + `badminton_russiaclub_smoke.mp4`

- **Source:** https://www.youtube.com/watch?v=p0PXNjNhE-c — "Russian badminton amateur doubles part 1"
- **Uploader:** Grigorii (https://www.youtube.com/@Greg_tennis)
- **License/terms:** Standard YouTube License. Local testing only, per D-7.
- **Resolution/fps:** 1920x1080, 29.97 fps
- **Duration:** main clip 240 s, smoke 35 s
- **Sport:** badminton, indoor hall
- **Lighting/venue:** artificial overhead lighting, hardwood floor, large windows along one wall
- **Camera:** fixed, low/floor-level position in one corner (GoPro-style wide lens, visible barrel distortion at frame edges), whole court in frame including both service boxes and the net
- **Players on court:** 4 (doubles)
- **Issues:** camera is at floor/low height rather than elevated, so vertical FOV is a bit tight near the net; fisheye distortion at the extreme edges. Otherwise clean — no overlays, no cuts.

### 7. `badminton_auditorium_240s.mp4` + `badminton_auditorium_smoke.mp4` — **strong barrel-distortion candidate, primary for the D-22 undistortion test**

- **Source:** https://www.youtube.com/watch?v=HOxJxhcPfqg — "GoPro 📸 Badminton Full Game 💯✨"
- **Uploader:** Internet scholar (https://www.youtube.com/@internetscholar)
- **License/terms:** Standard YouTube License (as observed; no CC marking). Local testing only, per D-7.
- **Resolution/fps:** 1920x1080, 29.97 fps, H.264 (GoPro-style wide/superview lens — letterboxed to a narrower vertical FOV inside the 16:9 container, consistent with a superview capture)
- **Duration:** source 557.5 s; main clip cut from source t=60–300 (240 s); smoke cut from t=60–110 (50 s)
- **Sport:** badminton doubles, indoor — a converted auditorium/assembly hall (real venue signage on the stage proscenium reads "...SARAN DASS AUDITORIUM"; brick side walls hung with large framed portraits, clearly a repurposed hall, not a dedicated badminton venue — amateur/informal play)
- **Camera:** fixed, elevated (above head height) and standing **beside the court, in the plane of the net** — not behind a baseline. The net projects to a single near-vertical line at x ≈ 930, the court's long axis runs **left–right** across the frame, and **both back boundary lines fall at or just outside the frame edges** (measured through the calibrated fit: the two back lines run off-frame at x = −61 px and x = 1922 px). That is why `corner_nl/nr/fl/fr` are absent from `badminton_auditorium_240s.landmarks.json` by design (D-19) and why the clip needs the `k1` lens model to calibrate at all (D-25). It shows **strong visible barrel distortion**: the sidelines and the auditorium's straight ceiling/wall lines are all visibly curved (bowed) across the frame, especially near the edges. Verified fixed (not panning/zooming) by comparing frames at source t=30 s, t=100 s, and t=480 s — identical framing throughout.
- **Framing measurements (re-measured through the calibrated `k1` fit — the earlier “1050 / 1800 / 450 px” numbers were right but mislabelled: they measure the court's *width* direction, not its length):** the court's 13.40 m **length** runs left–right and **overflows the frame** — the near (camera-side) sideline is visible from x ≈ 9 to x ≈ 1915 px, i.e. the full 1920 px width with both ends cut off, and the far sideline spans x ≈ 386–1477 px (**≈ 1091 px**, the old “far baseline ≈ 1050 px”). The court's 6.10 m **width** runs top–bottom: **≈ 466 px** at the net (y 517→983) and ≈ 500 px at either back boundary line (the old “court height ≈ 450 px”). The usual far-baseline / court-height bar does not apply to this framing — what matters here is that the across-court scale is nearly uniform (person boxes 117–483 px tall, p95 324) rather than pickleball's 7× run.
- **Players on court:** 4 (doubles), casual dress (no matching kit), no scoreboard/referee — amateur pickup game
- **Issues:** none significant. No overlays, no cuts, no commentary (ambient hall/gym audio only). The image is letterboxed top and bottom (black bars baked into the source, consistent with a GoPro superview/wide capture placed in a 16:9 container) — the playable-court region is the full 1920 px width but a reduced vertical band of the 1080 px height; this does not affect the width-based far-baseline measurement above.

### 8. `basketball_ceilingcam_240s.mp4` + `basketball_ceilingcam_smoke.mp4` — **extreme fisheye, ceiling/backboard-structure-mounted**

- **Source:** https://www.youtube.com/watch?v=ll8od7ZLySI — "GoPro: Pick Up Basketball"
- **Uploader:** Naoki Murayama (https://www.youtube.com/@naokimurayama6397)
- **License/terms:** Standard YouTube License (as observed; no CC marking). Local testing only, per D-7.
- **Resolution/fps:** 1280x720 (720p60 was the highest format YouTube served for this video — no 1080p source exists), H.264. Below the corpus's usual 1080p floor, kept anyway because the distortion and full-court elevated framing are otherwise an excellent match for the D-22 test case and the measured pixel counts clear the bar even unscaled (see below).
- **Duration:** source 602.1 s; main clip cut from source t=90–330 (240 s); smoke cut from t=90–140 (50 s)
- **Sport:** basketball, indoor gym, full-court pickup game (shared multi-sport floor markings, single basketball setup in use)
- **Camera:** fixed, mounted extremely high and close to/above the backboard structure at one end (appears ceiling- or backboard-frame-mounted, looking almost straight down the court) — **extreme barrel/fisheye distortion**: gym sideline boundary tape bows dramatically outward, the glass safety barrier at the bottom of frame curves into a wide arc, both baskets (near, large, bottom-center; far, small, top-center) are visible in one shot. Verified fixed by comparing frames at source t=30 s and t=200 s — identical framing (same glass-barrier and boundary-line geometry).
- **Framing measurements (native 1280x720, measured via pixel-grid overlay crop):** far baseline/boundary line ≈ **1150 px** wide (≈1725 px equivalent scaled to a 1920-wide/1080p frame); near baseline ≈ full frame width; whole-court height (far to near boundary line) ≈ **510 px** native (≈765 px equivalent at 1080p scale). Clears both thresholds by a wide margin even without upscaling.
- **Players on court:** ~8–10 (pickup game, mixed clothing, no uniforms/referee — amateur)
- **Issues:** two small wall-mounted electronic scoreboards are visible top-left and top-right of frame — confirmed static/non-live-updating across the two sampled timestamps, consistent with real physical venue scoreboards (as elsewhere in this manifest), not a video overlay. Native resolution is 720p, not 1080p — flagged above. No cuts, no software overlay, no commentary (ambient gym audio only).

### 9. `volleyball_westwashington_240s.mp4` + `volleyball_westwashington_smoke.mp4` — **primary volleyball clip, Creative Commons (CC BY)**

- **Source:** https://www.youtube.com/watch?v=b3aiaYKG3-c — "25 Volleyball Austin vs West Washington" (livestream recording, uploaded 2025-10-19, 12 499 s)
- **Uploader:** West Washington Livestream (https://www.youtube.com/@WestWashingtonLivestream)
- **License/terms:** **Creative Commons Attribution license (reuse allowed)** — read from the video's YouTube metadata (`license` field) by `yt-dlp`, 2026-10-06. Attribution required if any derivative is ever published or committed: "West Washington Livestream, '25 Volleyball Austin vs West Washington', https://www.youtube.com/watch?v=b3aiaYKG3-c, CC BY". Under D-7 the footage itself is still not committed here; the licence only means that a later decision may allow committed evidence from it (check the licence on the page again at that point; it is the uploader's claim and says nothing about the players or any music/trademarks).
- **Decision (D-76): local only despite CC BY.** The players are high-school students (minors) at a school game. Frames, cutouts, scene packages and recordings derived from this clip stay in gitignored docs/evidence/local/ and on the box, like every YouTube clip; nothing derived from it is committed or published.
- **Resolution/fps:** 1920x1080, 30 fps, H.264 (stream-copied from the 1080p HLS rendition), AAC audio. The audio track is **re-encoded** (AAC 128 kb/s, 44.1 kHz stereo) because muxing the HLS audio segments with `-c copy` silently truncated it to 108 s; the video is a pure stream copy. Mean volume −36.9 dB (gym ambience, whistles, ball contact — no commentary).
- **Duration:** main clip 240 s, cut from source t = 4377.9–4617.9 s (first HLS segment boundary at/after 4380 s); smoke 30 s = the first 30 s of the main clip, re-encoded H.264 yuv420p CFR 30 + AAC, faststart. Sizes: main 58.1 MB, smoke 10.0 MB.
- **Sport:** indoor volleyball, high-school girls (Austin vs West Washington), a school gym ("Senator Pride", bleachers with spectators on the far side). Amateur and unbranded production; the gym is a shared basketball/volleyball floor (blue basketball lines, red volleyball lines — the red lines are the court; the blue centre line lies under the net).
- **Camera:** fixed (verified identical at source t = 100, 1000, 3000, 4500, 6000, 8000, 10 000 and at the last frame of the cut), **elevated and standing in the plane of the net** (like `badminton_auditorium`): the court's long axis runs left–right in the image, the net projects to a near-vertical line at x ≈ 1040–1090, and **both end lines, both sidelines, both attack lines and the net are fully in frame** with players on both sides. The lens is rectilinear (the painted lines stay straight edge to edge; no `k1` model was needed — homography reprojection error 1.26 px, see the landmarks file).
- **Framing measurements (native 1920x1080):** far sideline y ≈ 485, near sideline y ≈ 702 (net direction, 9 m ≈ 217 px); end lines at x ≈ 331–584 (left) and 1496–1852 (right) (18 m ≈ 1270–1520 px); players ≈ 90–130 px tall.
- **Players on court:** 12 (6 a side) in white/navy vs black; plus a referee standing at the near net post, a person at each end line, and the teams' benches along the bottom edge (bottom left and bottom right of the frame, outside the court polygon).
- **Landmarks:** `volleyball_westwashington_240s.landmarks.json` — 10 hand-clicked points (4 corners, 2 centre-line/sideline crossings, 4 attack-line ends) read off zoomed crops of a 43-frame temporal median of the clip. Naming: near end = left end line, `l` sideline = the far/top one (a rotation, not a mirror, of the template).
- **Issues:** a small physical scoreboard hangs top-left (a real LED scoreboard, partly a venue sign, not a video overlay; no software overlay anywhere). The cut contains a team huddle/timeout (seen at ≈ 150 s into the clip) and between-rally dead time — normal for a real set. Spectators and the team benches sit outside the court polygon; the gym's blue basketball arcs and lines are decoys for any line detector. The source is a livestream recording of several matches, so a different part of it can be cut on request (frames at source t = 100, 3000, 4500, 6000, 8000 s show live play; t = 1000 s a huddle; t = 10 000 s an empty floor).

---

## Rejected candidates

- `xSZ4ifFrbzg` "5v5 pick up hoop game" — handheld/POV camera, follows a player around; not a fixed tripod shot.
- `wlIkiJxvwGU` "Our Savior Lutheran HS Pick up Basketball" (Bamboo Project Sports) — persistent "GAME 2" title-card text and a channel logo watermark visible for the entire recording (confirmed at two timestamps).
- `C574jxCNtT8` "Bad Boyz Vs. Veo Max Championship" — camera positioned at low/chest height rather than elevated, youth/branded league (physical wall signage "BRODIE"-style production feel), doesn't show the whole court cleanly.
- `P28N9WMobQo` "Mic'd Up in the Brodie League... Coach G Hooping NYC" — has an added commentary audio track ("Mic'd Up"), and the venue is a branded semi-pro "Brodie" league gym with matching uniforms, not a grassroots pickup game.
- `SNv4KgIg0Ik` "TRIPODS VS RAINING WET" — very low source resolution (640x480); rejected on metadata alone.
- `Fv09uxE0Mxc` "4.5 Rec Doubles | NEPC Jacky/Joe vs Tyler/Stuart" (pickleball) — persistent broadcast-style scorebug graphic (player names + running score box) visible for the whole clip.
- `SMY8DuavKnQ` "Sunday Pickleball Doubles... Sam & Rob vs Jordan and John" — initially accepted, then rejected after a second-frame check showed the on-screen score caption changes over time (0-3 at one timestamp, 2-3 at another) — i.e. a persistent, live-updating scorebug, not a static intro title. Deleted after download.
- `_PJR7ebrt8s` "Tripod was hit by ball, Video NOT Centered" (pickleball, Sigler Park CA) — camera was knocked off-center per the title; frame shows only the near half of the court clearly, opponents not visible. Kept as a documented backup option, not downloaded further.
- ytsearch results for "pickleball backyard game tripod no commentary" — all irrelevant (drills/tips, paddle and scoreboard-gadget product reviews); no usable full-game footage found.
- Various high-view-count "men's league" creator videos (`7IdyAVn9jiE`, `2zW7E4mY7Fw`, `9-IhuqpU85M`, `wgyLhcrqWxo`) — not probed further; clickbait titles + large view counts strongly suggest edited/produced content with cuts, out of scope per the brief.
- All NCAA/ACC/professional broadcast replays surfaced by generic basketball searches (Duke, UNC, Howard, etc.) — excluded outright, professional broadcast footage is out of scope.

**2026-09-22 second pass (elevated whole-court basketball) — rejected candidates:**

- `rrL6yv0CjIY` "Jun 26 25 Open Gym Runs *PIxellot Camera" — elevated, whole court (both hoops) in one fixed shot, but has a persistent software-composited "Pixellot Air" scorebug graphic burned into the bottom-left corner throughout (confirmed live-updating score across timestamps, distinct from the real physical wall scoreboard also in frame) — disqualified by the "no scorebug/overlay" requirement.
- `XqPPmSHg5Yw` "LAMBS vs STORM [Pixellot View]" — same issue: persistent Pixellot Air scorebug overlay confirmed live-updating (2-0 at t≈302s, 29-45 at t≈3002s) across the whole video; also appears to be a more competitive club/travel game (bench, uniforms) rather than casual rec play.
- `OCapTc3aTSo` / `TTGSBqjlhTc` / `hpQ8iCkms8E` — titles suggested basketball ("Church Gym", "Full Court view") but probed frames showed **volleyball** games being played on shared gym courts with a basketball hoop visible in the background — wrong sport.
- `NfamCBgl8As` "Winter 2026 Intramural Basketball Championships" — probed frame shows a dodgeball-style game (players running with thrown balls, no dribbling/shooting) despite the "Basketball Championships" title/overlay; also has a persistent video scorebug graphic.
- `_n3lWa5Fij0` "No Drama Basketball Pickup Game Abingdon Virginia" — camera is low/eye-level and only frames the near basket, not elevated, not whole court.
- `ElIHjogkyOY` "Drone Basketball!! 5v5 Full Court COED 4K" — outdoor elementary-school yard with multiple half-courts, persistent "TuneSquad vs Monstars" scorebug overlay, casual/small-scale, not a genuine full 5v5 single-court game.
- `TEYI_xRcRLc` "Winter Intramurals Recreational Basketball Game 2" — source video is sideways/rotated and low quality.
- `1tl7FonW3qE` "Game 3 Sept 18, 2022" (Jakarta International School) — camera at low/eye-level courtside, only partial court in frame, persistent "GAME 3" score-text overlay.
- `6IVd74XvIOI` "Saint Sabina adult open gym (Game 5)" — decent adult open-gym game but camera only captures ~3/4 of the court and has a persistent "INSTAGRAM / BALL OR NOTHING TV" text-overlay watermark.
- `lFdJR9KwY20` "University of Oregon club open gym" — handheld/walking camera (visible shake), not a fixed mount.
- `FxYDGj6_qzE` "SNC employees at Reyes Gym (Yi 4K action camera)" — camera at low/child-eye height, only one basket clearly in frame, not elevated.
- `Pr1X_g1ZFb0`, `9JoQ5sxyEhM` (Scout AI Test Boys Varsity Basketball), `gA1GcQPvwDk` (Surrey Winter Rec), `_htpkrwH-wg` (Iowa City corner camera), `RXJaRA_lDoM` (Evergreen v Clover Hill Rec), `BiQwvJekkwg` (Timberland Large Gym Recording), `l4ZiCbg-At8` (Gym Camera Recording) — all returned "This video is not available" / extraction errors when probed; not evaluable.
- Generic Pixellot/Veo/XbotGo/BallHawk/Scout-AI product-demo and marketing videos (`TU3o3DlyShY`, `-J0XbwP8qUk`, `BS9iZQG5jkc`, `hGexK8fifns`, `QJEIORttKgI`, etc.) — short promotional clips, not usable full-game footage.
- Numerous high-view "men's league"/AAU/travel-club highlight-reel channels and all D1/pro/Olympic/NBA/NCAA broadcast results surfaced by the broader queries — out of scope (edited/produced or professional).

**Verdict on this pass:** genuine elevated, whole-court, fixed-camera, overlay-free amateur basketball footage **does exist on YouTube and is findable** — but it is a narrow niche. The two accepted clips come from a single hobbyist videographer (same channel, same custom ultra-wide panoramic camera rig) filming a Georgia recreational league; most other "elevated"-looking candidates turned out to be auto-production systems (Pixellot/Veo) with baked-in scorebug overlays that violate the "no overlay" requirement, or were mislabeled (wrong sport, dodgeball, intramural livestream chapters), or had cameras that were elevated but not truly whole-court. Expect to spend real search time (or accept a persistent-scorebug clip as a documented compromise) if more than 2 such clips are needed.

**2026-09-22 third pass (ultra-wide/fisheye lens) — rejected candidates:**

Badminton:
- `72e6bA-MlrI` "GoPro Badminton Interhub Friendly Nov 2016" — only 1280x720; camera at floor/net-post height aimed diagonally across several adjacent courts, not a clean single-court framing.
- `rGVDqvn0s_k` "Badminton match doubles warm up match || gopro hero9" — 1920x1080 and visibly wide-angle, but has a persistent "Prash vlogs" text watermark and a YouTube-subscribe-button graphic burned into the frame throughout; also frames the net at a shallow diagonal across multiple courts rather than one court squarely.
- `oh5MXJYb5fw` "Badminton Game - GoPro perspective - @ KCBC" — only 1280x720; camera at near-net/low height, not elevated.
- `qtCz3aaQ6t4` "GOPRO badminton game #1" — only 960x720; rejected on resolution.
- `h7k6pEYOHbs` "Insta360 Wide angle Badminton" — 1906x1080, but a 360-camera reframe showing 4–5 adjacent courts across a whole gymnasium in one fisheye shot, not isolated to a single court.

Pickleball (no accept this pass — see verdict below):
- `bOynMUEGkgY` "Tony&Robert vs David&Jimmy Part 2... GoPro 8 1080p 120fps" — 1920x1080, cleanly elevated fence-post mount, single court, but edge crops show negligible barrel curvature (near-straight lines even at frame edges) — doesn't meet the "strong distortion" bar.
- `nz_0v_6FPSQ` "6/30/21 Shaw A Final GoPro (2nd half)" — same profile and same rejection reason: elevated fence mount, clean single court, but essentially straight lines edge-to-edge.
- `fIlyGME7QgY` "PBC Phil/Dave vs Tommy/Steve 04292024 Montebello Park" — persistent "Pickleball Chumps" logo overlay burned into the top-left corner throughout.
- `dip4UwR3eI4` "3-20-17 Monday Night Pickleball Rec Play - Yi 4k Action Cam" — shared gym floor with basketball/volleyball lines heavily overlapping the pickleball court, confusing multi-line surface, not a clean dedicated court.
- `HEsxWFXAt6c` "3.0 Pickleball Match" — camera close/low right behind the near baseline (not clearly elevated), tight FOV covering only ~1.5 courts, faces blurred (privacy post-processing).
- `t6CK3Yw-MNU` "Americano Doubles Fixed Partner, Live from Kampus Bali" — StreamYard-produced live-stream recording: persistent software logo overlay plus a permanent split-screen multi-camera layout (each pane far below 1080p-equivalent width).
- Dead-end search phrasings that returned no usable results (camera-gear reviews, vlogging tutorials, product comparisons instead of match footage): "pickleball ultra wide iphone tripod full game", "pickleball tripod balcony fixed camera", "pickleball GoPro superview full match", "pickleball fisheye camera fence post", "pickleball action cam elevated fence full match", "pickleball court camera high angle full game fisheye", "pickleball GoPro wide angle doubles full game no music".

Basketball:
- `n3eVq_FppeM` "YMCA - GoPro - 2/3/17 - full court" — 1280x720 max, elevated with some distortion, but not pursued further once `ll8od7ZLySI` was confirmed as a stronger (more distorted, more clearly whole-court) candidate within the time-box.

**Verdict on this pass:** strongly barrel-distorted (fisheye/superview) footage that also satisfies the elevated-fixed-camera, single-court, overlay-free framing bar **exists for badminton and basketball** but is rare and took real search effort to isolate — most "GoPro badminton/basketball" results are POV/head-mounted, multi-court gym-wide shots, or have channel-branding overlays. For **pickleball specifically, no qualifying clip was found in this pass**: clean, elevated, single-court, overlay-free pickleball footage is comparatively easy to find, but essentially all of it is shot on a standard (not ultra-wide/superview) GoPro or phone lens with negligible barrel distortion at the frame edges — the distortion requirement, not the framing requirement, is the bottleneck for this sport. Revisit with a dedicated search for phone-native 0.5x-lens pickleball uploads (e.g. TikTok/Instagram re-uploads) if a distorted pickleball clip is still needed.

**2026-10-06 fourth pass (volleyball) — rejected candidates** (each probed by extracting real frames at one to eight timestamps; licence is the YouTube `license` field, "standard" = no CC marking):

- `d1yMxzgAJrU` "Semi-Finals: Hilo vs Waiakea" (Hilo High School; CC BY, 1080p60, 1 h 40 min) — school broadcast production: full-width lower-third graphics and title cards over the court, camera at bleacher level and panning with the play, only part of the court in frame.
- `Z9yffRnNo88` "Frontier Regional School Volleyball vs Lenox" (FCATMedia; CC BY, 1080p30) — low sideline camera showing about half the court, persistent live scorebug box top-left.
- `_OI_ZgrKriA` "Warner University (Los Gallos de Oro) Vs Insystem (adult team)" (Mr Meow; CC BY, 1080p30, 426 s) — adult team but a low handheld-looking sideline view of a part of the court, only 7 min long.
- `9uNiGQNQMmw` "2020 MN SELECT 16-1s vs NL 17-2 Set 1" (Lisa Stremmel; CC BY, 1080p24) — camera behind the net at near-net height (net mesh fills the foreground), far court only; 24 fps youth club game.
- `N1G7oWrS6YA` "LWCS Varsity Girls vs JCA" (Living Water Christian School; CC BY, 1080p30) — shot from the referee's stand: a referee fills the right third of the frame at close range, a basketball-court floor, only a few players visible.
- `XD6HIjJF8bk` "Beechwood 7th vs Summit View" (Beechwood Class of 202x; CC BY, 1080p30) — low corner camera, tight on one half of the court.
- `ZkCYtf-VFJ0` "Champions Cup 25 — Court 1" (SRDS Preston; CC BY, 1080p30, 10.9 h livestream) — low sideline view, persistent score/sponsor overlay top-left and top-right, players on the near side much larger than the far side.
- `K_UqS490MSs` "Coed Tournament Feb 6/semifinal" (Andre Troyer; standard, 1080p30) and the same channel's other coed-tournament uploads (`pk46UoPr0a8`, `pctziBt34HM`, `MMFNsIdpZBs`, `0iJ6qmwzdN4`, `7zwl1MvOzAU` — only the first was probed by frame, the rest were judged from the channel) — low sideline tripod at gym floor height, about 2/3 of one court, people in the foreground.
- `ke81j9xEBaI` / `5T5YnoIny-Y` (Luck Sports & Entertainment; standard, 1080p60/30, ~1 h each) — rec-league coed 6v6 at ground level from one side with a basketball backboard in the way, partial court.
- `A6Zslh8ijPc` "NFJC - EVPC Friday League" (SundaySchool VolleyballClub; standard, 1080p30) — low corner shot, two courts in frame, each only partly visible.
- `0zBSGdQ2y9U` "Cream Team (Game 1) [Yankee C+ 10/23/22]" (The AHU Project; standard, 2560x1440p60) — low corner camera, partial court.
- `FP0cyNH5GJk` "Volleyball GJSD vs Richland" (Darren Buchko StreamPro; standard) — corner camera at spectator height, persistent score banner at the top of the frame.
- `WYYTzOeRnks` "Varsity Lady Indians vs. Summersville (Full Court)" (Couch K-12 Schools; standard, **720p**) — a fixed mid-height shot with the whole court but the scorers' heads fill the bottom of the frame and the source is only 1280x720; kept as a backup if a second fixed-camera volleyball venue is wanted.
- `4hy0iMH5_j0` "Delaney Moon Volleyball Game film … 18s Nationals" (standard, 1080p30) — low end-line tripod in a convention-centre hall with a persistent score bar and many neighbouring courts.
- `XaYCXR-5O5E` "DCD Coed Quads A/B" (Jason Shen; standard, 1080p60) — outdoor sand court, 4v4 at net height.
- Not probed by frame (judged from metadata/title): the `IVL … Coed League` series by Paul Sander (spherical 360° videos, "lifeguard view" — reframing needed, and the descriptions say so); all POV/GoPro head-cam uploads (MaKuro, Hamaji Neo, BrodesVolleyball, DTvolleyball, Volleyball Gorillas, moomoocowjonny GoPro); NCAA/Olympic/club-nationals broadcasts (`mSlJCiiYkBA`, `LcAWutYusEE`, `rKahSdKGgv4`, `lTh-Fk3E5QQ`, …) — professional or produced, out of scope; `jTfTKiIM0I8` and `MoIrAlqAOMc` — "video not available" when probed.
- Search phrasings that returned no usable fixed/elevated rec volleyball: "volleyball end line camera full match high angle", "volleyball scrimmage high camera wall mounted", "volleyball bleachers high angle view game", "adult recreational volleyball match full court view" (returns only product-review/ camera-gear videos and tutorials).

**Verdict on this pass:** a genuinely elevated, fixed, whole-court, overlay-free **indoor volleyball** clip at 1080p exists on YouTube under a CC licence, but it is a school livestream (one fixed camera on the gym wall) rather than rec-league footage; every adult rec-league upload found was filmed from the floor. Search effort was high: the CC filter yields very few volleyball videos and each frame probe costs a minute through yt-dlp.

---

## Disk usage

- `samples/real/` total: **~855 MB** (19 video clips + 19 JPEG frames) + **~68 MB** for the volleyball pass (2 clips + 2 JPEG frames + 1 landmarks file) added 2026-10-06.
- All intermediate/full source downloads were deleted after cutting (the volleyball pass never downloaded a full source: only the 258 s of HLS segments around the cut, deleted afterwards).
