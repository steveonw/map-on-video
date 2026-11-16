"""Pixel-art sprites for worldtrip.py (--sprites DIR): a car on the roads, a plane in the air, map pins that bounce in
with a sparkle on arrival, and a traveller who waves at the end.

DIR holds the four sheets of the sprite request pack, drawn at 8x scale on flat magenta (#FF00FF):
  P1-01.png  car, top-down, 8 directions in one row (up, up-right, right, ... up-left)
  P1-02.png  plane, top-down, 8 directions (only the first, nose up, is used: the rest are rotated from it)
  P1-03.png  traveller, side view facing right: walk x8 / idle x4 / wave x4
  P2-04.png  map pin bouncing in x6 / arrival sparkle x6
Each frame is a 32x32 cell. Frames are reduced to 1x, the magenta keyed out, and scaled back up by a whole number
with nearest-neighbour, so pixels stay crisp.
"""
import os
import numpy as np
from PIL import Image

CELL, SRC_SCALE = 32, 8


def load_1x(path):
    """8x art -> 1x RGBA, sampling each 8x8 block's centre; magenta becomes transparent."""
    a = np.array(Image.open(path).convert("RGB"))[SRC_SCALE // 2::SRC_SCALE, SRC_SCALE // 2::SRC_SCALE].astype(np.uint8)
    mag = (a[..., 0] > 215) & (a[..., 1] < 60) & (a[..., 2] > 215)
    return np.dstack([a, np.where(mag, 0, 255).astype(np.uint8)])


def cells(rgba):
    h, w = rgba.shape[:2]
    return [[rgba[r * CELL:(r + 1) * CELL, c * CELL:(c + 1) * CELL] for c in range(w // CELL)] for r in range(h // CELL)]


def scale2x(a):
    """EPX / Scale2x: smooths staircase edges so a rotation doesn't shred thin lines."""
    h, w = a.shape[:2]; p = np.pad(a, ((1, 1), (1, 1), (0, 0)), mode="edge")
    B, D, E, F, H = p[:-2, 1:-1], p[1:-1, :-2], p[1:-1, 1:-1], p[1:-1, 2:], p[2:, 1:-1]
    eq = lambda x, y: (x == y).all(-1)
    out = np.zeros((h * 2, w * 2, 4), np.uint8)
    out[0::2, 0::2] = np.where((eq(D, B) & ~eq(B, F) & ~eq(D, H))[..., None], D, E)
    out[0::2, 1::2] = np.where((eq(B, F) & ~eq(B, D) & ~eq(F, H))[..., None], F, E)
    out[1::2, 0::2] = np.where((eq(D, H) & ~eq(D, B) & ~eq(H, F))[..., None], D, E)
    out[1::2, 1::2] = np.where((eq(H, F) & ~eq(D, H) & ~eq(B, F))[..., None], F, E)
    return out


def rotsprite(frame, deg):
    """RotSprite-style rotation (clockwise for negative deg in PIL terms): Scale2x x3, rotate nearest, sample back."""
    if deg % 90 == 0: return np.rot90(frame, k=int(deg // 90) % 4).copy()
    big = frame
    for _ in range(3): big = scale2x(big)
    im = Image.fromarray(big, "RGBA").rotate(deg, resample=Image.NEAREST, expand=False)
    return np.array(im)[SRC_SCALE // 2::SRC_SCALE, SRC_SCALE // 2::SRC_SCALE]


def _img(a, scale): return Image.fromarray(a, "RGBA").resize((CELL * scale, CELL * scale), Image.NEAREST)


class Pack:
    """Scaled, ready-to-paste PIL images. car[d] / plane[d] for 8 directions (0 = up, clockwise), pin[0..5],
    sparkle[0..5], walk[0..7], idle[0..3], wave[0..3]."""
    def __init__(self, folder, scale=3):
        p = lambda n: os.path.join(folder, n)
        car = cells(load_1x(p("P1-01.png")))[0]
        up = cells(load_1x(p("P1-02.png")))[0][0]
        trav = cells(load_1x(p("P1-03.png")))
        fx = cells(load_1x(p("P2-04.png")))
        self.scale = scale
        self.car = [_img(f, scale) for f in car[:8]]
        self.plane = [_img(rotsprite(up, -45 * i), scale) for i in range(8)]      # one plane, turned: identical in every direction
        self.walk = [_img(f, scale) for f in trav[0][:8]]
        self.idle = [_img(f, scale) for f in trav[1][:4]]
        self.wave = [_img(f, scale) for f in trav[2][:4]]
        self.pin = [_img(f, scale) for f in fx[0][:6]]
        self.sparkle = [_img(f, scale) for f in fx[1][:6]]
        self.size = CELL * scale
        # where the pin's tip sits in its settled frame (bottom-most opaque pixel), so pins stand exactly on a stop
        a = np.array(self.pin[5])[..., 3]; ys, xs = np.nonzero(a)
        self.pin_tip = (int(xs[ys == ys.max()].mean()), int(ys.max()))


class Heading:
    """8-way sprite direction from a screen-space heading, with hysteresis so a wiggly road doesn't make it flicker."""
    def __init__(self, hold_deg=12): self.d = None; self.hold = hold_deg
    def __call__(self, dx, dy):
        ang = (np.degrees(np.arctan2(dx, -dy)) + 360) % 360           # 0 = up, clockwise, screen y points down
        if self.d is not None:
            off = abs(((ang - self.d * 45) + 180) % 360 - 180)
            if off <= 22.5 + self.hold: return self.d
        self.d = int(round(ang / 45)) % 8; return self.d


def paste_center(fr, im, x, y):
    fr.paste(im, (int(round(x - im.width / 2)), int(round(y - im.height / 2))), im)


def paste_feet(fr, im, x, y, foot_y=None):
    """Bottom-centre anchor: the sprite's lowest opaque row sits on y."""
    fy = foot_y if foot_y is not None else im.height
    fr.paste(im, (int(round(x - im.width / 2)), int(round(y - fy))), im)
