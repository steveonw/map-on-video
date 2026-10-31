# Map Rendering Handout: Faster Ways to Draw Route Videos

Oct 30, 2026 · steveonw

## How to use this handout

Paste the whole page into each AI in a fresh chat with the prompt below, and collect the answers in the grid at the end. This handout is only about **how the maps get drawn**. The product questions were covered in the first handout.

```
I'm building a tool that turns a driving route into a short narrated video. The hard part is drawing the maps: the current method runs a full map engine (MapLibre GL) inside a headless browser, and it is slow without a graphics card. Below is a handout with the limits, what exists today, measured numbers, and candidate alternatives. Please answer the numbered questions using the template at the end. Be concrete: name libraries, file formats and techniques, say what you would try first, and estimate render times where you can. If you are unsure a library exists or does what you say, say so. Hybrids (mixing two methods) are especially welcome.

[paste the handout here]
```

If an answer is vague, follow up with: "Sketch the code structure for your first choice, and tell me the one thing most likely to go wrong."

## The problem

We need to draw map imagery for a 1080p, 24 fps, 2–4 minute video of a drive. The map has to match a route line exactly, at every zoom from a whole country down to one street corner, on a machine with no graphics card.

**What has to appear on screen**

- An overview of the whole trip (up to 2,800 miles, e.g. New York to Los Angeles).
- Regional views along the route while a red line draws across them.
- Street-level close-ups at each key turn, rotated so travel points up, tilted about 40°, ideally with 3D buildings.
- A route line and a moving dot that sit exactly on the roads in every view.
- Readable labels on a phone screen.

**Hard limits**

| Limit | Detail |
| --- | --- |
| Hardware | 2 CPU cores, about 7 GB RAM, no GPU. WebGL runs in software (SwiftShader). |
| Time | A render should finish in under about 10 minutes; one command is capped at 10 minutes, and longer jobs must run in the background. |
| Network | Package registries (pip, npm), GitHub, Hugging Face and a few map services are reachable; most other sites are blocked. |
| Map data rules | **No** tiles from tile.openstreetmap.org: its policy bans any pre-fetching. Allowed now: OpenFreeMap vector tiles (OpenMapTiles schema, free, commercial and video use allowed with the credit "OpenFreeMap © OpenMapTiles Data from OpenStreetMap"). Possible later: MapTiler or Stadia with a key, or self-hosted Protomaps PMTiles. |
| Software already present | Python 3 with Pillow, NumPy and GeoPandas; Node with Playwright and Chromium; ffmpeg. Anything on pip or npm can be added. |
| Routing | OSRM demo server: the route as about 2,000–35,000 points, plus turn-by-turn steps. |

## How it works today (version 2)

Today's tool draws 15–25 still maps with MapLibre in a headless browser, then animates over them in Python. A 3-minute narrated video takes about 4 minutes and comes out at 16–24 MB.

1. **Route and script:** look up both places (Nominatim), get the route (OSRM), pick the key turns, find state lines, and write one spoken line per turn and per travel leg.
2. **Narration:** a local text-to-speech voice (Kokoro) speaks each line. Its timestamps set how long each part of the video lasts.
3. **Maps (the slow part):** headless Chromium runs MapLibre GL JS with OpenFreeMap's style. It draws an overview, about 1 regional sheet per 130 miles (capped at 14), and one close-up per turn: rotated so travel points up, tilted 40°, with 3D buildings. That's about 5 s per still at 1280×720 × 1.5 pixel ratio. For each still it also records where every route point lands in pixels.
4. **Animation (fast):** Python and Pillow copy the right still for each frame and draw the red line, the dotted road ahead, the moving dot, the instruction card and the bottom strip. That runs at about 30 frames per second.
5. **Output:** ffmpeg encodes H.264 at 24 fps with the narration, soft subtitles and a chapter for every turn and leg.

The camera never moves within a view: changes between views are 0.5-second cross-fades. That keeps rendering fast and files small, but it is the main limit this handout is about.

## What today's approach cannot do

Drawing a few still maps works and is fast, but it gives up the camera. Each view is a fixed photograph, so these are out of reach today:

1. **Smooth camera moves.** There's no continuous zoom from the overview down to a street corner, no panning along the road, and no gradual rotation into the travel direction. Changing views is a cross-fade between two stills.
2. **Live-drawn frames.** Drawing every frame with MapLibre was measured at about 1.9–2.8 seconds per frame at 1280×720. A 3-minute video would take 2–3 hours.
3. **Labels that react to the camera.** Labels are baked into each still, so they can't stay upright or resize during a move.
4. **Map styling that follows the story.** Fading the map out away from the route, or adding the old-paper look, means changing the map style, then redrawing and re-checking every still.
5. **Independence from a browser.** The pipeline needs Chromium, the MapLibre library with a small page script, and a workaround for MapLibre's automatic framing, which zooms out far too much when the map is tilted or rotated.

