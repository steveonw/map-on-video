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

## 2026-10-31 continuation: V6 reproducible preview
- Created and locally verified **40-second silent** V6 MP4 `woodbridge-billings-v6-reproducible.mp4` (960x540, 12 fps, H.264; ffprobe duration 40.000s). A midroute frame was reviewed for clear UI and route positioning.
- Created a **reproducible source ZIP** `woodbridge-billings-v6-source.zip` containing `render_preview.py`, `map30.png` (the actual native MapLibre 1280x720 overview image), the original one-pass Woodbridge-to-Billings ZIP, and README with exact run command. These two artifacts are delivered via the ChatGPT conversation, **not currently stored in this GitHub repository**; recover them from user conversation attachments or request upload.
- V6 preserves V4/V5 compact overlay preferences, animates the actual OSRM route geometry, advances the blue marker, and introduces gentle image-space camera crop moves. **Crucially, these are crops of one already-rendered native MapLibre frame, NOT full native high-zoom frame rendering**. No new tiles were fetched; still silent. Do not mistake this for complete upstream `routevid3.py` output.
- Next priority is moving the standalone V6 renderer into the repo and replacing overview-image camera crops with *actual* camera-specific MapLibre renders, then turn guidance and verified narration. Main remains untouched.

## Additional reference: uploaded Claude v3 skill bundle (2026-10-31)
User supplied a ZIP named `Route briefing video v3-v1.zip` containing exactly `.claude-plugin/plugin.json` and `skills/route-briefing-video-v3/SKILL.md` (~58 KB). This is **reference material, not a complete dependency bundle**. The skill contains an older full `routevid3.py` code block, renderer theory, camera/turn/timing constraints, ffmpeg settings, and voice-system integration instructions. It documents native MapLibre flights (van Wijk), pitched ~15 zoom turn holds, ID-image mile overlay, narration-paced holds and flights, and chapter/subtitle output. The repository's checked-in `routevid3.py` is the stronger, newer source of truth and includes later fixes; do **not** overwrite it with the older embedded code. Reuse this reference to inform evaluation and QA, especially map-dominant imagery and restrained cards. V6's image-crop renderer is only a backup prototype; prioritize bringing the actual upstream/native worker fully offline with camera-specific asset capture. User-provided ZIP is a conversation attachment, not added to Git.

## 2026-10-31 PR #4 collaboration update
- Claude opened PR #4 against main from branch `pack-and-asset-plan`, HEAD `2cf63c81a7122c5d549c18cbfef9a529329dec60` as verified via GitHub connector. It adds `tools/pack.py`, `tools/onepass_to_pack.py`, `docs/PACK_FORMAT.md`, tests, bundled borders, and upstream renderer support for `--assets`, `--asset-plan`, and `--make-pack`. PR remains unmerged; do NOT merge or silently replace the OpenAI branch without compatibility tests.
- User provided `potomac-mills-to-wise-pack.zip`, schema `route-video-pack-v1`, 496 ZIP entries, of which 495 are manifest-listed files; all 495 SHA-256 and size checks **passed** in a local independent archive validation. Contains 478 vector-tile PBF files under `http/tiles.openfreemap.org/planet/...`. Route identifiers in pack: `Potomac Mills, Woodbridge VA` -> `Wise, Wise County, Virginia`. Use those exact strings with PR #4's strict matching. Archive is a conversation attachment, not in this git branch.
- Immediate next task: test **actual** `routevid3.py` from PR #4 with this pack and an isolated cache, generate stills/missing.json; then integrate downloader to produce packs/needs top-ups and compare to Claude's reference stills. Merely validating the archive is NOT proof that native rendering works in the current environment.
- Important: PR #4 `docs/PACK_FORMAT.md` is source of truth for URL-to-path canonicalization and pack security. Don't build a second incompatible pack format or use the older SHA1 cache seeder if new pack reader works.

## 2026-10-31: Cross-assistant native compatibility PASSED
- Verified uploaded main ZIP corresponds to merged PR #4 commit `32e5c2fbecd37b41f87094ebcccc1829e85c1cff`.
- Local isolated test with user-supplied `potomac-mills-to-wise-pack.zip` and Claude `compat-test-potomac-wise(1).zip`: 11 unit tests passed; planning output matched expected_plan.txt exactly; ten offline native MapLibre stills compared to reference and yielded `RESULT: map areas match`.
- Full exact offline renderer completed 4207 frames in 198 sec and produced 175.33-sec silent MP4 (31,306,833 bytes); worker summary `net=0`, `misses=0`; missing.json absent. This confirms **real camera/turn native rendering**, no image-crop substitute.
- Video and `COMPATIBILITY_RESULT.md` live as user conversation artifacts in this ChatGPT session; they have not been committed to GitHub. In future sessions recover from conversation or request uploads.
- NEXT: adopt upstream pack and asset-plan into OpenAI branch, retire legacy SHA1 offline adapter where possible; implement browser pack-v1 creation and needs top-ups, then narration. Preserve `main` as renderer of record.

