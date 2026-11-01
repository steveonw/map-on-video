# Woodbridge, Virginia -> Billings, Montana (reviewed example)

Everything needed to reproduce the reviewed Woodbridge -> Billings briefing with merged `main`
(`routevid3.py` at `32e5c2f`), online or fully offline.

| File | What it is |
| --- | --- |
| `turns.json` | The hand-reviewed turn list. **Pass it with `--turns-json`**; the automatic list is wrong here (see below). |
| `woodbridge-to-billings-pack.zip` | *Not in git* (56.5 MB). Complete `route-video-pack-v1`, made by Claude with `--make-pack`. Hand it over as a file. sha256 `eb8bc5f287f414c4121eb0c9bd9d007bec1640ccad5607d3474a9992155b91fc`, 56,480,432 bytes, 879 files. |

## Render offline from the pack

```bash
# Kokoro folder layout that tools/narrate.py actually reads (not one flat folder):
#   <kokoro>/onnx/model.onnx   <kokoro>/tokenizer.json   <kokoro>/voices/af_heart.bin
python3 routevid3.py --assets woodbridge-to-billings-pack.zip \
  --from-label "Woodbridge, Virginia" --to-label "Billings, Montana" \
  --turns-json docs/examples/woodbridge-billings/turns.json \
  --narrate <kokoro> --voice af_heart --work wb-billings --plan-only
python3 routevid3.py --work wb-billings --stills 2,87,135,250      # optional check
python3 routevid3.py --work wb-billings --out woodbridge-to-billings.mp4
```

Expected: 11 key turns, 27 spoken lines, timeline about 258.5 s narrated, 6,204 frames, worker summary
`{"net":0,"misses":0}`, empty `missing.jsonl`. The intro says "about thirty-five hours eight minutes".

## What was verified (Claude, 2026-11-01)

- **Pack built online** from merged `main` with `--make-pack` + `--asset-plan`: 875 resources
  (783 vector tiles, **78 `natural_earth/ne2sr` raster tiles**, 11 glyph ranges, 2 sprites, 1 TileJSON) plus
  route, geocodes and place names for all 55 maneuvers.
- 5 glyph ranges are reported "not available": `256-511` and `8192-8447` of Noto Sans Bold/Italic/Regular.
  They are the speculative "standard glyph ranges" the planner adds; OpenFreeMap doesn't serve them and no camera
  uses them. They don't cause misses.
- **Offline proof:** `unshare -n` (no network at all), a fresh `--cache` holding only the MapLibre binary (`node3`):
  `--asset-plan` against the pack reported **0 not available**; the full narrated render finished in 319 s on
  2 cores, 259 s / 54.3 MB MP4, `net=0, misses=0`, `missing.jsonl` empty.
- **Same video as online:** frames at 8 times (map area, rows 0-960) from the offline and the online render
  match: mean difference 0.00-2.0 of 255 (0.00 at 5 s and 20 s), and 6.3 for one mid-flight frame at 230 s, which a
  side-by-side shows is a sub-frame timing offset with the same tiles and labels.
- Narration ASR check (`tools/check_audio.py`, sherpa zipformer small): 7.5% of words missed, "OK: no problems";
  flagged lines were recognizer quirks (Breezewood, Tomah).

## Route-data quirks you should know about

1. **Two OSRM detours stay in the route line.** The OSRM demo router leaves I-90 twice: in Chicago it exits the
   Kennedy at Montrose Avenue and uses Milwaukee Ave / Northwest Hwy / Bryn Mawr / Higgins Rd to rejoin I-90 near
   O'Hare (miles 723-731), and near Beloit, WI it exits at Shopiere Rd and uses County J to the Avalon Rd ramp
   (miles 813-822). A real driver stays on I-90. Waypoints on I-90 didn't help (OSRM snapped them to side streets;
   its data seems to treat those I-90 stretches as unusable). Neither detour is narrated; on the long-leg views they
   are a barely visible wiggle.
2. **Automatic turns are wrong here**, which is why `turns.json` exists: without it the planner announces
   "Take the ramp onto I-39" at the county-road ramp near La Prairie, WI, says "Turn straight onto I-90" at Hammond,
   and misses the I-39 split at Portage.
3. **Two road names in the route were corrected** before the pack was made (the pack's `data/route.json` already
   has them): step 23 `ref` `I 70; I 76` -> `I 76; I 70` (so the Turnpike leg is spoken as I-76, not I-70), and
   step 60 `name` `MnRoad Mainline` -> empty (OSM names 800 miles of I-94 after the MnROAD test track). If you
   re-route online from OSRM instead of using the pack, you get the unpatched names.
4. OSRM's 35.1 h is long; typical estimates for this drive are about 29 h. The video says it is a preview.
