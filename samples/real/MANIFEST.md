# samples/real/ — Real-footage test corpus

Per D-7 (docs/decisions.md): this footage is for **local testing only**. It is
Creative-Commons-unverified YouTube content under the standard YouTube
license (see per-clip notes below) — it is **never redistributed or
committed**; only this MANIFEST.md is tracked in git (`samples/real/*` is
gitignored except this file). All clips were downloaded with `yt-dlp` and
cut/re-encoded with `ffmpeg`. Every accepted clip below was verified by
extracting and looking at real frames, not just judged from the title.

Downloaded 2026-09-22. Total corpus size: ~696 MB (13 clips + 13 frame
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

---

## Disk usage

- `samples/real/` total: **~696 MB** (15 video clips + 15 JPEG frames)
- All intermediate/full source downloads were deleted after cutting.
