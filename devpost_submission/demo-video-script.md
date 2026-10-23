REPLAY — Demo Video
Shooting script · target runtime 3:00 · draft 2 (technical detail added)
Format: Short narrative skit (IRL) intercut with app screen recordings
Cast: JOSEPH: hit the game-winner, wants to relive it.
SUBHAM: recorded the game, knows the app, drives the TV.
RAVI: the third friend; asks the questions the audience would ask.
Locations: Court (cold open) · PTN, the hangout spot with a Fire TV
Placeholders: “REPLAY” is the working app name; character names are swappable.
Production note: This script proposes the demo flow, not a verified feature inventory. Match controls and labels to the working app. Every generated view (Virtual replay, Free view, Player’s view) carries the honesty caption “Virtual view, recreated from the real footage (AI-generated)”; do not present it as footage from another camera. Commentary is replay audio, not the player’s thoughts.
Naming note: the skit calls the last basket “Joseph’s game-winner”. The app never says “Game winner”: its labels are “Best play” (star) and “Last basket”. Do not put “Game winner” in any ON SCREEN text that shows app UI.
Technical-detail note: dense specs go in lower-thirds (cheap on time). Spoken lines stay short. Do not add numbers or accuracy claims to captions; none are verified for the demo game beyond what is written here.
Script
0:00–0:12 | IRL | Ext. court — late game
The phone or camera recording sits courtside. Tie game, seconds left. JOSEPH gets the ball, takes one dribble, pulls up. Swish. Everyone yells. Freeze on JOSEPH mid-celebration.
Shoot this as the real game footage the app will process later (wide, fixed, courtside), so the cold open and the in-app clip match.
Optionally add a handheld close-up for energy.
ON SCREEN (small lower-third, last 4s): “One phone. One fixed angle. That’s the only camera.”
0:12–0:15 | CARD | Title card
Black screen, white text: 2 hours later.
0:15–0:35 | IRL | Int. PTN — evening
JOSEPH, SUBHAM and RAVI are on the couch with food and drinks. The TV is on, showing the Fire TV home screen. JOSEPH is still riding the high.
JOSEPH
Still can’t believe I hit that shot. Wish I could watch it again.
SUBHAM (not looking up from his phone)
Well… you can. I recorded the whole game.
RAVI
I’m not scrubbing through a whole game. Give me the highlights.
SUBHAM (grins, grabs the remote)
Funny you say that.
0:35–0:55 | IRL | Int. PTN — SUBHAM introduces REPLAY
SUBHAM talks us through it as he goes. Cut between the phone screen (over the shoulder or a phone screen recording) and the TV.
SUBHAM (on phone)
Meet REPLAY. Scan the TV’s QR code. It uploads straight to S3.
Insert: Pan to someone using the QR code on their phone, then switch to a screen recorded view of the actual phone picking the game video and uploading. Show genuine progress, then a visible “After processing” time jump to the ready game. Use a preprocessed copy of the same game for the remaining demo.
Insert: on the phone, SUBHAM taps the rim and the key corners on a frame of the game (the “Court markings” choice is visible in the upload page; it offers NBA, US college and US high school).
ON SCREEN (lower-third, over the upload): “Phone → direct-to-S3 multipart upload (resumable) · API: AWS Lambda behind a function URL · Web app: S3 + CloudFront”
ON SCREEN (lower-third, over the court taps): “Tapped landmarks → homography → court coordinates · NBA / NCAA / high-school markings”
SUBHAM (picks up the Fire TV remote)
A GPU worker does the rest. Then Fire TV. Native app. No casting.
Insert: the remote navigates from the Fire TV home screen to REPLAY. Hold on the app tile, launch, then reveal today’s ready game.
RAVI
Wait, it already cut the highlights?
SUBHAM
Already done.
ON SCREEN (lower-third, over the Fire TV launch): “Native React Native app (react-native-tvos), driven by the D-pad”
ON SCREEN: “Upload from your phone” → “Watch on Fire TV”
0:55–1:25 | SCREEN | Highlights · player · follow players
A clean Fire TV screen recording, full frame. Keep SUBHAM’s narration going as light VO, or use music only.
Highlights list (≈8s): the auto-generated highlight clips, with the game-winner as one of them. Scroll the list with the remote so it’s clear they’re all there and easy to get to, show the last highlight one more time. The last clip carries the app’s “★ Best play” tag.
Regular player (≈10s): open a clip and show the normal media controls: play/pause, scrub, skip forward/back. It should feel like any TV video player.
Follow players (≈12s): turn on player tracking. The view follows a selected player around the court. End on JOSEPH’s run-up to the game-winner.
SUBHAM (V.O.)
Every big play, clipped. Makes come from the ball at the rim; a hype score ranks them. Normal controls. And if you only care about one guy…
JOSEPH (V.O.)
Me. Obviously.
ON SCREEN (highlights list): “Shots and makes: the ball at the rim · Hype score: crowd audio + arms-up poses + speed bursts ranks the plays”
ON SCREEN (regular player): “Pickup scoring (1s & 2s) is a setting on the phone’s Names tab”
ON SCREEN (follow): “YOLO person + ball detection → multi-object tracking · teams from shirt colour (HSV bins), or from who guards whom in 2v2”
ON SCREEN (follow, as the view pans): “Follow mode: a virtual camera crops and pans after the tracked player”
ON SCREEN (optional, end of segment): “Bookmark a moment: X sign to the camera, or say “Replay, clip that” (Whisper ASR)”
ON SCREEN: Auto highlights · Follow any player
1:25–1:32 | IRL | Int. PTN
JOSEPH (leaning in, squinting)
Okay, but I wish I could see it from a better angle. You can’t even see my release.
SUBHAM just points the remote at the TV.
1:32–1:55 | SCREEN | A different, better angle
The game-winner plays from the original angle, then SUBHAM switches to a different/better angle of the same moment.
Show the switch happening live in the player, so it reads as a feature and not an edit.
Let the shot play out fully from the new angle, ideally slowed down at the release (the 0.5× slow-mo toggle in the angle view: playback at half speed).
RAVI (V.O.)
Wait, how did it get that angle?
SUBHAM (V.O.)
SAM cuts out the real players. We stand them on a model of the court.
JOSEPH (V.O.)
Look at that form. Textbook.
ON SCREEN (app badge, always visible): “Virtual replay · Recreated from the real players on a model of the court”
ON SCREEN (honesty caption, whole segment): “Virtual view, recreated from the real footage (AI-generated)”
ON SCREEN (lower-third, at the switch): “Angles cut at the same media time · Free view: orbit the scene with the D-pad”
ON SCREEN (lower-third, at the release): “Slow-mo: playback at 0.5×”
ON SCREEN (lower-third): “SAM 2.1 segmentation masks → player cutouts, placed at tracked court positions”
ON SCREEN: See it from a better angle

