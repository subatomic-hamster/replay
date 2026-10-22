# Replay TV redesign (spec, not built yet)

Inputs: [research.md](research.md) (platform guidance and TV app patterns, tagged [S]/[U])
and the inventory of today's apps/tv (15 routes, a 15-item grouped watch menu, 9 feature
screens). Mockups: the "Replay TV redesign" design artifact.

## Brief

- **Subject:** your own game (rec league, school, pickup) played back on the living-room
  TV like a broadcast.
- **Audience:** players, parents and coaches on a couch, 2 to 4 m away, one hand on a Fire
  TV remote, often talking to each other.
- **Primary job:** find the moment and watch it again, from a better angle.
- **Feel:** a premium streaming app. Calm, minimal, no dashboards. Processing is invisible
  plumbing: it happens in the cloud while you browse, and the app tells you only what you
  can do next.

## Principles

1. **One player, not nine screens.** Everything about a game happens over its video: the
   timeline, the moments, following a player, angles, free view, stats. Today's separate
   Highlights, Rallies, Replays, Review and Search screens become layers of the player or
   ways to watch.
2. **The remote is the grammar.** Left/Right is time. Up is "do more with this moment".
   Down is "go somewhere else in the game". Select confirms. Back peels one layer. Nothing
   needs the menu button, and no feature is reachable only by a hidden key.
3. **Never block on processing.** A game is watchable as soon as its video is ready (the
   YouTube Studio pattern: SD first, the rest later [S]). Smart features light up as their
   stages finish; until then they show "Getting ready" with a time, not an error.
4. **Typing and fine edits go to the phone.** Clip trimming, tagging names, review answers
   and search queries are faster with a thumb. The TV offers "Edit on your phone" (a QR
   code, same pattern as upload) instead of an on-screen keyboard.
5. **Color comes from the footage.** The chrome is quiet and neutral; one accent marks
   game time and moments only.

## Information architecture