## 2026-11-01: Narrated Potomac Mills -> Wise milestone and next route
- User confirmed the completed narrated video works. Local artifact (conversation, not git): `/mnt/data/narrated-wise/potomac-wise-narrated.mp4` and contact sheet `/mnt/data/narrated-wise/contact-sheet.jpg`.
- Renderer: merged `main` / PR #4 native MapLibre `routevid3.py`; same verified `route-video-pack-v1` asset pack, completely offline (0 network requests / 0 missing map assets).
- Actual persisted invocation parameters in `/mnt/data/narrated-wise/args.json`: `src="Potomac Mills, Woodbridge VA"`, `dst="Wise, Wise County, Virginia"`, `from_label="Potomac Mills"`, `to_label="Wise, Virginia"`, `narrate="/mnt/data/kokoro-v1"`, `voice="af_heart"`, `style="https://tiles.openfreemap.org/styles/liberty"`, `crf=24`, `maxrate="3M"`, `assets="/mnt/data/potomac-mills-to-wise-pack.zip"`, `cache="/mnt/data/compat-live/cache"`. Runtime paths are workspace-specific, not portable.
- Reproduction from initialized working folder: `python3 routevid3.py --assets /path/to/potomac-mills-to-wise-pack.zip --narrate /path/to/kokoro-v1 --voice af_heart --work /path/to/new-work --from-label "Potomac Mills" --to-label "Wise, Virginia" --plan-only`; then `python3 routevid3.py --work /path/to/new-work --out narrated.mp4`. Inspect `plan_check.json`, `worker.log`, `missing.jsonl`, `subs.srt`, contact sheet, ffprobe audio/video and `tools/check_audio.py` where a local ASR is available. Invocation uses merged main, NOT experimental SHA1 adapter.
- Kokoro uploaded by user and tested: `model.onnx` (~311 MiB), `tokenizer.json`, `af_heart(1).bin` (renamed as `voices/af_heart.bin`) organized under `/mnt/data/kokoro-v1/{onnx/model.onnx,tokenizer.json,voices/af_heart.bin}`; compatible offline Python 3.13 Linux x86-64 wheels from `narration-wheels-py313-linux-x86_64.zip` installed in an isolated environment. Real 9.3-sec WAV smoke test worked, user approved the voice. Model weights MUST NOT be committed to git.
- Render output: 3m02s narrated Potomac Mills -> Wise, 20 camera transitions, 21 speech segments, subtitles present, no clipping; user reports video works. It is a route *preview*, not live navigation.
- Next route: **Woodbridge, VA -> Billings, MT**. Existing `route-video-onepass-v2` ZIP in session `route-assets-woodbridge-billings-onepass.zip` is only sampled tiles (240); do not claim it covers native close-ups. Convert via `tools/onepass_to_pack.py`, run merged renderer `--asset-plan` offline to enumerate exact needs, then arrange one pack/top-up supplied by Claude or browser. Only render final narrated MP4 when `missing` is zero. Preserve compact title/footer styling desired by user.

## 2026-11-01 Woodbridge -> Billings actual start
- Converted existing onepass `route-assets-woodbridge-billings-onepass.zip` into `route-video-pack-v1` at `/mnt/data/billings-next/partial-pack.zip`, 252 manifest members (249 map resources), route identifiers `Woodbridge, Virginia` -> `Billings, Montana`. This is **partial**, not final.
- Successfully ran `routevid3.py --assets <partial-pack> --work /mnt/data/billings-next/work --plan-only`. It planned **228-second timeline, 26 camera flights** with turn information; route labels were missing locality names because `reverse.json` was not fully populated. Do not narrate unverified coordinates.
- Attempted `--asset-plan /mnt/data/billings-next/needs.json` with a fresh isolated cache plus portable native MapLibre v6.4.1. Worker immediately reported **61 missing raster OpenFreeMap natural_earth/ne2sr resources in the opening view** and ended in a segfault before a complete `needs.json` could be written. `/mnt/data/billings-next/work/missing.json` has the partial 61 URL list, **not exhaustive**. Do not claim a complete plan or successful video render.
- For true native offline render: get complete Billings `--make-pack` from an internet-enabled Claude environment using current merged main, or fix the MapLibre missing-asset planner to survive blank raster resources and generate full `needs.json`. Then render using `--assets complete-pack.zip --narrate /path/to/kokoro-v1 --voice af_heart`, verify zero missing and audio. The one-pass pack alone is insufficient for distant route close-ups. The user requested this continuation; both git handover and partial pack were prepared.
