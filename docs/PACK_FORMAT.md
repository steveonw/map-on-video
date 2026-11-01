# Asset packs: `route-video-pack-v1` and `route-video-needs-v1`

A **pack** holds everything one trip needs, so `routevid3.py --assets pack.zip` renders with no network at all.
Any tool can write one:

- `routevid3.py --make-pack` (online);
- the browser fetcher;
- `tools/onepass_to_pack.py`, which converts the browser fetcher's older `route-video-onepass-v2` ZIPs.

The renderer reads every pack the same way, so the same pack gives the same video in every environment.
The reference code is `tools/pack.py`, and `tests/test_pack.py` pins its behaviour.

## Workflow

```bash
# Online (Claude, or anyone with network): plan, then build a complete pack
python3 routevid3.py --from "Potomac Mills, Woodbridge VA" --to "Wise, Wise County, Virginia" \
  --contact you@example.com --work wise --plan-only
python3 routevid3.py --work wise --make-pack wise-pack.zip --asset-plan wise-needs.json

# Offline (ChatGPT, a plane, a server with no internet): render from the pack
python3 routevid3.py --assets wise-pack.zip --from-label "Potomac Mills" --to-label "Wise, Virginia" \
  --work wise --stills 2,33,60
python3 routevid3.py --work wise --out briefing.mp4

# Offline with an incomplete pack: list exactly what's missing, fetch it, add it to the pack, render
python3 routevid3.py --assets partial.zip --work wise --asset-plan needs.json
```

| Flag | What it does |
| --- | --- |
| `--assets PACK` | Use a ZIP or an unpacked folder. Nothing is fetched. `--from`/`--to` default to the pack's route, and if given they must match it exactly. `--contact` isn't needed. |
| `--on-missing fail\|blank` | What to do with a resource the pack lacks. `fail` stops at the first frame that needs it; it's the default for the video. `blank` draws it as empty map; it's the default for `--stills` and planning. Either way, every miss is written to `<work>/missing.json` as `{url: [cameras that needed it]}`. |
| `--asset-plan NEEDS_JSON` | A dry run over every camera. Nothing is drawn to disk and no voice is needed. It writes the needs list (below). Online it also fetches as it goes; with `--assets` it reports what the pack lacks. |
| `--make-pack PACK_ZIP` | Online only. Runs the asset plan, fetches extra glyph ranges and place names for every maneuver, and writes a complete pack. |

The `--work` folder remembers the trip, including `--assets` and `--cache`. Each run also writes
`<work>/provenance.json` with the tool commit, MapLibre version, pack path, pack sha256 and miss policy.

## Pack layout

```
pack.json
http/<host>/<path>        map resources: style, TileJSON, vector tiles, raster tiles, sprites, glyphs
data/geocode.json         {"<query exactly as given to --from/--to>": [lon, lat, "display name"]}
data/route.json           OSRM /route/v1/driving response, unchanged: overview=full, geometries=geojson, steps=true
data/reverse.json         {"<lat>,<lon>": "Town, ST"}   lat and lon with 3 decimals, e.g. "38.301,-77.504"
```

`pack.json` example:

```json
{
 "schema": "route-video-pack-v1",
 "route": {"from": "Potomac Mills, Woodbridge VA", "to": "Wise, Wise County, Virginia"},
 "style": "https://tiles.openfreemap.org/styles/liberty",
 "created": "2026-11-01T01:05:00Z",
 "created_by": "routevid3 --make-pack",
 "tool_commit": "abc1234",
 "attribution": "OpenFreeMap © OpenMapTiles Data from OpenStreetMap; route OSRM; geocoding Nominatim (OpenStreetMap)",
 "files": {
  "data/route.json": {"sha256": "<64 hex>", "size": 581125},
  "http/tiles.openfreemap.org/planet/index": {"sha256": "...", "size": 1234},
  "http/tiles.openfreemap.org/planet/20261025_080012_pt/12/1166/1569.pbf": {"sha256": "...", "size": 48211}
 }
}
```

Required fields: `schema`, `route.from`, `route.to`, `files`. Every file other than `pack.json` must be listed in
`files` with its sha256, and every listed file must be present. Other fields are informational.

