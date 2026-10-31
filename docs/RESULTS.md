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

## What the AI reviewers agreed on

From [handout 1](handout-1-product-review.md) (product) and [handout 2](handout-2-rendering-review.md) (rendering), with five reviewers each:

- **Narration first**, with pacing driven by the narration: linear travel that pauses at each key turn.
- **Cut** the big state banners, the locator inset and continuous panning; hold the camera still instead.
- **Rendering:** native MapLibre (no browser), the route as a GeoJSON layer inside the map style,
  curated labels only, and van Wijk & Nuij camera flights timed to the pauses between spoken lines.
- **Main risk named:** labels popping during flights. v3 keeps labels to city, state and highway shields plus the start and end names.

## Open issues and ideas

- **No dot during flights.** Holds use the ID image to place the dot, and flights have no ID image.
- **Flights cost most of the file size.** Shorter flights, or flying only into turn close-ups, would cut size and render time.
- **Compositing is the slowest step** (about 45 ms per frame). It could redraw only the band that changes.
- **The "S" start marker looks like a "5"** on the overview.
- **Features:** exit numbers and lane graphics (Mapbox or Valhalla data), an adventure-paper map style,
  overnight splits for multi-day trips, a printable turn sheet and GPX, and a vertical 9:16 version.