## Candidate approaches, with what we measured

While writing this handout we tested two alternatives. One of them changes the picture: **native MapLibre, run without a browser under a virtual display, drew full map frames in about 40–80 ms**, roughly 40× faster than the browser version. That makes real camera moves affordable. All tests: 1920×1080, OpenFreeMap "liberty" style, 2 CPU cores, no GPU, around Gordonsville, VA.

| Approach | How it works | Measured here | What it gets right | Open problems |
| --- | --- | --- | --- | --- |
| Today: MapLibre GL JS in headless Chromium | The browser map engine, software WebGL (SwiftShader), screenshots | About 5 s per still; 1.9–2.8 s per live frame | Full map style, labels, 3D buildings | Too slow for camera moves, so stills only |
| **Native MapLibre** (`@maplibre/maplibre-gl-native` 6.4.1) under a virtual display (`xvfb`, Mesa software OpenGL) | The same engine compiled for Node: raw pixels, no browser | First frame 0.5–1.7 s (loading map data); then an **average of 46 ms** over a 72-frame zoom-in from zoom 9 to 15.5 with tilt; rotation works | Same style and labels as today; continuous zoom, rotation and tilt are now affordable | Needs `libopengl0` and `xvfb`; label stability during moves untested; memory over thousands of frames untested; occasional 0.5 s stalls when new map data loads |
| Own vector renderer: Python + Skia | Decode OpenFreeMap's raw vector tiles (`mapbox-vector-tile`), draw roads, water and buildings with `skia-python` | **26 ms per frame** with rotation and zoom; 25 tiles decoded in 0.04 s | Fastest; total control of the look (paper style, fade everything away from the route) | **No labels**, and label placement is the hard part of map drawing; we'd have to write our own style |
| Hybrid A: native MapLibre base + Python overlays | MapLibre draws the map each frame; Python adds the route, dot, cards and strip (as today) | About 50–80 ms per frame expected (not yet run end to end) | Smooth flights from overview to street level, rotating into the travel direction | Draw the route inside the map style (so it sits under labels) or on top? Pre-loading map data along the camera path |
| Hybrid B: Skia geometry + hand-placed labels | Skia draws the map; only the names that matter (route roads, towns, the exit) are labeled, by us | About 30 ms per frame expected | A clean "briefing" look with nothing irrelevant on screen | Writing label placement for the few names; 3D buildings would need extra work |
| Hybrid C: zoom ladder of stills | MapLibre stills at several zoom levels, blended like image pyramids to fake a continuous zoom | No new tools; a few seconds per still | Works with today's code | Can't rotate smoothly; blends can look soft |

Not tested here, but worth an opinion: Mapnik or another server-side renderer fed from a self-hosted PMTiles file; drawing each sheet as SVG and rendering it with `resvg`; Blender with imported OpenStreetMap data for cinematic 3D; AI frame interpolation (RIFE, FILM) between stills, which is likely too slow on a CPU; renting a cloud GPU only for final renders.

## What success looks like

A better method should hit all of these on the same 2-core machine with no GPU:

| Target | Today (v2, stills) | Goal |
| --- | --- | --- |
| Render time for a 3-minute video | About 4 min (2.5 min drawing maps + 1.5 min compositing) | Under 8 min, with real camera moves |
| Camera | Held stills joined by cross-fades | Smooth zoom from overview to street level, rotating into the travel direction |
| Route line | Drawn by Python from projected points; exact | Still exact at every zoom and angle |
| Labels | Baked into each still | Readable on a phone, steady during camera moves, ideally only the names that matter |
| File size | 16–24 MB for 2.5–3 min | Under 40 MB at 1080p, even with moving camera |
| Dependencies | Chromium + MapLibre GL JS + Python | Fewer moving parts; installable from pip, npm or apt in one step |
| Data rules | OpenFreeMap with credit; nothing from tile.openstreetmap.org | Same, or self-hosted data |

## Questions for reviewers

If you answer only one, answer question 1.

