# Results and version history

All numbers come from the same machine: 2 CPU cores, about 7 GB RAM, no GPU, 1920×1080 at 24 fps.

## Versions

| | v1 | v2 | v3 (current) |
| --- | --- | --- | --- |
| Maps | Raster tiles from tile.openstreetmap.org, stitched into "sheets" on a paper-map table | OpenFreeMap vector tiles, drawn as 15–25 stills by MapLibre GL JS in headless Chromium (about 5 s each) | OpenFreeMap, drawn by native MapLibre in Node under xvfb (about 0.05–0.2 s a frame) |
| Camera | Pans across the sheet table; turn close-ups in a corner inset | Held stills, 0.5 s cross-fades between them | Holds while a line is spoken; van Wijk flights in the pauses |
| Route line and dot | Drawn in Python on the stitched image | Python, from points projected by the browser | ID image + NumPy for holds; MapLibre `setFilter` for flights |
| Narration | None | Kokoro; timestamps set pacing | Same, and pauses stretched to fit each flight |
| NYC → Hollywood | 3:15, about 160 MB, 7–8 min | 3:08, 24 MB, about 4–5 min | 3:42, 45 MB, 7 min |
| Status | **Retired.** It broke the OSM tile usage policy (about 940 tiles pre-fetched). | Superseded | In use |

## What we measured for v3

- **Native MapLibre** (`@maplibre/maplibre-gl-native` 6.4.1, Mesa software GL):
  - **Frame time:** a 72-frame zoom from 9 to 15.5 with tilt over rural Virginia averaged 46 ms per frame.
    A tilted 3D flight over Manhattan took a median of 180 ms per frame (p95 about 300 ms; worst case 0.47 s
    once cached, 0.74 s on the first run).
  - **Memory and network:** the worker used about 820 MB of memory. A second run made no network requests,
    because every tile, font and sprite is cached on disk.
- **Browser MapLibre**, for comparison: 1.9–2.8 s per live frame, and about 5 s per still.
- **Own Skia renderer** (decode vector tiles + `skia-python`): 26 ms per frame, but it has no labels. Not pursued.
- **The ID-image trick:**
  - Each hold needs three renders (map, map + route, ID), about 1 s together.
  - After that, compositing takes about 40–50 ms per frame.
  - The dot and the red line land exactly on the road in tilted 3D close-ups.
  - This replaces `project()`, which native MapLibre lacks.
- **Revealing the route with `setFilter`** (3 layers) costs about 1 ms.
- **Bitrate:**
  - Holds cost about 1.2 Mbps.
  - Flights cost about 5.3 Mbps uncapped, rising to 6.7 over cities.
  - Capping with `-maxrate 3M -bufsize 3M -tune animation -crf 24` took NYC → Hollywood from 59 MB to 45 MB.
    Potomac Mills → Wise stayed at 32 MB, because its rural flights were already under the cap.
- **Time split for NYC → Hollywood (413 s):**

  | Step | Time |
  | --- | --- |
  | Hold set-up (21 holds × 3 renders) | 8 s |
  | Hold compositing (about 4,100 frames) | 193 s |
  | Flight frames (1,177) | 107 s |
  | Narration, overlays and encoding | the rest |
- **Narration check:** speech recognition missed about 9% of words, mostly road numbers ("I two eighty",
  "U.S. one oh one"). That's the recognizer, not the voice.

## v3.1: fixes from the second round of AI reviews

Measured on a 2-core machine, before and after. Potomac Mills → Wise ran both versions on the same machine;
the NYC "before" numbers are the v3 measurements above.

