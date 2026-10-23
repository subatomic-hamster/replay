# What's next

These are our own plans and known gaps, drawn from HANDOFF.md section 9, docs/demo-readiness.md and the decision log. They are not commitments.

**Accuracy on real games.**

- Identity still fragments into many ids on long games, and both teams can get the same label.
- Real shot recall is low on some clips. There is no basketball block detector (D-96): the signals we have cannot tell a block from a contested shot.
- Dead-ball shots are counted until we have a general rule to drop them.
- Players in alike outfits remain a weak case (D-97).

**Virtual replays.**

- Virtual views show only some of the players and are limited to what the one camera saw. We want better texture and coverage, and an honest comparison against a real second camera.
- Tier D research (Gaussian splats, generative views) is experimental only (docs/tier-d.md).

**Fire TV.**

- Verify hold-to-seek and the key repeat with a physical remote.
- Find out why the app does not appear in Your Apps & Channels or the App Library (cause unknown); today it starts with `am start`.
- Move to a signed release with a per-user sign-in instead of a key in the APK. This is needed before the app can be shared outside the team.
- Test on more devices than one Stick.
- Reduce the main-thread frames seen when a game opens (two of about 800 ms).

**Alexa.** The backend for "Alexa, ask replay court to clip that" exists. The TV app still needs to send its state heartbeat and poll the command queue. TODO(team): say whether the skill was ever created in the Alexa developer console.

**Cloud.**

- Run the GPU stages on AWS once a GPU quota exists, using the Step Functions and SageMaker skeleton already in `infra/` (it is in the CDK app but not deployed).
- More than one runner, and WebSocket-free pairing for more than the QR flow.

**Product.**

- More sports on the same profile mechanism, with real-footage acceptance for each.
- A native Fire TV renderer for the Free view, so it uses hardware decode and GL on the Stick (a native GL view exists; it is not device-verified).
- Name and team editing on the TV itself; the TV keyboard has no name presets, so names are set on the phone.

**Open source.** `courtcam` is the MIT piece, split out with `scripts/split-courtcam.sh` (D-36). TODO(team): confirm whether it has been published and add the link.
