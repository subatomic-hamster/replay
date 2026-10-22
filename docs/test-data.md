# Test data: what we have, where it lives, what it may be used for

Last updated 2026-10-06 (overnight CC-footage search). Companion docs: `samples/real/MANIFEST.md` (the
YouTube-standard-licence corpus), `docs/decisions.md` D-7 (corpus policy), `docs/licenses.md`.

## 1. Purpose and licensing rules

Three kinds of test data, with different rules about where they may appear:

| Kind                                          | Where it lives                                                                      | Commit it?                            | May appear in committed evidence / demo / README?                                                                                                                                                                                                                                                                                                                                                    |
| --------------------------------------------- | ----------------------------------------------------------------------------------- | ------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **samples/real** (YouTube _standard_ licence) | laptop `samples/real/` (gitignored) and box `/workspace/wt/replay-env/samples-real` | never (only `MANIFEST.md` is tracked) | **No** (D-7). Evidence derived from it goes to `docs/evidence/local/<milestone>/` (gitignored) and is referenced by path only.                                                                                                                                                                                                                                                                       |
| **Creative-Commons clips** (section 3)        | box only: `/workspace/wt/replay-env/samples-cc/<sport>_<slug>/`                     | never commit the video files          | **CC BY: yes, with attribution** (credit + licence link + say it was cut/modified). **CC BY-SA: yes, but anything derived from it must carry the same licence** (add a share-alike note; avoid mixing it into artefacts we want to keep under a different licence). **CC0: yes, no obligation** (credit anyway). Never NC/ND/PD-mark material from the Internet Archive without a separate decision. |
| **Synthetic** (`samples/synthetic`)           | repo                                                                                | yes                                   | **Yes, fully ours**, always labelled synthetic.                                                                                                                                                                                                                                                                                                                                                      |

Rules of thumb:

- The licence string we record is the one the platform reports, copied verbatim (for YouTube: the `license` field of `yt-dlp -j`). The search filter alone is never trusted; every accepted clip was verified from metadata.
- YouTube's "Creative Commons Attribution license (reuse allowed)" is CC BY 3.0. Attribution = title, author/uploader, source URL, licence name + URL, and a note if changed (we cut to 240 s; no re-encode).
- Frames/GIFs taken from CC clips that show identifiable people (tournament players, spectators): keep committed material small (crops, overlays, thumbnails) and always attributed. Nothing here has a model release.
- A "Creative Commons" label does not make re-uploaded TV/broadcast footage free to use. Every candidate was looked at; broadcast re-uploads were rejected.
- None of this footage is ever sent to a paid service; all processing happens on the box (hfbox).

## 2. Existing corpus: `samples/real/` (YouTube standard licence, local only, D-7)

All rows: licence = Standard YouTube License (no CC marking), **local only, never committed, never in demo/committed assets**. Full detail (framing, issues, rejected candidates) is in `samples/real/MANIFEST.md`; this is just the index. Box path: `/workspace/wt/replay-env/samples-real/<name>_240s.mp4` (plus `_smoke.mp4`, `.jpg`, and `.landmarks.json` where present).

| Name (`<name>_240s.mp4`)                               | Sport      | Source URL                                  | Notes                                                                               | Licence          | Local-only |
| ------------------------------------------------------ | ---------- | ------------------------------------------- | ----------------------------------------------------------------------------------- | ---------------- | ---------- |
| `basketball_parkwide`                                  | basketball | https://www.youtube.com/watch?v=z7YPEMBNV5w | outdoor, 1080p30, fixed low wall mount, whole court                                 | Standard YouTube | yes        |
| `basketball_powellgym`                                 | basketball | https://www.youtube.com/watch?v=b4JazHs43JA | indoor gym, 1080p30, fixed elevated corner                                          | Standard YouTube | yes        |
| `basketball_pavilion` (+ `basketball_pavilion4k_140s`) | basketball | https://www.youtube.com/watch?v=uc33gFpWEgs | covered court, native 4K, fixed elevated; neighbouring court visible                | Standard YouTube | yes        |
| `basketball_kennesawwide`                              | basketball | https://www.youtube.com/watch?v=bSbik1JWcVs | 2560x960 ultra-wide, 20 fps, elevated whole court (primary)                         | Standard YouTube | yes        |
| `basketball_northsidewide`                             | basketball | https://www.youtube.com/watch?v=xglRThRzdXM | same rig as above, other gym                                                        | Standard YouTube | yes        |
| `basketball_ceilingcam`                                | basketball | https://www.youtube.com/watch?v=ll8od7ZLySI | 720p60, extreme fisheye, backboard/ceiling mount                                    | Standard YouTube | yes        |
| `pickleball_legacypark`                                | pickleball | https://www.youtube.com/watch?v=clzJtKSMcbU | 1080p60 from 4K, night, fence mount; brief "DOUBLES" overlay                        | Standard YouTube | yes        |
| `badminton_russiaclub`                                 | badminton  | https://www.youtube.com/watch?v=p0PXNjNhE-c | 1080p30, low corner cam, 168 px far baseline (resolution fail, D-22)                | Standard YouTube | yes        |
| `badminton_auditorium`                                 | badminton  | https://www.youtube.com/watch?v=HOxJxhcPfqg | 1080p30 GoPro superview, strong barrel distortion, back lines off-frame (D-19/D-25) | Standard YouTube | yes        |

