# Inspiration

Amateur game footage is a fixed wide shot from the sideline. Everyone is tiny, nobody is followed, and finding your own plays means scrubbing through the whole recording. Camera systems that fix this exist, but they need dedicated hardware or a coach-level budget. Most people who play pickup basketball, pickleball or volleyball have a phone and a tripod and nothing else.

The television is where people already watch together, and a Fire TV remote is a D-pad. That suggested a different kind of interface for sports video: instead of a scrubber and a pause button, the D-pad moves focus between the people inside the picture. Pause, arrow to a player, press Select, press play, and the video becomes a follow-cam on that person. That one interaction, spatial focus on people in a video, is the idea the project started from (REPLAY_PLAN.md, "Core novelty").

The second push came from our own demo footage. The official demo is a 2v2 pickup game filmed by one of us, with consenting adults. In a game like that the interesting moments are small: a rebound and a putback, a defender who stops guarding his man, a last basket that closes out the clip. A box score built from a phone video is only useful if it is honest about what the camera could and could not see, so we decided early that the app should say "can't tell" instead of guessing, label recreated views as recreated, and never present mock data as a result.

We also wanted to learn how much of a broadcast-style experience (score bug, replays, commentary, highlights) a single fixed phone camera can support, and what has to be approximated. Several of the answers are in the challenges file and the friction log.

TODO(team): add a personal sentence or two about why the team picked Fire TV and court sports. The repo does not record motivations beyond the plan.
