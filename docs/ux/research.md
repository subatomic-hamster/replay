# Replay UX research: Fire TV playback, sports apps, handoff, minimalism

Date: 2026-10-19. Method: web searches only (search snippets, not full-page reads). Tags: **[S]** = stated by a cited source; **[U]** = unverified (from general knowledge or a secondhand source; verify before building on it).

## Executive summary (top takeaways)

1. **Design for 1080p at 960x540 dp, 10-foot viewing.** Few elements, large, widely spaced, little text. [S: Amazon]
2. **Keep content inside a 5% safe zone: 48 dp left/right, 27 dp top/bottom** (96 px / 54 px at 1080p). Backgrounds and key art may bleed full-screen. [S: Android; Amazon doesn't state the number itself]
3. **Focus must be unmistakable.** Android's guidance: scale 1.1x plus a border and elevation, with the title readable on the focused card. [S]
4. **Map the real remote keys.** Back (KEYCODE_BACK) returns to the previous screen; Menu is a context menu; Rewind/Fast-Forward keys are `KEYCODE_MEDIA_REWIND` / `KEYCODE_MEDIA_FAST_FORWARD`; Home and the voice key cannot be intercepted. [S: Amazon remote-input doc]
5. **Pressing Up during playback to reveal smart features is already an established Fire TV pattern.** Prime Video's X-Ray opens when the viewer clicks Up on the Fire TV remote. [S: Cord Cutters, 2020 coverage]
6. **Timeline markers for key moments are table stakes.** YouTube chapters (on TV since May 2020) and "Most replayed" heatmap, and NBA "Smart rewind" with key plays marked. [S, but YouTube heatmap on TV apps is not confirmed]
7. **Catch-up reels should be short and capped.** Prime's Rapid Recap: up to 13 plays, at most about 2 minutes, skip/replay items, jump back to live at any time. [S]
8. **Offer multiple recap lengths.** The NBA app offers "All Possessions", "10-Minute Condensed", "Key Highlights". Maps directly to Replay's highlights, condensed game and rallies. [S]
9. **Trickplay thumbnails: generate them server-side at a fixed interval.** Jellyfin stores the interval in ms plus tile layout; the Jellyscrub plugin defaulted to 10 s at 320 px wide. Replay can afford a denser cadence (2-5 s) because games are short [design choice, U]. [S for Jellyfin]
10. **Camera/feed switching belongs in a side options panel, not on the scrub bar.** F1 TV and Apple TV's F1 screen offer a feed picker (onboards, tracker) chosen from an options panel during playback. [S, secondhand for F1 TV]
11. **QR screens: dark-on-light, high contrast, roughly 300x300 px on 1080p, short encoded URL, plus a printed short URL as fallback, kept on screen long enough.** [S: TV-advertising QR guides, not Netflix/YouTube]
12. **Async work must never block browsing.** Show progress as a badge or ring on the library card. No source verified here for Netflix/Google Photos specifics; the pattern is [U].
13. **Calm look:** light sans-serif text avoided; use light text on dark, simple sans-serif fonts, no lightweight weights. [S: Android]
14. **Motion restraint:** Apple's parallax is tied to a touch surface and layered art; a D-pad has no equivalent, so use scale and border instead. [S/U]
15. **Accessibility:** VoiceView and caption specifics were not verified; see section 6.

---

## 1. Platform guidelines

**Amazon Fire TV** ([design and UX guidelines](https://developer.amazon.com/docs/fire-tv/design-and-user-experience-guidelines.html))

- TV UIs are "10-ft UIs"; limit the number of elements and make them large and well spaced; minimize text. [S]
- Design for 1080p: 1920x1080 px, 320 dpi (xhdpi), 960x540 dp. [S]
- Overscan varies by manufacturer. The 5% figure comes from third-party summaries of Amazon/Google advice ([Smashing Magazine](https://smashingmagazine.com/2025/09/designing-tv-principles-patterns-practical-guidance/), [UX Collective](https://uxdesign.cc/guidelines-designing-for-television-experience-524f19ab6357)). Treat as [U] for Amazon, [S] for Android.

**Remote keys** ([Fire TV remote input](https://developer.amazon.com/docs/fire-tv/remote-input.html))

- Back = `KEYCODE_BACK`, previous screen/activity. Menu = `KEYCODE_MENU`, context menu. Rewind/FF = `KEYCODE_MEDIA_REWIND` / `KEYCODE_MEDIA_FAST_FORWARD`. Home and mic are system events, not interceptable. Return true from `onKeyDown` when handled. [S]
- Whether the physical Fire TV remote's rewind/FF buttons deliver those codes to apps must be tested on a device. [U]
- Media buttons for play/pause (`KEYCODE_MEDIA_PLAY_PAUSE`) exist on the Android standard; confirm on the target remote. [U]

**Android TV / Compose for TV**

- Layouts: 5% margin = 48 dp sides, 27 dp top/bottom; design at 960x540; do not clip backgrounds to the safe area; light text on dark; avoid light font weights ([Android TV layouts](https://developer.android.com/design/ui/tv/guides/styles/layouts), [Build TV layouts](https://developer.android.com/training/tv/playback/compose/layouts)). [S] The same page also mentions 58 dp / 28 dp elsewhere; use 48/27 as primary.
- Cards/focus: focused card scales 1.1x with a border and elevation; titles stay legible ([Immersive list](https://developer.android.com/design/ui/tv/guides/components/immersive-list)). [S]
- Immersive list: focused item swaps a 16:9 background image in a large viewport; subject placed top-right; list grows to reveal title and description. Use for featured content. [S]
- Minimum type sizes: not found. Common TV guidance is body about 24-28 sp equivalent at 1080p [U].

**Apple tvOS (contrast)**

- Focus = parallax tilt driven by the Siri Remote touch surface, with layered images; scrubbing is by horizontal touch pan with thumbnail previews; swipe down opens an info panel. Sources are third-party summaries ([skills summary](https://skills.cat/skills/ehmo/platform-design-skills/tvos-design-guidelines), [Brightcove tvOS controls](https://sdks.support.brightcove.com/tvos/playback/apple-tv-ui-controls-native-sdk-tvos.html), [Apple AVPlayerViewController](https://developer.apple.com/documentation/avkit/avplayerviewcontroller.md)). [S secondhand]
- Lesson: Apple relies on the system player's transport bar and info panel rather than custom chrome. Replay should likewise keep one consistent overlay.

## 2. Playback UX on TV

| App                       | Finding                                                                                                                                                                                                                                                                                                                                                                                                    | Status                                  |
| ------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------- |
| YouTube                   | Chapters on smart TVs/consoles since May 2020; "Most replayed" graph above progress bar, tap a peak to jump; preview thumbnail indicates most-replayed segment ([9to5Google](https://9to5google.com/2022/05/18/youtube-most-replayed/), [TechCrunch](https://techcrunch.com/2022/05/18/youtubes-player-gains-new-features-including-most-replayed-video-chapters-single-loop-and-more))                    | [S]; TV-app availability of heatmap [U] |
| YouTube                   | D-pad seek step 10 s, hold to accelerate                                                                                                                                                                                                                                                                                                                                                                   | [U]                                     |
| Netflix                   | Timeline is the main control; thumbnails while scrubbing; Skip Intro button appears after opening starts ([overview](https://macmyths.com/can-i-fast-forward-through-netflix-streaming/))                                                                                                                                                                                                                  | Low-quality source; treat as [U]        |
| Netflix                   | Controls auto-hide delay (commonly cited ~4-5 s), 10 s skip, Up/Down episode switcher                                                                                                                                                                                                                                                                                                                      | [U]                                     |
| Prime Video               | X-Ray opened by pressing Up on Fire TV remote; per-play replays with stats ([Cord Cutters](https://cordcuttersnews.com/amazon-is-bringing-hdr-key-plays-other-new-features-to-thursday-night-nfl-games/)); Key Plays bank builds as game progresses, available live or on demand ([TechCrunch](https://techcrunch.com/2023/08/24/amazon-prime-video-ai-features-thursday-night-football/))                 | [S]; current-season status [U]          |
| Plex/Jellyfin             | Jellyfin trickplay: interval stored in ms, thumbnail size and tile counts per record ([API](https://typescript-sdk.jellyfin.org/interfaces/generated-client.TrickplayInfo.html)); Jellyscrub BIF default 10 s, 320 px wide ([README](https://github.com/nicknsy/jellyscrub/blob/main/README.md)); keyframe-only generation changes real spacing ([forum](https://forum.jellyfin.org/t-trickplay-interval)) | [S]                                     |
| Plex BIF default interval | Not found                                                                                                                                                                                                                                                                                                                                                                                                  | [U]                                     |
| Kodi seek acceleration    | Not found                                                                                                                                                                                                                                                                                                                                                                                                  | [U]                                     |

Seek acceleration tiers were not verified in any source. A reasonable proposal, flagged as Replay's own design: tap = 10 s; hold steps 10 s -> 30 s -> 1 min -> 2 min per second of hold; thumbnails shown throughout; Enter commits, Back cancels to the original position. [U]
tvOS note: precise scrubbing with preview was limited to paused state in tvOS 9.2 beta ([9to5Mac](https://viptest.9to5mac.com/?p=420271)); likely outdated. [U]

## 3. Sports apps

- **NBA app / League Pass**: multiview up to 4 games; Smart rewind with key plays marked; recap options "All Possessions", "10-Minute Condensed", "Key Highlights" ([NBA press release](https://pr.nba.com/nba-app-launches-new-digital-features-highlighted-by-multiview-ahead-of-the-2024-25-season), [PhoneArena](https://www.phonearena.com/news/nba-league-pass-update-multiview-ai-features_id163805)). [S]
- **NFL Sunday Ticket on YouTube**: Key plays let a viewer catch up via short clips of each major play before joining live; multiview shows 2-4 games, with combinations chosen by YouTube ([YouTube blog](https://blog.youtube/news-and-events/latest-nfl-sunday-ticket-features/), [Awful Announcing](https://awfulannouncing.com/nfl/youtube-sunday-ticket-multiview-key-plays.html)). [S]
- **Prime TNF**: X-Ray (stats, Next Gen Stats, per-play), Rapid Recap (13 plays max, ~2 min), Key Plays ([About Amazon](https://www.aboutamazon.com/md/news/aws/prime-video-thursday-night-football-next-gen-stats-ai-features), [TV Technology](https://tvtechnology.com/news/for-the-first-time-prime-video-will-offer-1080p-hdr-coverage-of-thursday-night-football)). [S]
- **F1 TV / Apple TV F1**: choose among live feeds (22 onboards plus driver tracker on Apple TV) via a picker ([Apple support](https://support.apple.com/guide/tvapp/atvbd8b6f0ad/web)). [S] F1 TV's own device support and feed counts [U]. A forum report says the tracker can drift out of sync with video, so keep overlay data time-locked to the player clock.
- ESPN, DAZN, Peacock specifics: not researched. [U]
- Following a specific player: no verified TV example found. Replay's follow-player is a differentiator; model it on F1's "pick a driver, stay on that feed".

## 4. Async upload and processing UX

No source verified for YouTube Processing, Google Photos, iCloud or Netflix Downloads. Pattern knowledge, all [U]:

- Card-level state: dimmed art plus a progress ring or "Processing 42%" label; card remains browsable but not playable until minimally ready.
- Stage names over raw percent (Uploading, Analyzing, Ready); staged availability (play the raw video as soon as upload ends, smart features appear when ready).
- One non-modal toast on completion ("Game ready"), auto-dismiss; no blocking spinners.
- The phone, not the TV, hosts the upload progress; TV mirrors it on the card.

## 5. QR / phone handoff

Sources ([AdWave](https://adwave.com/resources/qr-codes-tv-advertising), [Delivr](https://delivr.com/faq/1550/top-10-best-practices-to-consider-when-designing-with-qr-codes), [MediaVillage](https://www.mediavillage.com/article/common-mistakes-tv-advertisers-make-when-implementing-qr-codes-for-television/amp/)): [S]

- Must be scannable from about 10 ft; about 300x300 px on 1920x1080 (the ad guide suggests lower-right; for a dedicated screen use a larger one, 400-500 px, a design choice [U]).
- Dark modules on light background; avoid inverted codes; keep encoded data short (short URL / redirect) so the code is less dense.
- Show a readable short URL (and a code) beneath as a manual fallback; leave it on screen long enough.
- Netflix/YouTube/Disney+ activation screens and Spotify Connect specifics were not found. [U]

## 6. Minimalist visual design and accessibility

- Verified: light text on dark, simple sans-serif, avoid light weights, backgrounds bleed full-screen, 16:9 key art, 1.1x focus scale plus border. [S: Android guides above]
- Not verified (all [U]): Netflix 2024+ and Fire TV 2023+ redesign details, specific type sizes (typical proposals: title 48-56 px, row labels 32-36 px, body/metadata min 28 px at 1080p), focus glow vs outline, Max/HBO specifics.
- Accessibility not verified from sources: Fire TV VoiceView (set `contentDescription`/focusable semantics), captions on/off in player, WCAG contrast 4.5:1 for text. Treat as checklist items to confirm with [Amazon accessibility docs](https://developer.amazon.com/docs/fire-tv/design-and-user-experience-guidelines.html) and a device test.

---

## Second pass: verified from full pages (supersedes [U] tags above where they conflict)

- **Controls auto-hide [S]:** Media3 `PlayerControlView.DEFAULT_SHOW_TIMEOUT_MS = 5_000` (5 s), progress updates min 200 ms ([source](https://raw.githubusercontent.com/androidx/media/release/libraries/ui/src/main/java/androidx/media3/ui/PlayerControlView.java)). Use 5 s as Replay's default; Netflix/YouTube exact values still [U]. Media3 seek increments use `C.DEFAULT_SEEK_BACK/FORWARD_INCREMENT_MS` (value not in the page read; commonly 5 s back / 15 s forward [U]). Time-bar scrubbing is off by default in Media3 (`time_bar_scrubbing_enabled=false`), so a custom seek UI is expected.
- **Hold-to-accelerate tiers, thumbnail cadence, YouTube/Netflix step sizes:** still [U]; Leanback `PlaybackTransportControlGlue` reference page was too long to read (use [PlaybackSeekDataProvider](https://developer.android.com/reference/androidx/leanback/widget/PlaybackSeekDataProvider) and AndroidX source to confirm). Treat the tiers in section 2 as Replay design.
- **Body text minimum [S]:** Amazon: body text at least 14 sp = about 28 px at 1080p; short text, generous line spacing; text and focused item fully inside the inner 90% of the UI; prefer less saturated colors and cool hues over red/orange ([Amazon guidelines](https://developer.amazon.com/docs/fire-tv/design-and-user-experience-guidelines.html)). This replaces my earlier 24-28 px guess: use 28 px minimum.
- **Focus [S]:** Amazon: the focused element must be clearly indicated, and selecting should momentarily show a selected state; Left from a content row returns to the nav menu; lists wrap at the ends (do not copy wrap for the timeline).
- **Android TV type [S]:** 15-style Material scale (Display/Headline/Title/Body/Label x large/small); Roboto default; sans-serif body, avoid decorative fonts ([typography](https://developer.android.com/design/ui/tv/guides/styles/typography)); numeric sp values are only in an image, see [M3 tokens](https://m3.material.io/styles/typography/type-scale-tokens).
- **Color on TV [S]:** no numeric contrast ratio given; test in Standard picture mode, sRGB for basic UI, 10-bit+ for gradients, avoid white backgrounds, do not rely on color alone ([Color on TV](https://developer.android.com/design/ui/tv/guides/foundations/color-on-tv)). Use WCAG 4.5:1 / 3:1 as Replay's own bar. So marker types need shape or label as well as color.
- **Accessibility [S, partial]:** Fire TV supports closed captions, Text Banner and VoiceView Navigation; developers can add Orientation Text, Usage Hints and Described By through the FireOS accessibility API; an app that does not work with remote, Alexa, VoiceView, captions and system settings misses the quality bar ([Amazon blog](https://developer.amazon.com/apps-and-games/blogs/2025/11/guide-to-accessibility-on-amazon-fire-devices), [living-room article](https://dev.to/amazonappdev/living-room-experience-and-accessibility-2ldd)). Formal submission requirements not found [U].
- **Device activation [S, secondhand]:** YouTube TV apps show a code (roughly 6-8 characters) to enter at youtube.com/activate, sometimes with a QR; signing in with the remote is an alternative. All from third-party guides, no official YouTube Help page confirmed. Netflix, Disney+, Google TV screens not found [U].
- **Background processing [S]:** YouTube Studio shows per-quality (SD/HD/4K) processing with hover for estimated time remaining since Dec 2022; a video can be published once SD finishes ([9to5Google](https://9to5google.com/2022/12/13/youtube-processing-time-estimate/), [Social Media Today](https://www.socialmediatoday.com/news/youtube-adds-video-processing-time-indicators-more-info-panels-for-data-st/638700)). Direct model for Replay: playable early, smart features arrive in tiers, with an estimate. Fire TV install-progress tiles, Google Photos, Netflix downloads: not found [U].

## Replay implications

| Takeaway                                    | Screen / flow     | Action                                                                                                                         |
| ------------------------------------------- | ----------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| Safe zone 48/27 dp, 960x540 dp base         | All screens       | Global layout wrapper with 96x54 px padding at 1080p; backgrounds full-bleed                                                   |
| 1.1x scale + border + readable title        | Home/library      | One focus style app-wide; no glow, no parallax                                                                                 |
| Immersive list pattern                      | Home/library      | Top row "Continue / latest game" with key-art-like frame (best frame from the game) behind the rails                           |
| Few elements, little text                   | Home, Settings    | Max 2-3 rails; Settings as a single short list                                                                                 |
| QR dark-on-light, big, short URL + code     | Add game          | White tile with QR at 400+ px, short URL and 4-6 char code below, one sentence of copy, auto-advance when the phone connects   |
| Async, non-blocking                         | Processing status | Progress ring + stage label on the game card; toast when ready; game playable as raw video while analyzing                     |
| Key moments markers                         | Player            | Colored tick marks on timeline per event type, heat-style density strip for rallies/scoring                                    |
| Remote key mapping                          | Player            | Left/Right seek, Rewind/FF keys seek, Play/Pause, Back hides overlay first then exits, Up opens panel                          |
| Seek acceleration + thumbnails              | Player            | Server-generated sprite sheet every 2-5 s (Jellyfin tile model); acceleration tiers per proposal in section 2                  |
| Up reveals smart features (X-Ray precedent) | Up panel          | Tabs: Follow player, Camera, Highlights, Rallies, Condensed, Stats, Search                                                     |
| Recap options with lengths                  | Up panel          | "Key highlights", "10-minute condensed", "All rallies" as labeled choices with durations; cap highlights reel like Rapid Recap |
| Feed/camera picker like F1                  | Up panel > Camera | List of angles (Original, Virtual, Free 3D) plus follow-player; remembers last choice                                          |
| Overlay data must sync to player clock      | Player, Stats     | Render stats/tracking from timestamps, not a separate clock                                                                    |
| Accessibility basics                        | All               | Captions n/a for most footage; label every focusable; 4.5:1 text contrast; verify on a Fire TV with VoiceView                  |

Open items to verify on-device: remote key codes, overlay auto-hide delay (start at 4 s, pause while Up panel is open), acceleration feel, minimum type sizes.
