# samples/real/ — Real-footage test corpus

Per D-7 (docs/decisions.md): this footage is for **local testing only**. It is
Creative-Commons-unverified YouTube content under the standard YouTube
license (see per-clip notes below) — it is **never redistributed or
committed**; only this MANIFEST.md is tracked in git (`samples/real/*` is
gitignored except this file). All clips were downloaded with `yt-dlp` and
cut/re-encoded with `ffmpeg`. Every accepted clip below was verified by
extracting and looking at real frames, not just judged from the title.

Downloaded 2026-09-22. Total corpus size: ~523 MB (11 clips + 11 frame
JPGs). All full source downloads were deleted after cutting.

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

### 5. `badminton_russiaclub_240s.mp4` + `badminton_russiaclub_smoke.mp4`

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

---

## Disk usage

- `samples/real/` total: **~523 MB** (11 video clips + 11 JPEG frames)
- All intermediate/full source downloads were deleted after cutting.