1. **Which approach or hybrid would you build next, and why?** Pick from the table or propose your own. Sketch how the parts connect.
2. **Native MapLibre at 46 ms a frame:** what will go wrong when we render 4,000+ frames in a row? Think label flicker or labels jumping between frames, memory growth, stalls while map data loads, and the virtual display. How would you prevent each?
3. **Route line:** should the route be drawn inside the map style (a GeoJSON layer, so it sits under the labels and moves with the camera exactly) or on top in Python? What about the dot, the instruction cards and the bottom strip?
4. **Labels for a briefing:** a normal map shows every street name. A route briefing needs maybe five names at a time. How would you show only the names that matter: style filters, a custom label layer, or hand-placed labels?
5. **Camera paths:** how should the camera fly from the overview down to a turn and back out without making viewers seasick? Name an existing technique, such as the van Wijk and Nuij smooth zoom-and-pan, or what MapLibre's own flyTo uses, and how to time it to narration.
6. **The look:** we'd like an adventure-map feel (old paper, a red route line) without losing readability. Is that a map style job (edit the MapLibre style JSON), a post-processing job (texture and color grading in Python), or both?
7. **Speed and file size:** at about 50 ms per frame for the map plus overlays, what else would you do to keep a 3-minute video under 8 minutes and 40 MB? For example: render at 12 fps and interpolate, cache map data along the path, or tune the encoder.
8. **Anything we're missing?** A library, format or trick that makes this simpler, or a reason one of the options above is a trap.

## Answer template and comparison grid

**Template for reviewers to copy**

```
Reviewer (AI name and version):
Date:

1. Approach I'd build next (and how the parts connect):
2. What breaks over 4,000 frames of native MapLibre, and the fix for each:
3. Route line inside the style or on top (and the dot, cards, strip):
4. Showing only the names that matter:
5. Camera paths (technique, and how to time them to narration):
6. The adventure-map look (style, post-processing, or both):
7. Speed and file-size tricks:
8. What's missing, or which option is a trap:

My estimate for a 3-minute video with my approach (render time, file size):
The one thing most likely to go wrong:
```

**Comparison grid**

| Reviewer | Date | Approach they'd build | Route line: style or overlay | Labels plan | Camera technique | Estimated render time | Biggest risk named |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Gemini Pro Latest | Oct 31, 2026 | Native MapLibre only for 1–1.5 s flights between held views; local tile cache; Node worker piped to Python | In the style, under labels; dot, cards, strip in Python | Strip base labels; one curated label layer with overlap allowed | van Wijk & Nuij; fly in the pause, hold while speaking | 2–2.5 min, 18–28 MB | Labels popping during flights |
| Claude Opus Latest | Oct 31, 2026 | Hybrid A with three modes: hold, flat crop of a big still, full flight | In the style, revealed by gradient or filter; dot and labels in Python via a calibrated projection | Own label layer in Python, chosen per segment | van Wijk & Nuij; zoom first, rotate in the last 30% | 6–9 min, 25–40 MB | Python projection drifting off the roads when tilted |
| Grok Latest | Oct 31, 2026 | Native MapLibre, one map object, a shot list from the narration | In the style; Python only on untilted holds | Hide base labels; one curated label source | van Wijk & Nuij; one change per move | 3–5 min, 15–30 MB | Python-drawn line under tilt; time a cold city frame first |
| GPT Astra Latest | Oct 31, 2026 | Hybrid A, with MapLibre drawing the route and dot too | In the style; reveal and dot by frame-index filters | Context labels plus a per-shot briefing label source | Move, settle, explain; d3 interpolateZoom | 5–8 min | Label instability or costly per-frame layer updates |
| Muse Wonder | Oct 31, 2026 | Hybrid A; one Node process per shot; pre-flight tile warm-up | In the style, revealed by distance-bucket filter; dot as a point layer | Curated GeoJSON labels, per-shot filters | van Wijk & Nuij; bearing first half, pitch second half | 5–7 min, 25–40 MB | Labels popping during continuous zoom |

**What we measured afterwards (Manhattan, tilted, 3D, 1920×1080):** a flight frame takes about 180 ms (median; 0.7 s max on the first run, 0.47 s once cached), against 46 ms in rural Gordonsville. `setFilter` route reveals cost about 1 ms. The local resource cache cut network requests to zero on the second run. Flights cost a lot of file size: 14 MB for 5 s over Manhattan, against 38 KB for a 4 s hold. A new trick no reviewer suggested also worked: for each held view, render the map, the map with the route, and a hidden ID image where the route's colour encodes its position along the trip. NumPy then reveals the route and places the dot exactly on the tilted map, with no `project()` needed, at about 40 ms per frame.

Treat agreement as a lead to test, not proof: reviewers can share the same wrong assumption. Anything they claim about speed is worth a quick benchmark before we build on it.