There is no volleyball footage in `samples/real` (the synthetic generator covers volleyball; section 5).
The rejected-candidate lists in MANIFEST.md (Pixellot/Veo scorebug clips, handheld, wrong sport, etc.) are not repeated here; this file does not re-test them.

## 3. Accepted Creative-Commons clips (box only)

Root: `/workspace/wt/replay-env/samples-cc/` (421 MB total, 2026-10-06). Every clip dir holds the cut file(s), `SOURCE.txt` (URL, uploader, licence, attribution, cut points) and `source.info.json` (full yt-dlp metadata). All cuts are `ffmpeg -c copy` (no re-encode) of 240 s of live play; the full-length downloads were deleted. All sources are YouTube videos whose `license` metadata field is exactly **"Creative Commons Attribution license (reuse allowed)"** (= CC BY 3.0, https://creativecommons.org/licenses/by/3.0/), retrieved 2026-10-06 with yt-dlp 2026.08.19.

Verification frames (viewed by the author of this doc, local scratchpad only, not in repo): `bb_q1_sheet.jpg`, `bb_q3_sheet.jpg`, `basketball_nottingham_widecam_900.jpg`, `basketball_nottingham_widecam_3300.jpg`, `pickleball_surrey2022_sheet.jpg`, `pickleball_surrey2022_60.jpg`, `pickleball_surrey2022_400.jpg`, `pickleball_surrey2026_sheet.jpg`, `pickleball_surrey2026_100.jpg`, `pickleball_surrey2026_700.jpg`, `badminton_usnationals2012_sheet.jpg`, `badminton_usnationals2012_100.jpg`, `badminton_usnationals2012_700.jpg`, `badminton_fisheye_netpost_sheet.jpg`, `badminton_fisheye_netpost_40.jpg`, `badminton_fisheye_netpost_300.jpg` (frame filenames only).

### 3.1 Basketball: `basketball_nottingham_widecam/` (the only basketball clip that qualified)

- **Box files:** `/workspace/wt/replay-env/samples-cc/basketball_nottingham_widecam/basketball_nottingham_widecam_q1_240s.mp4` (source 300-540 s) and `..._q3_240s.mp4` (source 3000-3240 s)
- **URL:** https://www.youtube.com/watch?v=aH6PRcV4DHE
- **Title:** "25th October 2015 - Nottingham Wildcats vs Barking Abbey Crusaders wide angle cam view only"
- **Uploader:** Super League Basketball (https://www.youtube.com/channel/UCCCT9UtlzXTDTQR5GFGRUZg); description credits "(c) Peter Kaloczy 2015", filmed on an SJ4000 wide-angle action camera
- **Licence (exact):** `Creative Commons Attribution license (reuse allowed)`; licence URL https://creativecommons.org/licenses/by/3.0/
- **Attribution (paste-ready):** "25th October 2015 - Nottingham Wildcats vs Barking Abbey Crusaders wide angle cam view only" by Super League Basketball (video (c) Peter Kaloczy), https://www.youtube.com/watch?v=aH6PRcV4DHE, licensed CC BY 3.0 (https://creativecommons.org/licenses/by/3.0/). Segments cut to 240 s, otherwise unmodified.
- **Format:** 1920x1080, 30 fps, H.264, ~66 MB per 240 s cut. Source is 1080p30 (the same game also exists as a 4K60 two-camera edit `aEr8j7fPCYo`, CC BY as well, not downloaded because it cuts between cameras).
- **Shows:** a full indoor game (UK Super League Basketball channel; competition level not stated in the metadata. Q1 starts 1:07, Q2 19:23, Q3 44:28, Q4 1:02:54 in the source). 5v5 plus referees and bench.
- **Camera:** fixed wide-angle action camera at spectator-seat height on the sideline, whole court (both baskets, both baselines) in one frame, mild barrel distortion. No overlays, no cuts, no commentary. Honest limits: far-side players are small (roughly 30-60 px tall), spectator heads and a bin occlude the bottom strip, and the framing is **not perfectly static** (it drifts/is nudged by a few tens of px within a clip and differs between Q1 and Q3), so it is a good robustness test for court calibration rather than a pixel-stable one.
- **Allowed for:** development and tests on the box; committed evidence/demo WITH the attribution above (CC BY). Not a substitute for an elevated high-resolution corpus clip.
- **In the live AWS library (2026-10-21):** the Q1 cut is game `g_c8b6186280ac`, titled "Nottingham vs Barking Abbey (CC BY, Super League Basketball)" (the API has no description field, so the full attribution above is the credit of record). Uploaded the phone's way (multipart with the upload token). The auto-calibration was refused (score 0.75 < 0.9, D-72; it put the court on the far wall). The calibration is 13 hand-placed landmarks (near baseline = left basket; `l` = far sideline) on a player-free median of 41 frames, since the camera drifts < 2 px across the cut. Fit: k1 -0.415, lens RMS 3.66 px, API reprojection error 9.56 px (undistorted px, gate 16.7). Result notes are in docs/progress.md.
- **Hand annotation (D-90):** `samples/truth/nottingham_q1.json` and `nottingham_q3.json` (`replay.playlog.v1`, `use: evaluation`, "hand annotation (ground truth for evaluation)"; format in docs/playlog.md). They list every shot with release and rim time, basket, team, make or miss, and points, plus the in-arena scoreboard read at 1 fps as an independent check. Q1 runs 0-0 to dark 3, red 4. Q3 is the hold-out, annotated before any change was measured on it. Dark = Nottingham (home), red = Barking Abbey. Q1 dark attacks the left basket and Q3 the right; the camera is re-aimed between the cuts. Facts only, with the attribution above; never shown in the app. Score with `courtcam eval-events`.

#### 3.1b Basketball 3x3 proxy (demo scenario: a few players on a half court, D-88)

- **Title:** "ČBF 3x3 Tour 22.6. Ústí nad Labem", Wikimedia Commons, by Honza Nový, CC BY 3.0. URL: https://commons.wikimedia.org/wiki/File:%C4%8CBF_3x3_Tour_22.6._%C3%9Ast%C3%AD_nad_Labem.webm
- **Attribution (paste-ready):** "ČBF 3x3 Tour 22.6. Ústí nad Labem" by Honza Nový, https://commons.wikimedia.org/wiki/File:%C4%8CBF_3x3_Tour_22.6._%C3%9Ast%C3%AD_nad_Labem.webm, licensed CC BY 3.0 (https://creativecommons.org/licenses/by/3.0/). Cut to 58.7–74.4 s and lens-corrected (re-encoded).
- **Box only:** `/workspace/wt/replay-angles-data/src/cc3x3/` (source webm 1920x1080 VP8 29.97 fps 156 s; `cbf3x3_shot_rect.mp4` the cut, lens-corrected; `cbf3x3_shot_rect.landmarks.json`). Game `g_cc3x3` in the angles data dir.
- **What it is:** an edited montage of GoPro shots (fisheye, about 0.8 m high). The longest fixed shot (58.5–74.6 s) looks at the basket from beyond the arc: 3 v 3 in red and white/blue shirts and an orange referee.
- **Calibration:** the fisheye was corrected with division k1 = −0.5 (fitted so the near boundary line is straight, 0.9–1.6 px rms) at zoom 1.16. The landmarks were then read by hand on a player-free median: key corners, free-throw corners, rim, rim top; 6.6 px reprojection. The 3x3 court sits on the FIBA half template (same key and arc). It has no 14 m half-way line and its sidelines are not painted, so depth far from the key is extrapolated.
- **Hand annotation (D-90):** `samples/truth/cc3x3_usti.json`: 3 shots in the 15.7 s cut (makes at 1.75 s and 14.4 s, a rim-out at 10.1 s) and a pass caught at the rim (not a shot). Viewed at 8 fps over the whole cut and 15-30 fps around the rim.

#### 3.1c Basketball 2v2 park proxy (demo scenario for identity: four people, distinct clothes, D-89)

- **Box files:** `/workspace/wt/replay-env/samples-cc/basketball_2v2park/basketball_2v2park_120s.mp4` (source 60-180 s, `ffmpeg -c copy`), `full.mp4` (the whole 570 s download), `SOURCE.txt`, `source.info.json`
- **URL:** https://www.youtube.com/watch?v=z5bdgHqcShw
- **Title:** "2v2 BASKETBALL GAME"; **uploader:** M'ster Lewis (https://www.youtube.com/@MsterLewis), uploaded 2021-04-27
- **Licence (exact):** `Creative Commons Attribution license (reuse allowed)` (CC BY 3.0, https://creativecommons.org/licenses/by/3.0/), checked in the yt-dlp metadata on 2026-10-22
- **Attribution (paste-ready):** "2v2 BASKETBALL GAME" by M'ster Lewis, https://www.youtube.com/watch?v=z5bdgHqcShw, licensed CC BY 3.0 (https://creativecommons.org/licenses/by/3.0/). Cut to 120 s, otherwise unmodified.
- **Format:** 1920x1080, 23.976 fps, H.264 + AAC.
- **Shows:** a fixed tripod at court level beside one basket of an outdoor park court; 2v2 half court, four adults in clearly different clothes (grey shirt and black pants; grey #23 jersey and white pants; black shirt and shorts; cream shirt and maroon pants). Edited score cards between some points; cuts at 40-42 s and 480-483 s of the source, none inside the 120 s cut.
- **Honest limits:** the court lines are washed out by the sun, so there is no court calibration; the D-89 evaluation used a ground plane fitted to people's heights (`docs/evidence/D89-tracking/`), not a court fit. People pass close to the camera (very large boxes, frequent overlaps).
- **Ground truth:** `samples/truth/basketball_2v2park_identity.json` (hand-checked identity boxes at 10 Hz; how it was made is in its `source` field, including one fix by eye: A added at 40.2-41.1 s). Score with `docs/evidence/D89-tracking/gt_eval.py`.
- **Found by:** YouTube CC-filter searches from the box ("1v1 basketball full game", "2v2 basketball game", "2v2 pickup basketball", "1 on 1 basketball tripod", "basketball 21 game", "2 on 2 basketball", "3v3 half court basketball pickup", "basketball 2v2 tripod gym", "1v1 basketball outdoor court", "streetball 2v2"); 16 CC BY candidates viewed as 4-frame sheets. Close seconds: `7MloXoCl6LU` / `NY0t2bejspg` / `AThYgh0YRWA` (JaiArtHub 2v2, fixed tripod, visible court lines, but burned-in score graphics and four players mostly in black); the rest were handheld, vlog-edited, at night or with face overlays.

### 3.2 Pickleball: two clips from one tournament channel

Both: uploader **pickleball4you** (https://www.youtube.com/channel/UC83z_qzETSgcemFzZdtmFvw), hosted by Surrey Pickleball Club at South Surrey Athletic Park (BC, Canada), licence `Creative Commons Attribution license (reuse allowed)` (CC BY 3.0). 1920x1080, 29.97 fps, H.264, 240 s each. Fixed tripod behind one baseline, no overlays, no cuts, doubles, whole singles/doubles court visible with neighbouring courts and spectators in the background (tournament setting). Camera height is roughly standing eye level (not elevated), so the far side compresses; neither is a "phone on a fence post" high-angle shot.

**a) `pickleball_surrey2026/pickleball_surrey2026_240s.mp4`** (recommended pickleball CC clip)

- Box: `/workspace/wt/replay-env/samples-cc/pickleball_surrey2026/pickleball_surrey2026_240s.mp4` (58 MB, source 100-340 s)
- URL: https://www.youtube.com/watch?v=4M58YJoZ4O4 , "2026.09.04 MD4.0 (age 50+) John Lee + Ernest Tosch vs Brendan Fong + Anthony Chang (Gold Medal)", uploaded 2026-09-11 (9th Annual Grip'n Rip Tournament)
- Whole court incl. near baseline and both sidelines in frame, slightly raised angle; a line judge and neighbouring courts are visible. Cleanest framing of the CC set.
- Attribution: "2026.09.04 MD4.0 (age 50+) John Lee + Ernest Tosch vs Brendan Fong + Anthony Chang (Gold Medal)" by pickleball4you, https://www.youtube.com/watch?v=4M58YJoZ4O4, licensed CC BY 3.0 (https://creativecommons.org/licenses/by/3.0/). Segment cut to 240 s, otherwise unmodified.

**b) `pickleball_surrey2022/pickleball_surrey2022_240s.mp4`**

- Box: `/workspace/wt/replay-env/samples-cc/pickleball_surrey2022/pickleball_surrey2022_240s.mp4` (89 MB, source 60-300 s)
- URL: https://www.youtube.com/watch?v=wY_KUvQ8w7I , "2022.05.07 MXD 3.5-4.0 Bronze Medal Game", uploaded 2022-05-12 (2022 Spring Launch)
- Lower and closer than (a): the near-right corner of the court is clipped by the frame edge, the near player is sometimes cut off, a crowd stands behind the far baseline. Good as a harder framing, not for whole-court calibration.
- Attribution: "2022.05.07 MXD 3.5-4.0 Bronze Medal Game" by pickleball4you, https://www.youtube.com/watch?v=wY_KUvQ8w7I, licensed CC BY 3.0 (https://creativecommons.org/licenses/by/3.0/). Segment cut to 240 s, otherwise unmodified.

The same channel has dozens more tournament matches under the same licence (searches listed in section 4); more can be pulled the same way if a larger CC pickleball set is wanted.

**Allowed for (both):** box development/tests; committed evidence/demo with attribution. Players are identifiable members of the public.

### 3.3 Badminton: two clips, both with stated limits

Both: licence `Creative Commons Attribution license (reuse allowed)` (CC BY 3.0), 1920x1080, H.264, 240 s, fixed camera, no overlays or cuts.

**a) `badminton_usnationals2012/badminton_usnationals2012_240s.mp4`** (usable, with a caveat)

- Box: `/workspace/wt/replay-env/samples-cc/badminton_usnationals2012/badminton_usnationals2012_240s.mp4` (96 MB, source 100-340 s), 25 fps
- URL: https://www.youtube.com/watch?v=654WkfWSYf0 , "2012 US Badminton Adult National Championships Mixed Doubles Quarter Finals HD 1080P", uploader **Roy Huang** (https://www.youtube.com/channel/UCvyhCPEzN701h-hiqnxUkxg), uploaded 2012-04-24
- Mixed doubles on a tournament court filmed from the spectator seats behind the near baseline at low height. Both sidelines, the net and the far baseline are visible and players are discernible, but **two empty chairs (and sometimes a spectator) hide the bottom-centre of the frame and the near baseline**, and the court is a long way from the camera. Not a whole-court calibration clip; fine for player/shuttle-ish detection and rally segmentation tests.
- Attribution: "2012 US Badminton Adult National Championships Mixed Doubles Quarter Finals HD 1080P" by Roy Huang, https://www.youtube.com/watch?v=654WkfWSYf0, licensed CC BY 3.0 (https://creativecommons.org/licenses/by/3.0/). Segment cut to 240 s, otherwise unmodified.

**b) `badminton_fisheye_netpost/badminton_fisheye_netpost_240s.mp4`** (lens-distortion test only)

- Box: `/workspace/wt/replay-env/samples-cc/badminton_fisheye_netpost/badminton_fisheye_netpost_240s.mp4` (59 MB, source 40-280 s), 29.97 fps
- URL: https://www.youtube.com/watch?v=B9XLUHQfh4A , "Badminton recorded with fisheye lens (Hans & René)", uploader **bvconquesto** (https://www.youtube.com/channel/UCBCDrpIIUzTLJ9nBN4r2bAw), uploaded 2012-04-07
- Camera is mounted **on the net post** looking down the court with a strong fisheye lens (the description says "half court"). Two players visible, one at each side; lines and ceiling strongly curved. This is _not_ the product camera placement and not a whole-court view; use it only as a fisheye/undistortion test input alongside the standard-licence `badminton_auditorium`.
- Attribution: "Badminton recorded with fisheye lens (Hans & René)" by bvconquesto, https://www.youtube.com/watch?v=B9XLUHQfh4A, licensed CC BY 3.0 (https://creativecommons.org/licenses/by/3.0/). Segment cut to 240 s, otherwise unmodified.

### 3.4 Volleyball: none accepted

No volleyball clip met the bar (see section 4). Use `samples/synthetic/volleyball` for volleyball tests.

## 4. Searched, nothing (or not enough) suitable, by sport

Sources and method:

1. YouTube search with the Creative-Commons filter (`https://www.youtube.com/results?search_query=<q>&sp=EgIwAQ%3D%3D`) through yt-dlp `--flat-playlist -J`, from the box (`yt-dlp -4`). About 60 queries across the four sports. Metadata `license` was checked with `-j` for ~310 basketball results (all CC BY) and for every shortlisted clip; for the rest, the CC search filter was relied on only to _discover_, and nothing was accepted without a metadata check. Shortlisted candidates were downloaded at <=360p, 4 frames sampled across the video, contact sheets viewed; accepted ones were then re-downloaded at 1080p and re-checked on the cut.
2. Wikimedia Commons API (`filetype:video` search for basketball, "basketball game/court", pickleball, badminton, "volleyball game/match", ...), licence from `extmetadata`.
3. Internet Archive advancedsearch (`licenseurl:*creativecommons*`) for basketball, badminton, volleyball, pickleball.

Note: the box ffmpeg crashes on https inputs, so frames were taken from downloaded copies; YouTube watch-page requests from the box IP were rate-limited (HTTP 429 / "sign in" bot check) for about 25 minutes after the first 300-video metadata sweep, so the sweep was split and slowed.

### Basketball (1 accepted, most searched; large CC pool but almost all produced or handheld)

Queries (YouTube CC filter): full court basketball game tripod; pickup basketball wide angle; basketball full game gym fixed camera; rec league basketball full game; 5v5 pickup basketball full court; basketball open gym full court camera; basketball scrimmage wide angle; church league basketball game; adult league basketball game full; outdoor basketball court full game; basketball gym recording whole court; basketball game one camera high angle; 3x3 basketball full game; youth basketball game full court; high school basketball game full; basketball game recorded from bleachers; basketball tournament full game amateur; basketball pickup run raw footage; basketball gym camera fixed unedited full game; basketball one camera wide whole court recording; pickup basketball tripod; basketball game no commentary raw; basketball full court view elevated camera; basketball wide angle gym; basketball 5v5 gym recording; open gym basketball full game; basketball game from the stands; basketball tripod corner camera; rec league basketball tripod; basketball game wide shot; wide angle cam view only basketball; Super League Basketball full game wide angle.

Rejected after viewing frames (YouTube CC, id: reason):

- `9SiG9NU4p_Y` (Roundball BC rec league; the channel has ~50 similar CC uploads, only this one was viewed): close camera that follows the play, channel watermark; not a fixed whole-court view. The rest of the series was not checked and is assumed similar.
- `kzpP_It5wxI` (THE GREAT MAYA 3x3 series, Nepal, 4K30, dozens of uploads, only this one viewed): burned-in score banner and channel graphics, tracking camera, half-court 3x3.
- `CifX-nlrOF8` (WOSN, Ohio high school livestream, only this one viewed): produced multi-camera broadcast with a persistent scorebug. Other school-livestream channels (West Washington, USD 329, Dye Sporting Network, etc.) were not viewed.
- `6ajFxyTZkNw` (Juice Team 5v5 pickup): fixed wide camera but a persistent graphic scoreboard "BLUE VS RED" burned into the bottom of the frame.
- `kEQSSfgiB8U` (park game): single hoop only, low angle.
- `JIWieW7vgaU`: portrait-style phone video, watermark, tracking.
- `AwSA2T9s0rQ`, `jni7A5QNbMQ`, `70Gc6PWbcnI`, `r5EaYuS4ahQ`, `o-mt1pVyxeM`, `BaB-5NXNpFk`: handheld, POV or vlog-cut footage with a head-and-shoulders talking intro, watermarks or captions.
- `q_MD_3aONfA` (UAAP, Insta360): 360-degree equirectangular footage from a courtside seat; unusable without reprojection and the court is tiny.
- `EzWkghk-e4g`, `NdV927z4gZ8` (long school livestreams, truncated probe), `SG73ZiAlNcI` (Pivo), `CgX5vyY3MsQ`, `Jg4JTYYj8vY`, `E3mbJqgNlmI`: probe download failed (HTTP 403) or was truncated; **not viewed**, not accepted.
- Roundball BC `ultra-zoom` and Super League `...ultra-zoom cam view only` / the 4K two-camera edit `aEr8j7fPCYo`: zoomed or cutting between cameras; only the single wide-angle upload (`aH6PRcV4DHE`) was accepted.
- Everything NBA/NCAA/FISU/Euroleague/Olympic/TV-style rebroadcast surfaced by the queries: excluded on principle (broadcast or professional production).

Wikimedia Commons: dozens of hits for basketball. Viewed frames of `Boys Varsity Basketball v. Enosburg - January 15, 2026.webm` (Hardwick Community Television (HCTV), CC BY 4.0, 1080p, ~100 min; the series has ~25 files from the same producer, only this one was viewed): multi-camera produced broadcast with cuts and a "Live from Hazen Union" lower third, rejected. `Samsunspor-Merkezefendi Belediyesi Denizli Basket (26.12.20).webm` (CC BY 3.0, TBF): professional league broadcast with a scorebug, rejected. `Mad Ants VS Drive.webm` (G League, 480p handheld from the stands), `15 January Canberra Capitals game 2643.theora.ogv` (and the other Canberra Capitals clips, CC BY-SA 3.0, 720p, short, handheld pan from the stands, pro women's league), `ČBF 3x3 Tour 22.6. Ústí nad Labem.webm` (CC BY 3.0, 156 s, handheld GoPro): rejected. No other basketball videos longer than ~2 min with a suitable licence were found.

Internet Archive: ~3300 "basketball" movie items with CC licence URLs, but nearly all are NC/ND/PD-mark town-access-TV or school-broadcast recordings (`whs-*`, `snafuinfinitybasketball_*`, `Rotary_Basketball_*`, `cbb-*` Auburn film reels), which are produced multi-camera, NC/ND (not usable under our rules) or public-domain-mark rather than CC BY/BY-SA/CC0. Not downloaded.

### Pickleball (2 accepted from one channel)

Queries: pickleball full court doubles tripod; pickleball doubles game fixed camera; pickleball match whole court; pickleball rec play wide angle; pickleball gameplay full game 4.0; pickleball tournament match full court; pickleball4you doubles gold medal; pickleball4you mixed doubles.

- Accepted: pickleball4you tournament uploads (section 3.2). Not exhaustively reviewed: only 2 of the channel's ~60 CC uploads were pulled; older uploads (2013-2015 USAPA Nationals, 2022 Surrey 2022-07, 2024-2026 events) have not been viewed and may frame differently.
- Rejected: `QhLECLlXU3c` (Melbourne FL doubles): persistent score overlay. `v5BHuxV1imM`, `ChrAmYsue5A` and the rest of the Saigon "Craig vs Pickleball" and "Vernonchan Thirstday" series: download failed or not viewed (not evaluated). `DuNSRdQ4JQo` etc: paddle reviews.
- Wikimedia Commons: `Pickleball game.webm` (CC BY 3.0, Victor Jehovskiy, 1080p, 237 s): frames show handheld/panning footage that loses the court, rejected. Internet Archive: pickleball hits are city-council recordings and a "Pickleball Courts Open" local-TV item, nothing usable.

### Badminton (2 accepted, both limited)

Queries: badminton doubles game tripod; badminton match full court fixed camera; badminton singles match recording; badminton club game wide angle; badminton rally gameplay full match; badminton wide angle cam full match one camera; badminton tripod doubles match full 1080p; badminton fisheye lens.

- Accepted with caveats: section 3.3.
- Rejected: `bbLQ1Kmn-uU` ("Daily FV Sports Outdoor Badminton Night Match" series, Bangladesh; only this one viewed): dirt court with a camera that shifts, partial court, strong flood-light glare. `8jVoVJk-Co0` (Geneva friendly): persistent score overlay plus a subscribe pop-up graphic. `ppyuKsDmsnQ` (HeartFlow, Port Coquitlam, DJI Action 2 2K raw, 94 min): looked promising from the title, but the probe download failed (HTTP 403), so it was **not viewed** (worth a retry by a human or a later run). `ak94qTtkERw`, `8PIGTNmH3Vo`, `MhYNdXqIiU8`: downloaded/not viewed or download failed. Pro/federation broadcasts (BWF, Lee Chong Wei, Sudirman Cup, FISU) excluded as broadcast footage.
- Wikimedia Commons: the "Битва Корпораций (5-й сезон) - ... Бадминтон" corporate-league matches (CC BY 3.0, 1080p, 7-14 min, uploader savinkins): low floor-level camera at the net/umpire stand showing only one end of the court, partially handheld; rejected. Sports shows and China Open news clips: edited. Internet Archive: badminton items are NC/ND or 1940s-50s educational films.

### Volleyball (none)

Queries: volleyball game full court tripod; volleyball match fixed camera; beach volleyball match tripod; indoor volleyball game wide angle; volleyball rec league game; volleyball wide angle cam full game; volleyball gym tripod full match 1080p; volleyball elevated camera high school full match.

- `phUOYauhQYg` (Beechwood HS, elevated fixed camera, 1080p60): court cut off at the bottom, a net post in the right third, and black privacy rectangles burned into the lower-left; rejected. `kYkSb11VCVM` (Belmont HS): produced stream with persistent scorebug. `CEGzDGLEU74` (BrodesVolleyball week 1): camera framing changes within the video (different positions) and the channel's other uploads are POV-from-a-tall-player; rejected. `usQa5hHIDG0`, `NEcb7Sq6l4g`: low handheld phone. `cEj6vgLYJ4c` (Ukrainian park league): logo watermark and intermittent scoreboard overlay, outdoor, camera not fixed. `fM5TE5x4taA` (Martinique league playoffs): elevated but operator pans/zooms. `ePH7M5AzDac` (Pakistan village match): channel banner burned into the bottom third plus a logo, crowd occluding, rejected. `z7KZjsbYuTQ`: close handheld sand-court play. `oKhVlHfEagg` (Burj Nathuke open match, 3 h) and `645K3C7_23E`: probe failed / not viewed. `The Volleyball Guys` backyard series: titles indicate edited, produced content; not viewed.
- Wikimedia Commons: only a few short edited items (`Joe Norman of Team Freedom Highlights of NVA match`, `Max Jayzeh - Game Day`), rejected. Internet Archive: ~450 school/college volleyball items, nearly all NC/ND/PD-mark, plus `MatchPoint_470` (CC0, "match point") which was **not viewed**; not pursued because the broadcast-style town-TV items dominate.

Net result: **volleyball has no CC clip; use synthetic.**

## 5. Synthetic data (`samples/synthetic`)

Generated by `samples/synthetic` (`generate.py`), labelled synthetic; golden outputs are committed. Another agent owns the generator; this section is only a pointer. Synthetic clips are fully ours and are the CI fixtures and the safe source for committed evidence per D-7. Sports present in the tree: badminton, basketball, basketball_half, pickleball, volleyball.

## 6. How to use the box clips (path, never commit)

- Reference by absolute box path: `/workspace/wt/replay-env/samples-cc/<sport>_<slug>/<file>.mp4`. Copy nothing into the repo or the laptop; run tools on the box (`source /workspace/wt/replay-env/env.sh`, ffmpeg at `/workspace/wt/replay-env/bin/ffmpeg`).
- From a repo copy on the box, symlink rather than copy: `ln -sfn /workspace/wt/replay-env/samples-cc <your-copy>/samples/cc` (`samples/cc/` is in the repo `.gitignore`). Tests/scripts that need CC footage should read the path from an env var (for example `REPLAY_CC_DIR`, default `/workspace/wt/replay-env/samples-cc`) and `skip` if it is absent so CI without the box stays green.
- Committed evidence derived from a CC clip: write it under `docs/evidence/<milestone>/`, keep each file small, add the paste-ready attribution from the clip's `SOURCE.txt` next to it (README line or image caption) and say it was cut/cropped/annotated. Evidence derived from `samples/real` goes to `docs/evidence/local/<milestone>/` (gitignored) and is referenced by path only.
- Do not mix up the two pools in committed assets: samples/real = standard YouTube licence, never public; samples-cc = CC BY 3.0 with attribution.
- Re-fetching a clip: the URL and cut points are in each `SOURCE.txt`; yt-dlp is `/workspace/wt/replay-env/venvs/ytdlp/bin/yt-dlp -4 --js-runtimes node:/workspace/wt/replay-env/node/bin/node`. Re-check the `license` field before relying on a clip again (uploaders can change it).