### URL → file mapping

Each map resource is stored under the URL MapLibre requests it by:

1. **Root.** The file is `http/` + the host in lower case + the percent-decoded path. The scheme is dropped, and http and https map to the same place.
2. **No extension.** If the last path segment has no `.`, `/index` is appended. This lets a TileJSON at
   `…/planet` and tiles under `…/planet/<build>/…` both exist.
3. **Query string.** If there is one, `@` plus the first 16 hex digits of the sha1 of the query (without the `?`) is appended to the last segment.
4. **Unsafe URLs.** Paths with `.` or `..` segments (also as `%2e`), backslashes or NUL are rejected.

| URL | File |
| --- | --- |
| `https://tiles.openfreemap.org/styles/liberty` | `http/tiles.openfreemap.org/styles/liberty/index` |
| `https://tiles.openfreemap.org/planet` | `http/tiles.openfreemap.org/planet/index` |
| `https://tiles.openfreemap.org/planet/20261025_080012_pt/6/17/25.pbf` | `http/tiles.openfreemap.org/planet/20261025_080012_pt/6/17/25.pbf` |
| `https://tiles.openfreemap.org/fonts/Noto%20Sans%20Bold/0-255.pbf` | `http/tiles.openfreemap.org/fonts/Noto Sans Bold/0-255.pbf` |
| `https://tiles.openfreemap.org/sprites/ofm_f384/ofm@2x.json` | `http/tiles.openfreemap.org/sprites/ofm_f384/ofm@2x.json` |
| `https://tiles.openfreemap.org/natural_earth/ne2sr/6/17/24.png` | `http/tiles.openfreemap.org/natural_earth/ne2sr/6/17/24.png` |

The map worker does the same mapping in JavaScript (`PACK_JS` in `tools/pack.py`). A test runs both on the same
URLs and checks that they agree.

**Glyph URLs.** MapLibre native asks for `fonts/<font stack>/<range>.pbf`, with the stack percent-encoded (`Noto%20Sans%20Bold`). The pack stores the decoded name: `fonts/Noto Sans Bold/0-255.pbf`.

### Versioned tiles

OpenFreeMap's TileJSON points at a dated build (`planet/20261025_080012_pt/{z}/{x}/{y}.pbf`) that changes about weekly.
A pack built today and a top-up fetched next week may therefore name different builds.

When a tile's exact file is missing, the reader falls back to **any tile in the pack with the same host,
prefix, z, x and y**: the segment just before `z` is ignored. Packs can mix builds, but the TileJSON in the pack
decides which URLs get requested.

### Place names

`data/reverse.json` gives the "near Fredericksburg, VA" part of each turn line and card. The key is the
maneuver's location from `route.json` (`steps[i].maneuver.location`), written as `f"{lat:.3f},{lon:.3f}"`. The value
is `"Town, ST"`: Nominatim reverse at zoom 12, using the first of city / town / village / hamlet / suburb / county,
plus the state's postal code.

The planner only needs names for the turns it picks. Fetchers that don't know which turns those are should
include every maneuver of type turn, fork, off ramp, on ramp, merge, end of road, roundabout or rotary. That's about
1 per 10 miles, at 1 request per second. A missing name is never replaced by coordinates; the line and card
leave the name out. Plans list any missing names, and so does `needs.json`.

### State borders

Borders don't come from the pack. `data/admin1.geojson` in this repo has Natural Earth admin-1 polygons for the
US, Canada and Mexico. Routes elsewhere fall back to downloading Natural Earth, which is online only.

### Validation (before anything is unpacked)

- **Paths:** no absolute paths, `..`, backslashes, drive letters or NUL. Everything except `pack.json` must be under `http/` or `data/`.
- **Entry types:** only regular files; no symlinks. Duplicate names (ignoring case) are rejected.
- **Limits:** at most 100,000 entries, 64 MB per entry and 4 GB in total. A compression ratio above 1000:1 is rejected.
- **Manifest:** `pack.json` must have the schema and route, and list exactly the files present, with matching sizes.
- **Checksums:** after unpacking to `<cache>/packs/<sha256 of the zip>/`, every file's sha256 is checked before the
  pack is used. The unpacked copy is reused on later runs. An unpacked folder can be passed instead of a ZIP; it gets the same checks.

