# What it does

Replay takes one phone recording of a court-sports game and turns it into something you can explore on a Fire TV. Basketball is the main sport. Volleyball, pickleball and badminton work through sport profiles with fewer features proven.

**Add a game.** On the TV, choose Add game and a sport. The TV shows a QR code. The phone opens a web page (no phone app to install), uploads the video straight to S3 in parts, lets you tap the court's landmarks or accept an automatic fit, and starts processing. The TV moves on to the game when it is ready.

**Watch.**

- Follow player: pick someone on the video with the arrow keys and the camera follows them. Back stops following.
- A timeline drawn as a court line, with notches for moments, and a Moments row with thumbnails and a Scores filter.
- Highlights: an auto-cut reel that ends on the best play. The last automatic make is labelled "Last basket" and tagged "Best play"; we cannot know whether a basket won a pickup game, so the app never says "Game winner". A star on the scrubber marks it. A phone pick overrides it.
- Replay angles: real-video cameras, plus virtual angles. The virtual "Free view" is labelled "Recreated from the real players on a model of the court". It shows cutouts of the real players' pixels placed on the court plane, not a true 3D capture.
- Player's view: a first-person-style cut for a play, built from the tracks.
- Stats: a box score and shot chart from the game's own events, with a Review queue where you correct what the pipeline got wrong. Pickup scoring (1s and 2s) is a phone setting.
- Grounded commentary captions: templated text checked against the game's events, with optional TTS narration.

**On your phone.** Clip a play, tag and name players, review calls, search plays in words, set teams and scoring, and send "Watch it" to the TV.

**Clip that.** Taps work. An X sign made facing the camera and the spoken phrase "Replay, clip that" are also detected as triggers. On the demo game, 5 of 5 X signs were found with no false ones; those thresholds were tuned on that one video.

**Voice with Alexa.** A backend for an Alexa custom skill exists (signed requests, TV pairing codes, a command queue). It is not wired into the TV app yet, so it is not part of the demo.

**Privacy.** Face matching and voice identification apply only to enrolled, consenting profiles, and store one averaged embedding per profile, not photos or audio. Everyone else stays anonymous.

**Limits we state in the app and here.** Tracking still fragments identities on long games. Real shot recall was low on some real clips. Virtual views show only some of the players. Details are in the challenges file.
