# map-on-video

Turn a drive from A to B into a short narrated **route-briefing video**, something like Google Maps as a video.
You give it two places and get an MP4 that plays offline on any phone or player.

- **Overview** of the whole trip, with a title card and a spoken summary (miles, driving time, number of key turns).
- **The camera holds still while each line is spoken, then flies to the next view in the pause.**
  Flights use the van Wijk & Nuij smooth zoom-and-pan curve (the same curve as MapLibre's `flyTo`).
- **Street-level close-ups at every key turn.** The map is rotated so the direction of travel points up,
  tilted 40°, with 3D buildings and a big instruction card that's readable on a phone.
- **A red route line and a blue position dot** that sit on the road to the pixel, even in tilted views and
  during camera flights.
- **Narration** from a local Kokoro voice. The timestamps of each spoken sentence set the pacing.
- **Extras:** "Now entering <State>" chips at borders; a bottom strip with miles done and left, time left and
  the next turn; a progress bar; soft subtitles; and a chapter for each line.

| Test route | Distance | Video | Size | Render time (2 CPU cores, no GPU) |
| --- | --- | --- | --- | --- |
| New York City Hall → Hollywood & Vine | 2,800 mi | 3:43 | 46 MB | 4.5 min |
| Potomac Mills, VA → Wise, VA | 379 mi | 3:02 | 34 MB | 3 min |

It's a **preview, not navigation**. The routing comes from the free OSRM demo server and can differ from what Google picks.

## Quick start

```bash
# system packages: native MapLibre needs a virtual display and libOpenGL
sudo apt-get install -y xvfb libopengl0 ffmpeg nodejs npm
pip install -r requirements.txt

# 1. plan: prints the route, key turns, border crossings and the spoken script (nothing drawn)
python3 routevid3.py --from "Potomac Mills, Woodbridge VA" --to "Wise, Wise County, Virginia" \
  --from-label "Potomac Mills" --to-label "Wise, Virginia" --contact you@example.com \
  --narrate voices/kokoro-v1 --work wise --plan-only

# 2. stills: prints the shot table (hold / fly, start–end) and saves a few frames as JPGs
python3 routevid3.py --work wise --stills 2,12,20,45

# 3. render (faster than real time; run long trips in the background)
python3 routevid3.py --work wise --out briefing.mp4
```

The first run saves the trip's settings in `<work>/args.json`, so steps 2 and 3 need only `--work` and can't
render a different route from the one you reviewed. Pass an option again to change it (the script says so).

On first run the script installs `@maplibre/maplibre-gl-native@6.4.1` (pinned: the version in the measurements)
into its cache folder (`~/.cache/routevid`) and calls `xvfb-run` itself.

**The voice:** download Kokoro v1.0 from Hugging Face `onnx-community/Kokoro-82M-v1.0-ONNX`. Put
`onnx/model.onnx`, `tokenizer.json` and `voices/af_heart.bin` in one folder, and pass that folder with `--narrate`.
Leave out `--narrate` for a silent video with estimated pacing.

**Options:** `--voice am_michael`, `--max-turns N`, `--turns-json file` (hand-fix the turn list),
`--style <MapLibre style URL>`, `--crf 24`, `--maxrate 3M` (bitrate cap; flights over cities cost the most).

**Check the narration:** `tools/check_audio.py` runs speech recognition over `narration.wav` and flags lines
that don't match the script. It needs `sherpa-onnx-zipformer-small-en-2023-06-26` from the sherpa-onnx `asr-models`
release. A narrated render writes `<work>/plan_check.json` for it, so just run
`python3 tools/check_audio.py <work>/plan_check.json --asr-dir <model folder>`.

## Review the turn list

Wrong or missing turns are the worst failure, so look at the `--plan-only` output before rendering. To override,
pass `--turns-json` with `[{"steps": [i, ...], "title": "...", "text": "..."}]`. The first entry is START and the
last is DESTINATION; step numbers come from the OSRM step list.

## Map data rules

- **Never use `tile.openstreetmap.org`.** The OSM Foundation's tile servers forbid any pre-emptive fetching,
  and a video renderer does exactly that. OSM *data* is free; their *tile servers* are not for this.
- **Maps: [OpenFreeMap](https://openfreemap.org)** vector tiles (styles liberty, bright, positron). They're free,
  need no key, and allow commercial and video use with the credit
  "OpenFreeMap © OpenMapTiles Data from OpenStreetMap", which appears on every frame. Every tile, font and
  sprite is cached on disk, so re-renders fetch nothing.
- **Routing:** OSRM demo server. **Place lookup:** Nominatim, 1 request per second, with your contact in
  the User-Agent. Both are meant for light use, and results are cached.
- **For a real product:** use MapTiler, Stadia or Mapbox with a key, or self-host Protomaps PMTiles and
  Valhalla. Never commit an API key.

## How it renders

1. **Plan.** Geocode the two places, get the route, pick the key turns, find state borders (Natural Earth), and
   write one spoken line per turn and per travel leg.
2. **Narrate.** `tools/narrate.py` voices each line. Its exact timestamps decide how long each line's view is held, and
   every pause is stretched to fit the camera flight that follows it.
3. **Cameras.** Each line gets one camera: the whole route (intro and outro), a north-up view fitted to a travel
   leg, or a tilted close-up at a turn. Cameras are computed in Python (Web Mercator), because native MapLibre
   has no `project()` or `cameraForBounds`.
4. **One map worker.** Native MapLibre runs in Node under `xvfb-run`. It reads JSON commands on stdin and writes raw
   1920×1080 frames on stdout: about 50 ms per frame in the countryside and 200 ms over Manhattan.
5. **Held views use an ID-image trick.** Each hold makes three renders: the map without the route, the map with
   the full route, and a hidden "ID image" whose route colours encode miles along the trip
   (R = i % 256, G = i / 256, B = 255). NumPy then reveals the red line up to the dot's mile and places the dot
   and turn markers at the matching pixels. That's pixel-accurate even under tilt, and costs about 10 ms per frame,
   because only the route's bounding box is recomposited.
6. **Flights render live.** The red line is filtered to the boundary mile with `setFilter`, and the blue dot is a
   MapLibre circle layer at that mile, so it stays on the road while the camera moves. 3D buildings are hidden
   during flights, then fade in when the camera settles. Big rotations get longer flights (at most about
   135° a second), so a U-turn reads as a turn rather than a spin.
7. **Encode.** ffmpeg (H.264 `-tune animation`, bitrate capped), plus AAC narration, soft subtitles and chapters.

More detail: [docs/RESULTS.md](docs/RESULTS.md) (version history and measurements) and the two AI-review handouts in [docs/](docs/).

## Layout

```
routevid3.py          the tool (one file)
tools/narrate.py      local TTS (Kokoro / sherpa-onnx) -> narration.wav + exact sentence timestamps
tools/check_audio.py  speech-recognition check of the narration against the script
docs/                 AI-review handouts and measured results
```

## License

MIT. Map data © OpenStreetMap contributors (ODbL), tiles by OpenFreeMap / OpenMapTiles, borders from Natural Earth (public domain).