## Needs list (`route-video-needs-v1`)

```json
{
 "schema": "route-video-needs-v1",
 "route": {"from": "...", "to": "..."},
 "style": "https://tiles.openfreemap.org/styles/liberty",
 "pack": "/path/to/partial.zip",
 "counts": {"glyphs": 9, "raster-tile": 13, "sprite": 2, "tile": 470, "tilejson": 1},
 "missing": 428,
 "data": {
  "geocode": ["<from>", "<to>"],
  "route": true,
  "reverse": [{"key": "38.301,-77.504", "lon": -77.504, "lat": 38.301, "turn": 1, "have": false}],
  "reverse_all_maneuvers": ["38.643,-77.296", "..."]
 },
 "resources": [
  {"url": "https://tiles.openfreemap.org/planet/20261025_080012_pt/14/4577/6332.pbf",
   "path": "http/tiles.openfreemap.org/planet/20261025_080012_pt/14/4577/6332.pbf",
   "kind": "tile", "have": false,
   "used_by": ["flight 12 (travel 12 -> close 13) k=0.752-0.752", "flight 13 (close 13 -> travel 14) k=0.198-0.198"]}
 ]
}
```

- **`kind`** is one of `tile`, `raster-tile`, `glyphs`, `sprite`, `style`, `tilejson` or `other`.
- **`used_by`** names the cameras that need the resource:
  - `hold <i> <intro|travel|close|outro> [turn <n>]` is the still view for spoken line *i*.
  - `flight <i> (<kind> <i> -> <kind> <i+1>) k=<from>-<to>` is the camera move after line *i*. `k` is progress through the flight, from 0 to 1.
  - `standard glyph ranges` are the 0-255, 256-511 and 8192-8447 ranges of each font, added because a dry run on empty tiles can't see label text.
- **A top-up fetch** gets every resource with `"have": false` from its exact `url` and stores it at its `path`.
  It also adds `data/reverse.json` entries for `data.reverse` items with `"have": false`.

### How the plan is made

The worker renders every camera the video will use, at 1280×720 CSS px and pixel ratio 1.5, and records every request:

- each held view, with 3D buildings when the view is tilted;
- each flight, sampled at 3 positions per output frame, plus both sides of every integer-zoom crossing.

The zoom crossings matter: at those moments the tile pyramid switches level and the new level's cover is widest. A
regular grid at 2 samples per frame missed 2 such tiles on Potomac Mills → Wise.

The plan doesn't depend on the narration, so it needs no voice. Rendering is the same on any machine, so
the plan is exact for a given route, style and TileJSON.

Measured on 2 cores, no GPU:

| Trip | Planning time | Resources | Pack size |
| --- | --- | --- | --- |
| Potomac Mills → Wise (379 mi) | 2.4 min | 491 (478 tiles) | 16.5 MB |
| NYC City Hall → Hollywood & Vine (2,800 mi) | 4.6 min (5.7 min with place names) | 737 (717 tiles) | 42.4 MB |

The full offline renders from these packs (no network, empty cache) had 0 misses. The Potomac Mills stills match the online render; the largest difference was 5 of 255 in one channel, which is JPEG noise.

## Converting a browser one-pass ZIP

```bash
python3 tools/onepass_to_pack.py route-assets-<job>.zip pack.zip [--reverse reverse.json]
python3 routevid3.py --assets pack.zip --work job --asset-plan needs.json     # what is still missing
```

The converter rebuilds each file's URL from the style and TileJSON in the same ZIP. It also reads
`assets/geocode/reverse.json` if the ZIP has one, in the same format as `data/reverse.json`.

## Rules that still apply offline

- **Attribution.** "OpenFreeMap © OpenMapTiles Data from OpenStreetMap" is drawn on every frame.
- **Tile sources.** Never fill a pack from `tile.openstreetmap.org`; its policy bans pre-fetching.
- **Nominatim and OSRM.** Both are for light use. Keep Nominatim to 1 request per second and identify yourself, with a User-Agent or an `email=` parameter.
- **No keys in packs.** A pack from a keyed provider must not contain the key in any stored URL.
