# Challenges we ran into

**Real footage is harder than synthetic.** We built a synthetic generator early so tests would be fast, and we labelled it synthetic everywhere. It stopped being a good guide quickly. On a real kit game (a CC BY Nottingham clip), D-97 found that the detector was not the bottleneck; the identity stage was. It capped live people at ten and three referees took three of those places, and red and dark kits fell into one team bin. Adding room for officials and a brightness channel to the kit colour moved player recall from 0.73 to 0.88 and team accuracy from 0.70 to 0.98 on hand-labelled frames. The same change made a clip where everyone wears dark tops slightly worse (right-person 64.1% to about 59%), which we accepted and recorded.

**The demo game.** D-98 covers the owner's own 2v2 game. The court labels we tapped came out mirrored against the image, teams with alike kits could not be told apart by colour (we now infer them from who guards whom), and X signs were missed when the player faced away. The fixes are tuned on that one video, which we say in the decision log.

**No Fire TV network we could trust.** The Stick was tested headless over USB adb. It sleeps with HDMI unplugged until a wake key is sent. Campus Wi-Fi intercepted HTTPS or quarantined the device behind a captive portal, and joining a network on Fire OS 7 meant driving the Settings screens with key events. Details are in the friction log.

**No GPU on AWS.** Our EC2 GPU quota was 0, so we split the system: serverless API and storage on AWS, GPU on a shared AMD workstation. That workstation has its own problems: a 16 GiB container memory limit that the `free` command does not show (a restart killed the runner on 2026-10-22), shared locks, ROCm quirks (MIOpen errors and hangs for some models), and an SSH path that dropped once.

**Lambda concurrency.** The account limit is 10. One open Watch screen made about nine parallel requests, so throttling was a demo risk. We reduced it in the clients (retry with backoff, at most four requests in flight, extras after the first frame) and filed a limit increase request; the outcome is not in the repo. TODO(team): note whether the increase was granted.

**Honest labelling.** Virtual views are recreated from cutouts of real players on a model of the court, so they cannot show what the camera never saw. We label them, and we skip views where a person is within 3.5 m of a fixed camera instead of showing a grey blob.

**A key in the APK.** The TV app talks to the API with a key baked in at build time, so the APK cannot be shared publicly.
