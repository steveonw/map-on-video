# Route Briefing Video: Handout for AI Reviewers

Oct 30, 2026 · steveonw

## How to use this handout

Paste this whole page into each AI with the prompt below, then put the answers side by side using the grid in the last section. Ask every AI the same thing, in a fresh chat, so the answers can be compared fairly.

```
I'm building a tool that turns a driving route (A to B) into a short, watchable, offline video. Below is a handout describing what exists, the design decisions, and the open problems. Please answer the numbered questions in the "Questions for reviewers" section using the answer template at the end. Be concrete and critical: name specific techniques, data sources, libraries, or products where you can, say what you would cut, and flag anything you think is a bad idea. If you're not sure about a fact, say so instead of guessing.

[paste the handout here]
```

Tips for getting useful answers:

- Attach one of the demo videos or a few screenshots if the AI accepts files. Reviewers judge visuals much better when they can see them.
- If an answer is vague, follow up with "Give me the one change you'd make first, and how you'd build it."
- Keep the AI's name and the date with its answers. Products change fast.

## The idea in plain words

It's like Google Maps, but as a video: you enter a start and a destination and get a 1 to 4 minute MP4 that walks you through the whole trip before you drive it. Because it's a plain video file, it plays offline on any phone or player, with no app and no signal.

- **Who it's for:** people facing a long or unfamiliar drive who want to get the route into their head ahead of time. For example, someone driving from New York to Los Angeles, or to a rural town they've never visited.
- **What you see:** a map of the whole trip, a red line drawn across it as the trip progresses, close-up street maps popping into a corner before each important turn, and a strip along the bottom with miles done, miles left, driving time left and the next turn.
- **How you use it:** watch it once before the trip. Drag the video's slider to see any part of the route. Jump to a specific turn using the video's chapter list.
- **The look:** an adventure-movie "map table", with an old paper map of the region and more detailed map sheets laid on top, overlapping, with the red route line crossing them.

It's a preview, not turn-by-turn navigation, and it doesn't try to replace a GPS app.

## What exists today

A working prototype: one Python script that goes from two place names to a finished, chaptered MP4, with no hand-editing. It has been tested on three routes.

| Demo route | Distance | Video length | What it showed |
| --- | --- | --- | --- |
| Richmond, VA to Virginia Beach, VA | 108 mi | 1 min 16 s | First run of the general tool on a route it had never seen; turns and layout chosen automatically |
| New York City Hall to Hollywood & Vine | 2,800 mi | 3 min 15 s | Map table with 9 overlapping sheets, 13 state banners, 26 chapters, slowed-down turns |
| Potomac Mills (Woodbridge, VA) to Wise, VA | 379 mi | 2 min 11 s | First prototype: one map, dotted trail, corner turn maps, scrub bar exactly proportional to distance |

**What's on screen**

- An aged-paper overview map, with detailed OpenStreetMap sheets laid along the route. Each sheet has a shadow, a border and a caption such as "MAP 3 OF 6 · OHIO · INDIANA".
- A red route line that draws as the trip goes, with a dotted preview of the road ahead and a pulsing position dot.
- Numbered turn markers that change color once passed.
- Turn close-ups: a street-level map pops into a corner about 3 seconds before each key turn, showing the instruction and the moving dot.
- A small locator map showing the whole trip, the current sheet and the camera's view.
- "Now entering \<State>" banners at border crossings.
- A bottom strip with the route name, current state, miles done and left, driving time left, the next turn and its distance, and a progress bar marked with turns and borders.
- Intro and arrival title cards, and chapter markers for every turn and border.

**How it's built (one script, in order)**

