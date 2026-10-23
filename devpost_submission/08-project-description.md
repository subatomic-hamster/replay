# Project description

Replay is a Fire TV app and a phone web page that turn one phone video of a court-sports game into an explorable, broadcast-style replay.

## What it does

You film a game with a phone on a tripod. On the Fire TV you choose Add game and a sport, and the TV shows a QR code. The phone opens the linked page, uploads the video to S3, and lets you confirm where the court is (tap landmarks, or accept an automatic fit). Processing starts, and the game appears on the TV Home screen when it is ready.

On the TV you can:

- Play the game and pick any player with the D-pad; the picture follows that player.
- Use a court-line timeline and a Moments row to jump to plays.
- Watch an auto-cut highlight reel that ends on the best play (labelled "Last basket" for an automatic last make; a phone pick can override it).
- Cut between real-video camera angles and virtual angles. The virtual Free view is labelled "Recreated from the real players on a model of the court".
- Read a box score, shot chart and grounded commentary built from the game's own events, and correct calls in a Review queue.

On the phone you can clip a play, name players and set teams, set pickup scoring (1s and 2s), search plays in words, and send a play to the TV. "Clip that" can also be triggered by an X sign made to the camera or the spoken phrase "Replay, clip that".

Face matching and voice identification are opt-in: they apply only to enrolled, consenting profiles, store one averaged embedding each, and leave everyone else anonymous.

## How it works

The Fire TV app is React Native for TV (react-native-tvos) with shared TypeScript logic that also builds for the web so Playwright can test it. The API is FastAPI on one arm64 AWS Lambda with a Function URL. Games, job records and uploads live in a private S3 bucket (presigned multipart uploads). The two web apps are served by CloudFront. Secrets are in SSM Parameter Store. AWS CDK defines the stack.

A pull-based runner on a shared AMD GPU workstation (ROCm, PyTorch) claims processing jobs from the API with a worker key and runs a cached stage pipeline: ingest, court calibration, YOLO11 person detection with BoT-SORT tracking, identity and team assignment, pose, ball and rim events, plays, then highlights, replay angles and optional models (SAM 2.1, Whisper, Kokoro, SigLIP). It uploads results back to S3. The computer-vision library, `courtcam`, is MIT licensed. Research-licensed models are optional extras listed in docs/licenses.md.

## Current limits

The app has run on one Fire TV Stick model. Tracking fragments identities on long games, real shot recall is limited, and virtual views cover only some players. The Alexa skill backend is built but not connected to the TV app. The APK holds an API key and cannot be shared publicly.