| | Wise v3 | Wise v3.1 | NYC v3 | NYC v3.1 |
| --- | --- | --- | --- | --- |
| Whole run (narration, maps, encoding) | 4:55 | 3:10 | 7 min | 4:31 (incl. first tile downloads) |
| Frame loop | 218 s | 130 s | 413 s | 188 s |
| Hold compositing | 109 s | 34 s | 193 s | 35 s |
| Overlays (strip, cards, chips) | not timed | 14 s | not timed | 20 s |
| Flights | 34 s of motion, no dot | 39 s, dot on the road | no dot | 49 s, dot on the road |
| Video | 2:57, 32.3 MB | 3:02, 34.4 MB | 3:42, 45 MB | 3:43, 46.0 MB |

- **Faster holds.** Only the route's bounding box is recomposited each frame, and frames stay RGB (no
  RGB → RGBA → RGB round trip). Border-chip times are computed once instead of 200 samples per border per frame.
  Overlays now have their own timer, so the numbers add up.
- **Blue dot in flights.** A MapLibre circle layer at each flight's mile, shown only during that flight, sized
  to match the dot Python draws in holds.
- **No more spins.** A flight that ends or starts in a tilted, rotated view is lengthened so each rotation
  stays under about 135° a second (cap 3 s). Before, a 160° turn could happen in under a second.
  This added 5 s of flights (and about 2 MB) on the Wise route.
- **Turn cards never drop words.** Before, anything past the second line was cut silently. Now the card
  shrinks from 46 px to as small as 34 px to fit three lines, and the plan step warns if even that's not enough.
- **Start marker:** a green circle with a white "go" triangle, not an "S" that reads as "5".
- **Attribution** has a light halo, so the required credit stays readable over dark map areas.
- **One source of truth for a trip:** the first run saves its settings in `<work>/args.json`; later steps need
  only `--work`. A narrated render also writes `<work>/plan_check.json` for `tools/check_audio.py`.
- **Pinned** `@maplibre/maplibre-gl-native@6.4.1`, the version all these numbers come from.

Two findings worth recording:

- **The strip and cards were opaque all along.** They're drawn with alpha 232–238, but on an RGBA image
  Pillow writes the colour without blending, so they came out solid, and the "Now entering" chip popped in instead
  of fading. With RGB frames, alpha now blends; the strip and cards are now drawn solid on purpose (same look as
  before), and the chip fades as intended. Every other pixel of the held views is identical to v3.
- **The ID image held up.** A reviewer-style worry was that anti-aliased pixels where the colour code wraps
  (R 255 → 0 every 256 segments) would decode far from the road. On all 21 holds of the Wise route,
  3 of 612,894 route pixels decoded more than 20 segments from their neighbours, with the plain encoding and with
  a "reflected" encoding alike, so they come from the route nearly touching itself, not from the wrap. No change made.

## What the AI reviewers agreed on

From [handout 1](handout-1-product-review.md) (product) and [handout 2](handout-2-rendering-review.md) (rendering), with five reviewers each:

- **Narration first**, with pacing driven by the narration: linear travel that pauses at each key turn.
- **Cut** the big state banners, the locator inset and continuous panning; hold the camera still instead.
- **Rendering:** native MapLibre (no browser), the route as a GeoJSON layer inside the map style,
  curated labels only, and van Wijk & Nuij camera flights timed to the pauses between spoken lines.
- **Main risk named:** labels popping during flights. v3 keeps labels to city, state and highway shields plus the start and end names.

## Open issues and ideas

- **Flights cost most of the file size** (and v3.1's calmer rotations add a little). Shorter flights between
  nearby legs, or flying only into turn close-ups, would cut size and render time.
- **Where the route nearly touches itself** (cloverleafs, out-and-back legs), a few ID pixels take the other
  pass's mile. It hasn't been visible yet; a frame of a cloverleaf with `--stills` would settle it.
- **check_audio.py flags road numbers** ("I two eighty", "U.S. one oh one") on long routes; the fix belongs in
  Read-Aloud-Lessons, where the tool lives (homophones such as eye/I and oh/zero).
- **Features:** exit numbers and lane graphics (Mapbox or Valhalla data), an adventure-paper map style,
  overnight splits for multi-day trips, a printable turn sheet and GPX, and a vertical 9:16 version.
