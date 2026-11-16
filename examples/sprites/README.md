# Example pixel-art sprites

The default sprite set for `worldtrip.py --sprites examples/sprites`: AI-generated from the prompts in `request_pack/`,
free to use in this project.

| File | What | Layout (32x32 frames, drawn at 8x on #FF00FF) |
|---|---|---|
| `P1-01.png` | red family car, top-down | 8 directions: up, up-right, right, ... up-left |
| `P1-02.png` | small jet, top-down | 8 directions (only the nose-up frame is used; the rest are rotated from it) |
| `P1-03.png` | traveller, side view, facing right | walk x8 / idle x4 / wave x4 |
| `P2-04.png` | map pin and arrival sparkle | pin bouncing in x6 / sparkle x6 |

Try them: `python3 worldtrip.py --trip examples/corridor_h_sprites.json --work w --sprites examples/sprites --out test.mp4`
(a 29 s drive from Davis to Parsons, WV).

**New sprites in the same style:** give `request_pack/` (zipped) and `request_pack/MASTER_PROMPT.txt` to an image
tool, change the descriptions in `PROMPTS.md` and the `prompt.txt` files (another car, a bus, a different traveller), and
keep the sheet sizes and the magenta background. `tools/sprites.py` checks nothing beyond the layout: keep frames on
the 8 px grid and in the order above.
