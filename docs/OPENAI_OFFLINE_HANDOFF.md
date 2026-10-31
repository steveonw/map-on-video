# OpenAI offline ZIP handoff (experimental)

This branch preserves `main` and adds an offline mode to `routevid3.py`.

## Use

Given the one-pass browser downloader's `route-video-onepass-v2` ZIP:

```sh
python3 routevid3.py --from "Woodbridge, Virginia" --to "Billings, Montana" \
  --contact YOUR_EMAIL --work wb-billings \
  --offline-assets /path/to/route-assets-woodbridge-billings-onepass.zip --plan-only
```

For an image test, replace `--plan-only` with `--stills 2,15`. Preserve `--work` and the cache directory across runs. Do not request a full MP4 before checking stills.

The `tools/offline_assets.py` adapter validates the route pair and ZIP status, populates the Python route/geocode/style cache, and seeds MapLibre's SHA1(URL) resource cache with the downloaded tiles, sprites, glyphs and TileJSON. `--offline-assets` blocks missing online requests; without the option, existing network behavior is unchanged. If a still fails, check `<work>/worker.log` for missing asset URLs.

## Known gaps

The one-pass ZIP currently contains *sampled* vector tiles, often only through zoom 11. Close turn views in the renderer use zoom ~15; **a complete offline MP4 is not yet supported by this sample package**. Native MapLibre must still be installed for first render (Node, Xvfb and @maplibre/maplibre-gl-native@6.4.1). The ZIP does not contain Natural Earth administrative boundary files; offline mode skips state-entry chips. Reverse geocoded turn labels become coordinates rather than place names.

This branch has not been tested through a full native MapLibre still or MP4 in this environment. Validate dependencies and map coverage before shipping.

Never bulk-download from OSM Foundation raster tile servers. Respect the map-data provider's limits and attribution. The video is a preview, not live navigation.
