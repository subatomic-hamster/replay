"""Virtual replay angles (M8).

`replays` picks the highlights and writes the per-play manifests, `segment` cuts the
players out with SAM 2.1 (box prompts from the tracks), `tiera` renders the real-video
angles (wide / follow / tight crops), `tierb` the 2.5D angles: the court plate as a
textured floor and backdrop, player cutouts as upright billboards at their tracked court
positions, rendered from virtual cameras (orbit, push-in, broadcast high).
"""