Insert: we move to one of joseph’s mistake clips
ON SCREEN (lower-third on the clip): “Lost his man — a defender drifts from his matchup while the offence has the ball”
1:55–2:02 | IRL | Int. PTN
RAVI (to JOSEPH)
What were you thinking?
JOSEPH
Honestly? No idea.
SUBHAM
Try your POV.
2:02–2:30 | SCREEN | POV cam + commentary
POV cam (≈14s): the play from JOSEPH’s point of view: defender closing out, the rim, the release.
Commentary (≈14s): turn commentary on and replay the shot with play-by-play audio. Let the commentary land the moment: hold on it.
SUBHAM (V.O.)
Player’s view: eye position and heading from his tracked pose. Play-by-play is written from the detected events, voiced by Kokoro, and ducked under the game audio.
RAVI (V.O.) (after the commentary hits)
Okay, that’s actually hard.
ON SCREEN (honesty caption, POV beat): “Virtual view, recreated from the real footage (AI-generated)”
ON SCREEN (lower-third, POV beat): “Player’s view: first-person virtual camera from the tracked player’s position and facing”
ON SCREEN (lower-third, commentary beat): “Commentary text is checked against the game’s events · Kokoro TTS · mixed under the game audio (ducked)”
ON SCREEN: Player POV · Replay commentary
2:30–2:50 | IRL | Int. PTN — sharing
JOSEPH
I need this. It’d be so cool if we could share it.
SUBHAM
Scan it.
Close-up on the TV showing REPLAY’s share screen with a QR code. JOSEPH holds up his phone and scans it. Insert: the highlight opens on his phone and plays. He’s already sending it to the group chat. RAVI’s phone buzzes.
RAVI (reading his phone, deadpan)
“Watch this from every angle.” …You’re never letting this go, are you.
JOSEPH
Never.
ON SCREEN (lower-third, on the QR): “QR → a short-lived link that opens the clip at that moment on your phone”
ON SCREEN (lower-third, as he sends it): “Sent with the phone’s native share sheet”
ON SCREEN: Scan to share
2:50–3:00 | CARD | End card
The game-winner plays one last time in slow motion, then the logo appears.
ON SCREEN (under the logo): “Replay · React Native on Fire TV · AWS Lambda + S3 + CloudFront · GPU worker · open-source CV core (MIT)”

Word count and runtime
(Spoken words only, speaker names and stage directions excluded. 150 words per minute = 2.5 words per second.)

| Segment                      | Window    | Type   | Spoken words | Speech time | Window length | Silent share                 |
| ---------------------------- | --------- | ------ | ------------ | ----------- | ------------- | ---------------------------- |
| Cold open                    | 0:00–0:12 | IRL    | 0            | 0s          | 12s           | 100%                         |
| Title card                   | 0:12–0:15 | CARD   | 0            | 0s          | 3s            | 100%                         |
| Couch                        | 0:15–0:35 | IRL    | 36           | 14.4s       | 20s           | 28%                          |
| Introduces REPLAY            | 0:35–0:55 | IRL    | 33           | 13.2s       | 20s           | 34% (inserts carry the rest) |
| Highlights / player / follow | 0:55–1:25 | SCREEN | 29           | 11.6s       | 30s           | 61%                          |
| Better angle ask             | 1:25–1:32 | IRL    | 18           | 7.2s        | 7s            | tight: see note              |
| Better angle                 | 1:32–1:55 | SCREEN | 27           | 10.8s       | 23s           | 53%                          |
| Mistake clip                 | 1:55–2:02 | IRL    | 10           | 4.0s        | 7s            | 43%                          |
| POV + commentary             | 2:02–2:30 | SCREEN | 30           | 12.0s       | 28s           | 57%                          |
| Sharing                      | 2:30–2:50 | IRL    | 27           | 10.8s       | 20s           | 46%                          |
| End card                     | 2:50–3:00 | CARD   | 0            | 0s          | 10s           | 100%                         |
| Total                        | 3:00      |        | 210          | 84.0s       | 180s          | 53% of runtime is silent     |

Estimated speaking time is 1:24 of 3:00 (210 words at 150 wpm). Windows add up to 3:00 exactly; no timecodes moved from draft 1.
Note on 1:25–1:32: JOSEPH’s line is unchanged from draft 1 and is about 0.2s over a 7s window at this pace. Deliver it quickly, or start the 1:32 screen recording 1s earlier (take the second from the 1:32–1:55 window, which has room).