1. Look up both places (Nominatim, from OpenStreetMap).
2. Get the driving route with turn-by-turn steps (OSRM's free public router).
3. Pick the key turns automatically and write plain-English instructions, e.g. "Take the exit for I-76 West toward Denver".
4. Find state or province crossings (Natural Earth border data).
5. Choose a map zoom and lay out the overlapping sheets along the route.
6. Download and cache the map tiles (OpenStreetMap), stopping if a run would need more than a set budget.
7. Assemble the "map table" image, then render each frame: camera position, route line, close-ups, banners and strip.
8. Encode with ffmpeg (H.264, 24 fps, 1080p or 720p) and add chapter markers.

Tools: Python with Pillow, NumPy and GeoPandas, plus ffmpeg. Speed: about 10 frames per second, so a 3-minute video takes 7–8 minutes to render. File size: about 160 MB at 1080p for 3 minutes; 720p is roughly a third of that.

## Design decisions and why

Each row is a choice we made on purpose. Reviewers are welcome to challenge any of them.

| Decision | What we chose | Why | What it costs |
| --- | --- | --- | --- |
| Pacing | Slow down and zoom in near key turns (a "linear" option also exists) | Turns that bunch up in cities (3 turns in the first 25 miles out of NYC) would otherwise flash by in under a second | The video's slider no longer matches distance exactly; the on-screen strip still shows true miles |
| Turn close-ups | A picture-in-picture box in a corner, not a cut-away | The main map never leaves the screen, and time keeps flowing | The box can cover part of the map; it's placed on the side away from the position dot |
| Map layering | An aged overview plus overlapping detailed sheets at their true positions | Gives the "paper maps on a table" feel and shows the jump from national to regional to street level | Sheets can't be rotated: even 1° makes the route line drift off the roads |
| Route line | A red line in the style of an adventure-movie map, plus a dotted preview ahead | Reads instantly as progress, and shows what's coming | Earlier tests used dots every few miles; the line looks better but has to follow the road closely |
| Which turns count | Automatic: a change to a road you then stay on for a meaningful distance, plus "stay on" splits where another major road leaves | Keeps 5–14 turns per trip instead of 70 raw steps | Misses some real decisions, like a roundabout onto a short road |
| Start and end | Everything in the first and last \~2% of the trip becomes one "Start" and one "Destination" close-up | City streets at either end would otherwise produce a burst of tiny turns | The early street-by-street directions are summarised, not spelled out |
| Format | Plain MP4 with chapters, 16:9 | Works offline everywhere; chapters give a turn list for free | Not interactive; the turn list only shows in players that support chapters (e.g. VLC) |
| Data | Free OpenStreetMap maps, OSRM routing, Natural Earth borders | No cost and no API keys for a prototype | Not allowed for a public app at scale; routes can differ from Google's choice |

## Known problems and limits

The biggest open issue is that the free map and routing services can't support a real product. Everything else is polish or features.

1. **Map data licensing at scale.** OpenStreetMap's free tile servers and the OSRM demo router are for light personal use. A public app would need its own map server or a paid provider, which changes the cost and the look.
2. **Turn picking is about 80% right.** It missed the Gordonsville, VA roundabout and kept a strange detour near Chicago that the router produced. Today a person has to review the turn list before rendering.
3. **Routes can differ from what drivers expect.** The free router sent the Virginia trip through Orange and Gordonsville rather than I-95 to I-64. Its driving times also run long (50 hours coast to coast).
4. **Rendering is slow.** 7–8 minutes for a 3-minute video on a 2-core machine.
5. **Files are large.** 160 MB at 1080p for 3 minutes.
6. **Rural maps look empty.** At regional zoom, sheets for Nebraska or Utah show almost nothing, because the map simply has little there at that scale.
7. **No sound.** There's no narration yet, so the video only works while you're watching the screen.
8. **Pacing trade-off.** Neither slowing down at turns nor keeping a strictly linear timeline is clearly right; see question 2.
9. **Text-only instructions.** The close-ups don't show lane guidance, exit numbers on every turn, or road-sign graphics.
10. **Single trip, single day.** No waypoints, overnight stops, fuel or rest stops.

## Questions for reviewers

Please answer all eight, briefly and concretely. If you'd only answer one, answer question 1.

1. **Would people use this?** Who would actually watch a route video instead of just opening a GPS app, and in what situation? Name the strongest use case and the weakest one. Is "offline" a real selling point or a niche?
2. **Pacing.** Should the video slow down at turns (better for learning the turns, but the slider no longer matches distance) or stay strictly linear (the slider is a true "how far along" control)? Is there a better third option?
3. **Picking key turns.** Given a router's step list (type, road name, road number, distance, destination signs), how would you decide which 5–15 maneuvers matter for a driver? Name specific rules or methods, and any existing tool that already does this well.
4. **Map data for a real product.** Which map tile and routing providers would you use if this became an app with users, and roughly what would they cost? What would you self-host, if anything?
5. **What to add next.** Rank these by value to a driver: narration ("in two miles, keep left onto I-15"), fuel and rest stops, overnight splits for multi-day trips, landmark and city callouts, terrain and mountain-pass warnings, lane guidance graphics, a printable turn sheet. Add anything missing.
6. **Visual design.** Does the adventure-map look help or get in the way? What would make the turn close-ups easier to read at a glance, especially on a phone?
7. **Format and delivery.** MP4 with chapters, an interactive web page, an animated map inside an app, or something else? Should there be a vertical phone version?
8. **What would you cut?** What in this design is unnecessary, risky, or a bad idea, and why?

## Answer template and comparison grid

Reviewers fill in the template; you fill in the grid as the answers come in, one row per AI.

**Template for reviewers to copy**

```
Reviewer (AI name and version):
Date:

1. Would people use this?
   Strongest use case:
   Weakest use case:
   Is offline a real selling point?
2. Pacing (slow at turns / linear / other):
   Why:
3. How to pick key turns (rules or methods; existing tools):
4. Map and routing providers for a real product (and rough cost):
5. Ranked additions (1 = most valuable):
6. Visual design: keep, change, or drop:
7. Best format and delivery:
8. What I would cut:

The one change I'd make first, and how I'd build it:
```

**Comparison grid**

| Reviewer | Date | Strongest use case | Pacing pick | Top addition | What they'd cut | First change they'd make | Usefulness (1–5) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Gemini Pro Latest | Oct 31, 2026 | Fleet, RV and anxious drivers on high-stakes unfamiliar drives; sharing a trip in a group chat | Narration sets the time spent at each turn; a separate distance ruler in the strip | Narration | Continuous camera panning (hold still on each sheet); the locator when a close-up is showing | Narration plus a still camera per sheet, and switch routing to Valhalla |  |
| Claude Opus Latest | Oct 31, 2026 | The unfamiliar last 20–50 miles; sending guests "how to get to our place" | Linear travel that pauses at each key turn | Narration | Sheets on long interstate stretches; banners for short state crossings; the linear option | Narration timed to the turns, using the lesson pipeline |  |
| Grok Latest | Oct 31, 2026 | The last 15 minutes of an unfamiliar drive; sending a file to someone who won't install an app | One full-frame chapter per decision; cut past empty highway | Narration | State banners, the 9 sheets, the paper texture, cross-country as the pitch | A reviewed turn list, one full-frame chapter and one sentence per turn |  |
| GPT Astra Latest | Oct 31, 2026 | A reusable, verified arrival briefing for a venue, campground or hospital | Variable; the slider is a time control, distance shown separately | A route approval and correction step | State banners, elaborate sheet effects, fuel planning, live-style countdowns | Route approval before more visuals; then test with real visitors |  |
| Muse Wonder | Oct 31, 2026 | A long, high-stakes unfamiliar drive learned the night before | Strictly linear, with turns as paused inserts | Narration | The locator map; 1080p as default; most state banners; the linear option | Narration with per-sentence timestamps driving the render |  |

Where three or more reviewers agree, that's a strong signal. Where they split, it's worth a closer look before deciding.