| Today (15 routes)                                    | Redesign                                     |
| ---------------------------------------------------- | -------------------------------------------- |
| library, players, profile, settings, pair, add       | **Home** (rows), **Add game**, **Settings**  |
| watch, replays, replay (+ Free view), highlights,    | **Player** with layers: transport, Moments   |
| rallies (+ condensed), review (stats), search, clips | (Down), Do more (Up), Stats panel, Angles,   |
|                                                      | Free view                                    |
| advice, profile tabs                                 | **Player profile** (from Home's Players row) |
| clips trimmer, tagging, review answers, search text  | **Phone** (QR handoff from the player)       |
| pair (4-digit companion code)                        | removed: the QR handoff replaces it          |

Ways to watch a game (NBA app pattern [S]): **Full game**, **Highlights** (top plays,
short, capped like Prime's Rapid Recap [S]) and **Condensed** (dead time cut; rallies for
volleyball and pickleball). Chosen on the game's hero, switchable from Up.

## Remote mapping

| Key                   | Home                   | Player, nothing open                   | Player, a layer open              |
| --------------------- | ---------------------- | -------------------------------------- | --------------------------------- |
| Left / Right          | move focus             | seek 10 s; hold accelerates            | move within the layer             |
| Up                    | move focus; top = gear | open Do more                           | move between rows / close Moments |
| Down                  | move focus             | open Moments                           | move between rows                 |
| Select                | open                   | play / pause (shows transport)         | choose                            |
| Play/Pause            | play the focused game  | play / pause                           | play / pause                      |
| Rewind / Fast-forward | none                   | scrub at 2×, 4×, 8×, 16× (press again) | none                              |
| Back                  | exit (system)          | to Home                                | close the layer                   |
| Menu                  | none                   | open Do more (alias of Up)             | none                              |

Seek: a tap moves 10 s. Holding steps 10 s, then 30 s after 1 s held, then 1 min after
3 s, then 2 min (Replay's own curve; the YouTube and Netflix numbers are unverified [U]).
While seeking, playback pauses and a preview frame rides above the playhead. Release
resumes from the new point. Each step goes to the next stop: a grid at the current step
(0:40, 0:50, …) plus every moment's start, where the preview shows and names the moment.
Transport hides after 5 s (Media3 `DEFAULT_SHOW_TIMEOUT_MS` [S]).

## Tokens

### Color (dark, cool, low saturation per Amazon's guidance [S])

| Name       | Hex       | Use                                                                            |
| ---------- | --------- | ------------------------------------------------------------------------------ |
| Floor      | `#121A23` | background                                                                     |
| Bench      | `#1D2834` | raised surfaces: panels, unfocused cards                                       |
| Line       | `#3A4856` | inactive track, hairlines, empty progress                                      |
| Chalk      | `#ECEFF2` | primary text, focus ring, focused chip fill                                    |
| Bleacher   | `#9DAAB7` | secondary text (7:1 on Floor)                                                  |
| Scoreboard | `#F0B44C` | game time only: playhead, played track, moment notches, progress of processing |

Two meanings, never mixed: **white is "selected"**, **amber is "in the game"**. Errors
use plain Chalk text with an icon; no red banners. Team colors from `players.color_hex`
appear only in player chips.

### Type

**Barlow** (OFL), designed from California highway signs to be read at a distance and
speed, which is the 10-foot problem. One family, two widths:

| Style   | Face                  | Size / weight           | Use                             |
| ------- | --------------------- | ----------------------- | ------------------------------- |
| Display | Barlow                | 64 / 600                | game title on the hero          |
| Title   | Barlow                | 40 / 600                | panel and row titles            |
| Body    | Barlow                | 30 / 500                | descriptions, menu items        |
| Meta    | Barlow                | 26 / 500                | dates, durations, hints         |
| Figures | Barlow Semi Condensed | 30 to 96 / 600, tabular | timecode, scores, speed readout |

Amazon's floor is 14 sp body, about 28 px at 1080p [S]; 26 px meta stays above today's
24 px test floor. Sentence case everywhere; no all-caps labels; no light weights.

### Layout and shape

- Canvas 1920×1080, 8 px grid. Safe zone 96 px left/right, 54 px top/bottom; video and
  key art bleed to the edge [S].
- Radius: 12 px cards and panels, full-round chips. One shadow only, on the focused card.
- Focus: scale 1.06 plus a 4 px Chalk ring with a 4 px gap, 150 ms ease-out. No glow, no
  color change on unfocused items.
- Motion: only in answer to a key press. Transport fades in 150 ms and out 300 ms; layers
  slide 24 px. No idle animation except the progress ring of a processing game.

### The one bold thing: the timeline as a court line

A 6 px line across the bottom safe edge, Line-gray ahead of the playhead and Scoreboard
behind it. Moments are notches cut like court hash marks: 4 px wide, 20 px tall for scores
and kills, 12 px for other plays, a small diamond for your bookmarks, so the type reads
without color [S]. While seeking, a scoreboard readout (`×8`, `+2:00`) in Barlow Semi
Condensed sits beside a 400 px preview frame. Everything else stays quiet.

## Screens

### Home

```
┌────────────────────────────────────────────────────────────────── ⚙ ─┐
│  [hero: best-moment frame of the focused game, bleeds right/top]      │
│  Saturday pickup                                                      │
│  Basketball, Oct 18, 41 min, 12 moments                               │
│  ( Play )  ( Highlights 4 min )  ( Condensed 18 min )                 │
│                                                                       │
│  Games                                                                │
│  [ + Add game ] [■ processing 62%] [ game ] [ game ] [ game ] …        │
│  Players                                                              │
│  ( avatar ) ( avatar ) ( avatar ) …                                   │
└───────────────────────────────────────────────────────────────────────┘
```

- Immersive list [S]: focusing a card swaps the hero art (that game's top moment frame) and
  text. The hero's buttons are the ways to watch; Play resumes where you left off.
- A processing game sits first in Games with its own first frame, dimmed, and a thin
  Scoreboard ring with plain words under the title: "Finding players, about 6 min". When
  the video is watchable the ring stays but Play works.
- Empty library: the hero becomes "Add your first game" with the Add game action focused.
- Settings is a gear at the top-right, reached with Up. Back exits the app.

### Add game

Two beats on one screen. First a row of sport tiles (icon plus name). Then:

```
┌───────────────────────────────────────────────────────────────────────┐
│   ┌─────────────┐   Scan with your phone's camera                      │
│   │   QR 400px  │   It opens a page to pick the video and upload it.   │
│   │  dark on    │   replay.tv/u/k3f9  (short link, no token shown)     │
│   │  white card │                                                     │
│   └─────────────┘   Waiting for your phone…                            │
│                     You can go back to Home. The game appears there    │
│                     and plays as soon as it's ready.                   │
└───────────────────────────────────────────────────────────────────────┘
```

QR as dark modules on a white card with a 4-module quiet zone, about 400 px [S: QR guides
say about 300 px at 1080p; larger is safer from a couch]. The status line follows the
phone: waiting, uploading 43%, uploaded, then "Processing. It's on Home." Back to Home at
any point; nothing is lost.

### Player

Layers stack over full-bleed video; Back removes the top one.

**Transport (any key):** top-left the game title in Meta, bottom the court-line timeline,
left the elapsed time and right the remaining time in Figures. When following a player,
their chip sits top-left instead of the title.

**Moments (Down):** a row of moment cards above the timeline, cued to the nearest moment.
Each card: the frame at the moment, "0:42", and what happened ("Three-pointer, #23
Maya"). Left/Right walks them, and the timeline playhead follows; Select jumps there and
closes the row. A chip row above filters: All, Scores, a player's plays.

**Do more (Up):** one row of large actions over a soft scrim. Only actions that exist for
this game and this moment appear:

| Action        | What it does                                                                | Today                                    |
| ------------- | --------------------------------------------------------------------------- | ---------------------------------------- |
| Follow player | row of player chips; pick one and the camera follows them                   | select mode                              |
| Angles        | thumbnails of this moment's replay angles; Left/Right cuts between them     | Replays                                  |
| Free view     | orbit the moment in 3D; Left/Right orbits, Up/Down height, Back exits       | Free view                                |
| Watch         | Full game, Highlights, Condensed                                            | Highlights, Rallies                      |
| Stats         | right-side panel like Prime's X-Ray [S]: score, players on court, box score | Review                                   |
| Commentary    | on/off                                                                      | Broadcast                                |
| On your phone | QR to clip, share, tag names, answer review questions, search               | Clips, Search, Review questions, tagging |

**Seeking:** as above: preview frame, `×4` readout, moment snap. Rew/FF give the same
preview at fixed speeds.

**Processing still running:** the actions that depend on unfinished stages show "Getting
ready, about 3 min" and cannot be chosen; the rest work.

### Player profile

Reached from Players on Home. Hero is the player's best moment; a row of their games and a
"Career reel" action. Stats in a single quiet table. Card rendering and profile links move
to the phone.

### Settings

A short list: Server address, API key, Test connection. Address and key are entered on the
phone through a QR handoff by default; the on-screen keyboard stays as a fallback.

## What the backend needs (later)

- **Seek previews:** a worker stage writing a storyboard sprite (one 320 px frame every
  2 s, tiled; Jellyfin-style trickplay [S]) plus its manifest in the game folder.
- **Moment thumbnails and labels:** one frame per event at `t_key`, and a plain-language
  label ("Three-pointer, #23 Maya") from events, players and the sport profile.
- **Tiered readiness:** a game flag `watchable` once ingest and the wide rendition exist;
  per-feature readiness derived from stages; a time estimate per remaining stage.
- **Hero art:** the top hype moment's frame per game (`thumb_url` today is the first frame).
- **Resumable phone upload:** the mockup promises that a dropped connection picks up where
  it left off. Today a failed multipart upload restarts; keep the `upload_id` and
  finished part ETags in the page's storage and add a "list parts" route so it can resume.
- **Phone handoff routes:** the phone page grows Clip, Tag, Review, Search tabs behind the
  same per-game token.
- **Faster processing:** the brief wants processing done quickly in the cloud. hfbox stays
  the default (free). A per-job AWS GPU (spot) is the option to price later against the
  remaining credit; nothing in the UI depends on where the GPU is.

## Migration notes

- The e2e specs pin testIDs and `data-*` attributes, the 24 px text floor (TV-08/09/17),
  TV-14's menu geometry and TV-18's QR runs. The redesign replaces TV-02/05/06/07/09/10/12/14
  wholesale; keep the testID vocabulary where a concept survives (video, timeline, focus).
- Tokens move into `theme.ts` (adding spacing and radius tokens); Barlow ships as an asset
  font on native and via `@font-face` on web.
- Focus stays app-state (not native focus); the input stack already supports layers.
