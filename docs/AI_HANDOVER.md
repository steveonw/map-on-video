# AI HANDOVER — OpenAI route-video development
Last updated: 2026-10-31. This document is a durable handover for another assistant / a future session.

## Goal and user preferences
Build a high-quality, narrated, offline-rendered map route briefing MP4 from a start and destination. Source of truth for renderer is this repository. Keep **main** (original Claude-oriented implementation) unchanged; experimental changes belong in branch `openai-offline-handoff`. The user wants **one browser download and one ZIP upload**, not a chain of manual JSON requests. User prefers demonstrable small iterations (stills, preview MP4, screenshot review) and compact overlays rather than broad title/footer bars.

## Current test journey and data
- Woodbridge, Virginia -> Billings, Montana, US.
- Coordinates from Nominatim: Woodbridge (lon -77.2676335, lat 38.6364470), Billings (lon -108.4960700, lat 45.7874957).
- OSRM drive approx **1,965 miles**, **35.1 hours**, **67 routing steps**, route geometry approx **25,314 points**.
- One-pass browser asset ZIP: `route-assets-woodbridge-billings-onepass.zip`, downloaded by user and supplied in ChatGPT conversation. It includes route geometry, geocoding, OpenFreeMap Liberty style, sprites, initial fonts and **240 sampled vector tiles** (limited, generally through zoom 11). No guarantee of close-turn zoom (~15) coverage.
- The ChatGPT runtime files referenced below were **conversation artifacts, not checked into this repository**. In a new session, search conversation attachments/File Library or ask for re-upload if unavailable. Do not invent sandbox download URLs or claim they are in GitHub.

## GitHub changes and stable resources
- Experimental branch: `openai-offline-handoff` (do not merge without testing). Draft PR: https://github.com/steveonw/map-on-video/pull/3
- `tools/offline_assets.py`: adapter to seed route/geocode/style and SHA1(URL) cache entries from `route-video-onepass-v2` ZIP; validates route.
- `routevid3.py`: experimental `--offline-assets` option; rejects missing offline network assets; retains normal online mode if flag omitted. It may need more testing and fixing.
- `docs/OPENAI_OFFLINE_HANDOFF.md`: installation/use details, coverage warning.
- `.github/workflows/build-maplibre-linux.yml`: Linux native MapLibre 6.4.1 build; uses Ubuntu 24.04 + Node 22 and packages matching ICU/JPEG/PNG shared libraries. **Successful run #5**: https://github.com/steveonw/map-on-video/actions/runs/41180889209 ; published artifact named `maplibre-native-linux-x64`. Later revisions may have additional successful runs. Inspect latest results before use.
- The native module was successfully loaded on the ChatGPT Linux runtime using its portable bundle and `LD_LIBRARY_PATH`, under Xvfb, and produced real map frames from the seeded cache. Node/ffmpeg/Xvfb/Python scientific libraries worked in the test runtime. Portability must be checked afresh in a new runtime.

## Video iterations (conversation artifacts, not currently committed)
All were made from the real OSRM route using native MapLibre imagery/frames (later versions can composite pre-rendered map views with Python/Pillow and FFmpeg rather than running upstream `routevid3.py` end to end):
- 8-second native map MP4: `woodbridge-billings-native-map-preview.mp4` — top title clipped, mid-route framing.
- V2 30-second native overview: `woodbridge-billings-native-30sec.mp4` — whole route fits, marker and progressive red line, but big title/footer.
- V3 50-second regional briefing: `woodbridge-billings-v3-briefing.mp4` — 5 regional views and captions, hard camera cuts; big bars.
- V4 50-second cleaner layout: `woodbridge-billings-v4-clean-layout.mp4`; contact sheet `woodbridge-billings-v4-contact-sheet.jpg`. Thin lower strip, smaller title; user prefers this layout.
- V5 50-second silent turn highlights: `woodbridge-billings-v5-turn-highlights.mp4`; contact sheet `woodbridge-billings-v5-contact-sheet.jpg`. Compact highway guidance cards (I-495/I-270, I-70, I-80/I-90, I-94, Billings approach) while preserving regional camera movements and small overlay. This is **the latest user-visible deliverable** as of this handover. No user review of V5 yet.
- User provided reference `briefing_nyc_to_hollywood_v3 (1).mp4` and screenshots of a Claude-generated route video and a Potomac Mills -> Wise, Virginia *contact sheet*. Reference has map covering almost entire frame, slim information strip, small dark turn card, turn closeups and animated progress. Use as a stylistic reference, not as proof that our current zoom-15 tile data exists.

## Next engineering priorities
1. **Persist the real V5 render recipe/source**: V5 MP4/contact sheet exist in conversation workspace but have NOT been committed in branch. Recover the actual code and assets if available; do not imply git branch contains V5 scripts.
2. Make camera-specific map resource planner: derive needed tiles + font glyph ranges from **exact upstream cameras and flights**, including off-center views and pitch; avoid assuming sampled 240 tiles suffice. Respect provider usage policies.
3. Extend one-pass HTML browser downloader / manifest to retrieve just needed additional assets, ideally still **one request/one upload**. Include accurate download-report.json and audit coverage.
4. Produce native MapLibre close-up stills first; check all missing assets, no empty tiles/fonts, turn accuracy, title/card/footer margins, labels and progress dot placement.
5. Build smoother intentional hold -> flight -> settle transitions. Favor camera motion during pauses, legible holds while explaining turns. The focused-explainer-video skill's move-settle-point-hold design may help. Avoid large title/footer panels.
6. Add narration using verified neural voice models only after preflight (prefer Kitten/Kokoro; check conversation/Library assets, not only local cache). Validate speech, timing, captions, audio; keep silent preview labelled silent if no voice.
7. Render, inspect contact sheet plus actual sampled frames, and verify MP4 with ffprobe and optional ASR quality checks. Explicitly mark route video as preview, not live navigation.
8. Ideally commit tested scripts, tests, docs, and an updated handover on this branch; large media can live as GitHub Release artifacts if appropriate, not automatically inside Git.

## Resume checklist (for another AI)
- Read this file, branch `openai-offline-handoff` and docs/OPENAI_OFFLINE_HANDOFF.md, inspect PR #3 and the current git HEAD. Do not assume this document reflects newer commits.
- Check files available in current conversation, local runtime, and user Library before requesting re-uploads.
- Recover route one-pass ZIP + portable MapLibre artifact from successful GitHub Actions run; validate archive before executing/expanding.
- Check branch's offline adapter against ZIP's actual schema; do not use personal email as Nominatim contact without user supplying it.
- Run a small native still test; build a rendering plan based on verified data; avoid promising full native video before coverage.
- Update this handover with exact version, deliverables, validated commands, remaining defects after every milestone.
