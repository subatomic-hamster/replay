# Replay: Devpost submission text

Amazon Developer Hackathon, Fire TV track (also entered in the AWS Builder and Open Source mini challenges, per the project plan). Deadline 2026-10-23.

## Pitch

Replay turns one phone on a tripod into a game you can watch on a Fire TV the way you would watch a broadcast. You film a rec-league game (basketball first), scan a QR code on the TV, upload from your phone, and a pipeline finds the players, fits the court, tracks everyone, and detects shots, makes and plays. On the TV you pick a player with the D-pad and the picture follows them, jump through a Moments row and a court-line timeline, watch an auto-cut highlight reel that ends on the best play of the game, cut between real-video and recreated virtual angles, read a box score built from the game's own events, and clip a play from your phone. The API and both web apps run on AWS (Lambda Function URL, S3, CloudFront). The GPU work runs on a shared AMD GPU workstation, because our AWS account has no GPU quota. The computer-vision core, `courtcam`, is MIT licensed.

## Files

| File                                                           | Devpost prompt                                                               |
| -------------------------------------------------------------- | ---------------------------------------------------------------------------- |
| [01-inspiration.md](01-inspiration.md)                         | Inspiration                                                                  |
| [02-what-it-does.md](02-what-it-does.md)                       | What it does                                                                 |
| [03-how-we-built-it.md](03-how-we-built-it.md)                 | How we built it                                                              |
| [04-challenges.md](04-challenges.md)                           | Challenges we ran into                                                       |
| [05-accomplishments.md](05-accomplishments.md)                 | Accomplishments we are proud of                                              |
| [06-what-we-learned.md](06-what-we-learned.md)                 | What we learned                                                              |
| [07-whats-next.md](07-whats-next.md)                           | What's next                                                                  |
| [08-project-description.md](08-project-description.md)         | Plain-text project description                                               |
| [09-product-feedback.md](09-product-feedback.md)               | Feedback on every tool, API and SDK used (AWS services in their own section) |
| [10-pre-hackathon-vs-window.md](10-pre-hackathon-vs-window.md) | Did the project exist before the hackathon?                                  |
| [11-feature-requests.md](11-feature-requests.md)               | Feature requests to platform and tool makers                                 |
| [12-friction-log.md](12-friction-log.md)                       | Friction log                                                                 |

## Before you paste anything

Search this folder for `TODO(team):`. Each one marks something the repo cannot answer (team bios, demo links, hackathon start date, a few outcomes). Do not submit with them in place.
