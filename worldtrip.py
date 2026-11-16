#!/usr/bin/env python3
"""worldtrip - a narrated overview video of a multi-leg trip: drives (OSRM roads) and flights (great-circle arcs).

Companion to routevid3.py. Where routevid3 briefs one drive turn by turn, worldtrip shows a whole journey
(a round-the-world trip, a fly-drive holiday) at country scale: one held, north-up camera per narrated line,
smooth van Wijk flights between them, the red road line and blue flight arcs revealed as a dot (or a plane)
moves along. Longitudes are unwrapped, so routes and cameras cross the date line without jumping.

It reuses routevid3's native MapLibre worker (extracted from routevid3.py, so there is one copy of it),
tools/narrate.py for the voice and the same OpenFreeMap tiles and disk cache.

The trip file (see examples/woodbridge_world.json) lists stops and legs; each leg is a drive or a flight with
hand-written narration ("text", spoken) and a card line ("card", on screen). A long drive can be split into
several holds with "to_mile" (miles from the start of that leg).

  python3 worldtrip.py --trip examples/woodbridge_world.json --work work --narrate voices/kokoro-v1 --out world.mp4
  ... --plan-only        legs, distances, borders, holds and the script
  ... --stills 2,30,60   a few frames as JPGs
"""
import argparse, json, math, os, re, subprocess, sys, time, urllib.request
import numpy as np
from PIL import Image, ImageDraw, ImageFont

MI = 1609.344
W, H, FPS = 1920, 1080, 24
VW, VH, RATIO = 1280, 720, 1.5
_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _here)
from tools import speech as sp

ap = argparse.ArgumentParser()
ap.add_argument("--trip", required=True)
ap.add_argument("--work", default="worldtrip_work")
ap.add_argument("--cache", default=os.path.expanduser("~/.cache/routevid"))
ap.add_argument("--ua", default="RouteVideo/3.0 (+https://github.com/steveonw/map-on-video)", help="User-Agent for OSRM and tiles")
ap.add_argument("--narrate", metavar="MODEL_DIR"); ap.add_argument("--voice", default="af_heart")
ap.add_argument("--style", default="https://tiles.openfreemap.org/styles/liberty")
ap.add_argument("--out", default="worldtrip.mp4"); ap.add_argument("--crf", type=int, default=24); ap.add_argument("--maxrate", default="3M")
ap.add_argument("--plan-only", action="store_true"); ap.add_argument("--stills")
ap.add_argument("--sprites", metavar="DIR", help="pixel-art sprite sheets (P1-01..P2-04, see tools/sprites.py): car, plane, pins, traveller")
ap.add_argument("--sprite-scale", type=int, default=3, help="whole-number scale for 32x32 sprites (3 = 96 px)")
ap.add_argument("--draft", metavar="OUT_JSON", help="fill in missing holds, cards, narration and flight times from the route data, write the trip file, stop")
ap.add_argument("--contact-sheet", metavar="JPG", help="one image with a thumbnail of every narrated view, then stop")
A = ap.parse_args()
WORK = os.path.abspath(A.work); os.makedirs(WORK, exist_ok=True); os.makedirs(A.cache, exist_ok=True)
TRIP = json.load(open(A.trip))

def http(url, binary=False):
    for k in range(4):
        try:
            b = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": A.ua}), timeout=120).read()
            return b if binary else json.loads(b)
        except Exception as e:
            if k == 3: raise
            time.sleep(2 + 2 * k)
def cached(name, fn):
    p = f"{A.cache}/{name}.json"
    if os.path.exists(p): return json.load(open(p))
    v = fn(); json.dump(v, open(p, "w")); time.sleep(1.1); return v
def hav(a, b):
    r = math.pi / 180; p1, p2 = a[1] * r, b[1] * r
    return 2 * 3958.8 * math.asin(math.sqrt(math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin((b[0] - a[0]) * r / 2) ** 2))
def great_circle(a, b, n=240):
    r = math.pi / 180; la1, lo1, la2, lo2 = a[1] * r, a[0] * r, b[1] * r, b[0] * r
    d = 2 * math.asin(math.sqrt(math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2))
    out = []
    for f in np.linspace(0, 1, n):
        A_, B_ = math.sin((1 - f) * d) / math.sin(d), math.sin(f * d) / math.sin(d)
        x = A_ * math.cos(la1) * math.cos(lo1) + B_ * math.cos(la2) * math.cos(lo2)
        y = A_ * math.cos(la1) * math.sin(lo1) + B_ * math.cos(la2) * math.sin(lo2)
        z = A_ * math.sin(la1) + B_ * math.sin(la2)
        out.append([math.degrees(math.atan2(y, x)), math.degrees(math.atan2(z, math.hypot(x, y)))])
    return out
def unwrap(c, start_near=None):
    c = np.array(c, float)
    c[:, 0] = np.degrees(np.unwrap(np.radians(c[:, 0])))
    if start_near is not None: c[:, 0] += round((start_near - c[0, 0]) / 360) * 360
    return c

# ====================================================================== legs -> one continuous trip line (unwrapped longitudes)
STOPS = {s["id"]: s for s in TRIP["stops"]}
LEGS, parts, cum_parts, m = [], [], [], 0.0
prev_lon = None
for k, lg in enumerate(TRIP["legs"]):
    a, b = STOPS[lg["from"]], STOPS[lg["to"]]
    if lg["mode"] == "drive":
        r = cached(f"osrm_{a['lon']:.5f}_{a['lat']:.5f}_{b['lon']:.5f}_{b['lat']:.5f}", lambda: http(
            f"https://router.project-osrm.org/route/v1/driving/{a['lon']},{a['lat']};{b['lon']},{b['lat']}?overview=full&geometries=geojson&steps=true"))
        R = r["routes"][0]; c = R["geometry"]["coordinates"]; dist, secs = R["distance"] / MI, R["duration"]
    else:
        c = great_circle([a["lon"], a["lat"]], [b["lon"], b["lat"]]); dist, secs = hav(c[0], c[-1]), lg.get("hours", 0) * 3600
    c = unwrap(c, prev_lon); prev_lon = c[-1, 0]
    seg = np.array([hav(c[i], c[i + 1]) for i in range(len(c) - 1)]); cm = np.concatenate([[0], np.cumsum(seg)])
    cm = cm * dist / max(cm[-1], 1e-9)
    LEGS.append(dict(i=k, mode=lg["mode"], a=a, b=b, m0=m, m1=m + dist, dist=dist, secs=secs, spec=lg))
    parts.append(c if not parts else c[1:]); cum_parts.append(m + (cm if len(parts) == 1 else cm[1:])); m += dist
coords = np.concatenate(parts); cum = np.concatenate(cum_parts); TOTAL = m
for i in range(1, len(cum)):
    if cum[i] <= cum[i - 1]: cum[i] = cum[i - 1] + 1e-7
def lonlat_at(mm): return [float(np.interp(mm, cum, coords[:, 0])), float(np.interp(mm, cum, coords[:, 1]))]
def leg_at(mm): return next((L for L in LEGS if mm <= L["m1"] + 1e-9), LEGS[-1])

# ====================================================================== borders: countries (Natural Earth admin-0), US states (bundled admin-1)
NE = f"{A.cache}/ne"; os.makedirs(NE, exist_ok=True)
crossings = []      # (mile, region name), drives only
try:
    import geopandas as gpd
    base = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/50m_cultural/ne_50m_admin_0_countries"
    for ext in ("shp", "shx", "dbf", "prj", "cpg"):
        if not os.path.exists(f"{NE}/admin0.{ext}"): open(f"{NE}/admin0.{ext}", "wb").write(http(f"{base}.{ext}", binary=True))
    adm0 = gpd.read_file(f"{NE}/admin0.shp", encoding="utf-8")[["NAME", "geometry"]]
    adm1 = gpd.read_file(os.path.join(_here, "data", "admin1.geojson"))
    adm1 = adm1[adm1["admin"] == "United States of America"][["name", "geometry"]]
    for L in LEGS:
        if L["mode"] != "drive": continue
        sm = np.arange(L["m0"], L["m1"], max(0.5, L["dist"] / 3000))
        lo, la = np.interp(sm, cum, coords[:, 0]), np.interp(sm, cum, coords[:, 1])
        lo = (lo + 180) % 360 - 180
        pts = gpd.GeoDataFrame(geometry=gpd.points_from_xy(lo, la), crs=4326)
        n0 = gpd.sjoin(pts, adm0, how="left", predicate="within").sort_index()["NAME"].groupby(level=0).first()
        n1 = gpd.sjoin(pts, adm1, how="left", predicate="within").sort_index()["name"].groupby(level=0).first()
        names = [s1 if c0 == "United States of America" and isinstance(s1, str) else c0 for c0, s1 in zip(n0, n1)]
        names = [{"United States of America": "United States"}.get(x, x) for x in names]
        names = list(np.array(names, dtype=object)); cur = None; raw = []
        for mm, nm in zip(sm, names):
            if isinstance(nm, str) and nm != cur: raw.append((float(mm), nm)); cur = nm
        for i, (mm, nm) in enumerate(raw):    # drop slivers (< 2 mi) unless it is where the leg ends
            nxt = raw[i + 1][0] if i + 1 < len(raw) else L["m1"]
            if (nxt - mm >= 2 or i == len(raw) - 1 or i == 0) and (not crossings or crossings[-1][1] != nm or crossings[-1][0] < L["m0"]):
                crossings.append((mm, nm))
except Exception as e:
    print("borders skipped:", e)
def region_at(mm):
    L = leg_at(mm)
    if L["mode"] == "flight": return "In the air"
    r = ""
    for c_m, nm in crossings:
        if c_m <= mm + 1e-6 and c_m >= L["m0"] - 1e-6: r = nm
    return r

# ====================================================================== segments: intro, one hold per leg part, outro

# ====================================================================== --draft: write the narration from the data (hand-written holds are kept)
def say_dist(mi):
    n = mi if mi < 100 else (round(mi / 10) * 10 if mi < 1000 else round(mi / 100) * 100)
    n = int(round(n / 5) * 5) if mi < 100 else int(n)
    if 1100 <= n < 2000 and n % 100 == 0: return sp.words(n // 100) + " hundred"     # "seventeen hundred"
    return sp.words(n)
def say_hours(h):
    h = round(h * 2) / 2; whole = int(h)
    if whole == 0: return "half an hour"
    return f"{sp.words(whole)}{' and a half' if h - whole else ''} hour{'s' if h > 1 else ''}"
def plain(name): return re.sub(r"\s*\([^)]*\)", "", name).strip()
def and_list(xs): return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1] if xs else ""
def big_cities(L):
    """Cities of 100,000+ (city proper) within 25 km of the road, in order of travel, not the leg's own ends."""
    try:
        import geopandas as gpd
        base = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/10m_cultural/ne_10m_populated_places_simple"
        for ext in ("shp", "shx", "dbf", "prj", "cpg"):
            if not os.path.exists(f"{NE}/places.{ext}"): open(f"{NE}/places.{ext}", "wb").write(http(f"{base}.{ext}", binary=True))
        pp = gpd.read_file(f"{NE}/places.shp", encoding="utf-8")
        pp = pp[pp["pop_min"] >= 100000][["name", "pop_min", "geometry"]].to_crs(3857)     # city proper, not metro (no suburbs)
        sm = np.arange(L["m0"], L["m1"], 1.0); lo = (np.interp(sm, cum, coords[:, 0]) + 180) % 360 - 180; la = np.interp(sm, cum, coords[:, 1])
        road = gpd.GeoDataFrame({"mile": sm}, geometry=gpd.points_from_xy(lo, la), crs=4326).to_crs(3857)
        near = gpd.sjoin_nearest(pp, road, max_distance=25000).sort_values("mile").drop_duplicates("name")
        out = []
        for _, r in near.iterrows():
            if min(r["mile"] - L["m0"], L["m1"] - r["mile"]) > 40: out.append((float(r["mile"]), r["name"], int(r["pop_min"])))
        return out
    except Exception as e:
        print("cities skipped:", e); return []
def regions_in(m0, m1):
    names = [region_at(m0 + 0.01)] + [nm for c_m, nm in crossings if m0 < c_m < m1]
    out = []
    for n in names:
        if n and n not in out: out.append(n)
    return out
def draft_leg(L, first_drive):
    a, b = plain(L["a"]["name"]), plain(L["b"]["name"]); hs = L["spec"].get("holds") or []
    if L["mode"] == "flight":
        hrs = L["spec"].get("hours") or round((L["dist"] / 500 + 0.5) * 2) / 2; L["spec"]["hours"] = hrs; L["secs"] = hrs * 3600
        i0, i1 = int(np.searchsorted(cum, L["m0"])), int(np.searchsorted(cum, L["m1"]))
        k = np.floor((coords[i0:i1 + 1, 0] + 180) / 360)
        dl = ""
        if len(k) and k.max() != k.min():
            dl = " You'll cross the International Date Line and " + ("gain back a day." if coords[i1, 0] > coords[i0, 0] else "lose a day.")
        hrs_card = f"{int(hrs)}½" if hrs % 1 else f"{int(hrs)}"
        auto = [dict(card=f"{a} to {b}, about {hrs_card} hours",
                     text=f"Fly from {a} to {b}: about {say_dist(L['dist'])} miles, roughly {say_hours(hrs)}.{dl}")]
    else:
        n = 1 if L["dist"] <= 600 else max(2, math.ceil(L["dist"] / 900)); cities = big_cities(L)
        cuts = [L["m0"]]
        for j in range(1, n):
            target = L["m0"] + L["dist"] * j / n; part = L["dist"] / n
            opts = [c_m for c_m, _ in crossings if L["m0"] < c_m < L["m1"] and abs(c_m - target) < 0.35 * part]
            cuts.append(min(opts, key=lambda c_m: abs(c_m - target)) if opts else target)
        cuts.append(L["m1"])
        kind = "states" if all(r in sp.US_ABBR for r in regions_in(L["m0"], L["m1"])) else "countries"
        nreg = len(regions_in(L["m0"], L["m1"])); auto = []
        hrs = L["secs"] / 3600
        for j in range(n):
            m0, m1 = cuts[j], cuts[j + 1]; regs = regions_in(m0, m1); inpart = [c for c in cities if m0 <= c[0] < m1]; allc = [c[1] for c in inpart]
            cs = [c[1] for c in sorted(sorted(inpart, key=lambda c: -c[2])[:4])]      # the 4 biggest, in the order you pass them
            past = f" past {and_list(cs)}" if cs else ""
            through = f"through {and_list(regs)}" if regs else ""
            if n == 1:
                text = (f"{'Drive' if first_drive else 'Next, drive'} from {a} to {b}: about {say_dist(L['dist'])} miles, around {say_hours(hrs)}"
                        + (f", {through}" if nreg > 1 else "") + (f",{past}." if cs else "."))
                card = f"{a} to {b}" + (f", past {and_list(cs[:2])}" if cs else "")
            elif j == 0:
                text = (f"{'Start with' if first_drive else 'Next,'} the drive from {a} to {b}: about {say_dist(L['dist'])} miles through {sp.words(nreg)} {kind}. "
                        f"First, head {through}{past}.")
                card = f"{a} to {(allc[-1] if allc else regs[-1])}, {through}"
            elif j == n - 1:
                text = f"Finally, {through}{past}, and on to {b}." if regs else f"Then on{past} to {b}."
                card = f"{(allc[0] if allc else regs[0])} to {b}, {through}"
            else:
                text = f"Then on {through}{past}."
                card = f"{(allc[0] if allc else regs[0])} to {(allc[-1] if allc else regs[-1])}, {through}"
            auto.append(dict(to_mile=None if j == n - 1 else round(m1 - L["m0"], 1), card=card, text=text))
    if not hs: return auto
    for h, d in zip(hs, auto):                         # keep what was written by hand, fill only the gaps
        for k_ in ("card", "text"): h.setdefault(k_, d[k_])
    return hs
if A.draft:
    nd = sum(L["mode"] == "drive" for L in LEGS); nf = len(LEGS) - nd; first_drive = True
    for L in LEGS:
        TRIP["legs"][L["i"]]["holds"] = draft_leg(L, first_drive and L["mode"] == "drive")
        if L["mode"] == "flight": TRIP["legs"][L["i"]]["hours"] = L["spec"]["hours"]
        if L["mode"] == "drive": first_drive = False
    home, end = plain(LEGS[0]["a"]["name"]), plain(LEGS[-1]["b"]["name"])
    loop = home == end and coords[-1, 0] - coords[0, 0] >= 300
    TRIP.setdefault("title", f"Around the World from {home}" if loop else f"{home} to {end}")
    TRIP.setdefault("subtitle", f"{nd} drive{'s' if nd != 1 else ''}  ·  {nf} flight{'s' if nf != 1 else ''}  ·  {TOTAL:,.0f} miles")
    TRIP.setdefault("short", f"{home}  →  around the world  →  {end}" if loop else f"{home}  →  {end}")
    TRIP.setdefault("intro", f"This is your trip {'around the world, from ' + home + ' and back' if loop else 'from ' + home + ' to ' + end}: "
                             f"about {say_dist(TOTAL)} miles, with {sp.words(nd)} drive{'s' if nd != 1 else ''} and {sp.words(nf)} flight{'s' if nf != 1 else ''}.")
    dm = sum(L["dist"] for L in LEGS if L["mode"] == "drive")
    TRIP.setdefault("outro", (f"And you're home in {end}. " if loop else f"And you've arrived in {end}. ")
                    + f"That's about {say_dist(dm)} miles by car and {say_dist(TOTAL - dm)} in the air.")
    TRIP.setdefault("outro_title", f"Welcome home to {end}" if loop else f"You made it to {end}")
    json.dump(TRIP, open(A.draft, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(f"draft: {A.draft} ({sum(len(l['holds']) for l in TRIP['legs'])} holds). Review the text, then run with --trip {A.draft}")
    for l in TRIP["legs"]:
        for h in l["holds"]: print(f"  [{l['mode']:<6}] {h['card']}\n           {h['text']}")
    sys.exit()
for L in LEGS:
    if not L["spec"].get("holds"): raise SystemExit(f"leg {L['i'] + 1} has no holds: run with --draft out.json first, then --trip out.json")

SEGS = [dict(kind="intro", m0=0.0, m1=0.0, text=TRIP["intro"], title="Overview")]
NL = len(LEGS)
for L in LEGS:
    holds = L["spec"]["holds"]
    a = L["m0"]
    for j, h in enumerate(holds):
        b = L["m0"] + h["to_mile"] if h.get("to_mile") is not None else L["m1"]
        mode = "Drive" if L["mode"] == "drive" else "Flight"
        head = f"LEG {L['i'] + 1} OF {NL}  ·  {mode.upper()}" + (f"  ·  PART {j + 1} OF {len(holds)}" if len(holds) > 1 else "") \
            + f"  ·  {b - a:,.0f} MI"
        SEGS.append(dict(kind=L["mode"], leg=L["i"], m0=a, m1=b, text=h["text"], card=h["card"], head=head,
                         title=f"Leg {L['i'] + 1}: {h['card']}"))
        a = b
SEGS.append(dict(kind="outro", m0=TOTAL, m1=TOTAL, text=TRIP["outro"], title="Home"))

if True:     # the plan is printed on every run (it is short); --plan-only stops here
    print(f"trip: {TOTAL:,.0f} mi; {sum(L['dist'] for L in LEGS if L['mode'] == 'drive'):,.0f} mi driving "
          f"({sum(L['secs'] for L in LEGS if L['mode'] == 'drive') / 3600:.1f} h), {sum(L['dist'] for L in LEGS if L['mode'] == 'flight'):,.0f} mi flying")
    for L in LEGS:
        print(f"  leg {L['i'] + 1} {L['mode']:<6} {L['a']['name']} -> {L['b']['name']}: {L['dist']:,.0f} mi, {L['secs'] / 3600:.1f} h  (trip miles {L['m0']:,.0f}-{L['m1']:,.0f})")
    print("borders:", " | ".join(f"{c_m:,.0f}:{nm}" for c_m, nm in crossings))
    print("script:")
    for s in SEGS: print(f"  [{s['kind']:<6}] {s['m0']:8,.0f}-{s['m1']:8,.0f}  {s.get('card', '')!s:<40}  {s['text']}")
if A.plan_only: sys.exit()

# ====================================================================== cameras (Web Mercator, unwrapped longitudes)
def merc(lon, lat):
    s = math.sin(math.radians(max(-85, min(85, lat)))); return (lon + 180) / 360, 0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)
def unmerc(x, y): return x * 360 - 180, math.degrees(math.atan(math.sinh((0.5 - y) * 2 * math.pi)))
def fit_cam(m0, m1, pad=(150, 70, 70, 95), zmax=11.0):
    i0 = int(max(0, np.searchsorted(cum, m0) - 1)); i1 = int(min(len(cum), np.searchsorted(cum, m1) + 1))
    c = coords[i0:max(i1, i0 + 2)]; xs, ys = zip(*[merc(lo, la) for lo, la in c])
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys); top, right, left, bottom = pad
    aw, ah = VW - left - right, VH - top - bottom
    z = float(np.clip(math.log2(max(1e-9, min(aw / max(1e-12, (x1 - x0) * 512), ah / max(1e-12, (y1 - y0) * 512)))), 1.0, zmax))
    ws = 512 * 2 ** z; cx = (x0 + x1) / 2 + ((right - left) / 2) / ws; cy = (y0 + y1) / 2 + ((bottom - top) / 2) / ws
    lon, lat = unmerc(cx, cy); return dict(center=[lon, lat], zoom=z, bearing=0.0, pitch=0.0)
WV = TRIP.get("world_view", {})
WORLD = dict(center=[WV.get("lon", 15.0), WV.get("lat", 25.0)], zoom=WV.get("zoom", math.log2(VW / 512)), bearing=0.0, pitch=0.0)
prev = None
for s in SEGS:
    s["cam"] = dict(WORLD) if s["kind"] in ("intro", "outro") else fit_cam(s["m0"], s["m1"])
    if prev is not None:     # keep each camera within half a turn of the previous one, so moves never go the long way round
        c = s["cam"]["center"]; s["cam"]["center"] = [c[0] + round((prev[0] - c[0]) / 360) * 360, c[1]]
    prev = s["cam"]["center"]
def van_wijk(a, b, rho=1.42):
    ws = 512 * 2 ** a["zoom"]
    p0 = np.array(merc(*a["center"])) * ws; p1 = np.array(merc(*b["center"])) * ws
    u1 = float(np.hypot(*(p1 - p0))); w0 = max(VW, VH); w1 = w0 / 2 ** (b["zoom"] - a["zoom"]); r2 = rho * rho
    if u1 < 1e-6:
        return (lambda k: (a["center"], a["zoom"] + (b["zoom"] - a["zoom"]) * k)), abs(math.log(w1 / w0)) / rho
    def r(i):
        bb = (w1 * w1 - w0 * w0 + (-1 if i else 1) * r2 * r2 * u1 * u1) / (2 * (w1 if i else w0) * r2 * u1)
        return math.log(math.sqrt(bb * bb + 1) - bb)
    r0 = r(0); S = (r(1) - r0) / rho
    def f(k):
        s_ = k * S; w = math.cosh(r0) / math.cosh(r0 + rho * s_)
        u = w0 * ((math.cosh(r0) * math.tanh(r0 + rho * s_) - math.sinh(r0)) / r2) / u1
        p = (p0 + (p1 - p0) * u) / ws; return list(unmerc(*p)), a["zoom"] + math.log2(1 / w)
    return f, S
MOVES = []
for i in range(len(SEGS) - 1):
    f, S = van_wijk(SEGS[i]["cam"], SEGS[i + 1]["cam"])
    MOVES.append(dict(f=f, dur=float(np.clip(S / 1.6, 1.0, 3.0)), mile=SEGS[i]["m1"]))
def move_cam(mv, k):
    e = k * k * (3 - 2 * k); c, z = mv["f"](e); return dict(center=c, zoom=z, bearing=0.0, pitch=0.0)

# ====================================================================== narration timing (as routevid3: hold while speaking, move in the pause)
def want(s):
    if s["kind"] in ("intro", "outro"): return 6.0
    return 8.0 + 4.0 * min(1.0, (s["m1"] - s["m0"]) / 3000)
need_gap = [mv["dur"] + 0.45 for mv in MOVES] + [0.35]
if A.narrate:
    plan = {"title": TRIP["title"], "scenes": [{"title": s["title"], "lines": [{"text": sp.respell(s["text"])}]} for s in SEGS]}
    def run_narrate():
        json.dump(plan, open(f"{WORK}/plan.json", "w"), indent=1)
        r = subprocess.run([sys.executable, os.path.join(_here, "tools", "narrate.py"), f"{WORK}/plan.json", "--model-dir", A.narrate,
                            "--voice", A.voice, "--gap", "0.35", "--scene-gap", "0.35"], capture_output=True, text=True)
        if r.returncode: print(r.stdout[-2000:], r.stderr[-2000:]); raise SystemExit("narration failed")
        return [tuple(map(float, l.split("\t")[:2])) for l in open(f"{WORK}/labels.txt") if l.strip()]
    lab = run_narrate()
    for i, (s, (a, b), sc) in enumerate(zip(SEGS, lab, plan["scenes"])):
        sc["lines"][0]["pause_after"] = round(max(0.35, want(s) - (b - a), need_gap[i]), 2)
    lab = run_narrate(); AUDIO = f"{WORK}/narration.wav"; tail = plan["scenes"][-1]["lines"][0]["pause_after"]
    json.dump({**plan, "audio": "narration.wav", "timestamps": "labels.txt"}, open(f"{WORK}/plan_check.json", "w"), indent=1)
else:
    lab, t = [], 0.4
    for i, s in enumerate(SEGS):
        sp = len(s["text"].split()) / 2.4 + 0.3; lab.append((t, t + sp)); t += sp + max(0.35, want(s) - sp, need_gap[i])
    AUDIO = None; tail = 4.0
for s, (a, b) in zip(SEGS, lab): s["say0"], s["say1"] = a, b
SHOTS, t = [], 0.0
for i, s in enumerate(SEGS):
    end = max(s["say1"] + 0.1, SEGS[i + 1]["say0"] - 0.3 - MOVES[i]["dur"]) if i < len(SEGS) - 1 else s["say1"] + tail
    SHOTS.append(dict(kind="hold", seg=i, t0=t, t1=end)); s["t0"], s["t1"] = t, end; t = end
    if i < len(SEGS) - 1: SHOTS.append(dict(kind="move", seg=i, t0=t, t1=t + MOVES[i]["dur"])); t += MOVES[i]["dur"]
DUR = t
print(f"timeline: {DUR:.1f} s, {len(SEGS)} holds" + (" (narrated)" if AUDIO else ""))
for s in SEGS: print(f"  hold {s['t0']:6.1f}-{s['t1']:6.1f}  {s['kind']:<6} {s.get('card', '')}")
def ease(u): u = min(max(u, 0.0), 1.0); return u * u * (3 - 2 * u)
def shot_at(t): return next((sh for sh in SHOTS if t < sh["t1"]), SHOTS[-1])
def mile_at(t):
    sh = shot_at(t); s = SEGS[sh["seg"]]
    if sh["kind"] == "move" or s["kind"] in ("intro", "outro"): return s["m1"]
    u = (t - s["t0"]) / max(1e-6, s["t1"] - s["t0"] - 0.4)
    return s["m0"] + (s["m1"] - s["m0"]) * (0.3 * ease(u) + 0.7 * min(max(u, 0.0), 1.0))
def cam_at(t):
    sh = shot_at(t)
    if sh["kind"] == "move": return move_cam(MOVES[sh["seg"]], min(max((t - sh["t0"]) / (sh["t1"] - sh["t0"]), 0.0), 1.0))
    return SEGS[sh["seg"]]["cam"]

# ====================================================================== style and the map worker (routevid3's, extracted so there is one copy)
NODE = f"{A.cache}/node3"
if not os.path.exists(f"{NODE}/node_modules/@maplibre/maplibre-gl-native"):
    subprocess.run(["npm", "install", "--prefix", NODE, "@maplibre/maplibre-gl-native@6.4.1", "--silent"], check=True)
src = open(os.path.join(_here, "routevid3.py")).read()
from tools import pack as packlib
WJS = re.search(r'WORKER = r"""(.*?)"""', src, re.S).group(1)
WJS = WJS.replace("%PACK_JS%", packlib.PACK_JS).replace("%RATIO%", str(RATIO)).replace("%VW%", str(VW)).replace("%VH%", str(VH))
open(f"{NODE}/worker.js", "w").write(WJS)
style = cached("style_" + re.sub(r"[^a-z0-9]+", "_", A.style.lower()).strip("_")[:60], lambda: http(A.style))
for l in style["layers"]:
    if l["type"] == "symbol" and not re.search(r"city|country|state|shield", l["id"]): l.setdefault("layout", {})["visibility"] = "none"
cuts = sorted(set([0.0, TOTAL] + [s["m0"] for s in SEGS] + [s["m1"] for s in SEGS] + np.arange(0, TOTAL, TOTAL / 6000).tolist()))
feats = []
for a, b in zip(cuts, cuts[1:]):
    if b - a < 1e-6: continue
    i0, i1 = int(np.searchsorted(cum, a)), int(np.searchsorted(cum, b))
    pts = np.array([lonlat_at(a)] + coords[i0:i1].tolist() + [lonlat_at(b)])
    pts[:, 0] -= math.floor((pts[0, 0] + 180) / 360) * 360       # first point in [-180, 180); a feature may run past 180 (date line)
    feats.append({"type": "Feature", "properties": {"m0": a, "m1": b, "air": int(leg_at((a + b) / 2)["mode"] == "flight")},
                  "geometry": {"type": "LineString", "coordinates": pts.tolist()}})
style["sources"]["route"] = {"type": "geojson", "tolerance": 0, "data": {"type": "FeatureCollection", "features": feats}}   # 0: never drop short pieces at world zoom
style["sources"]["flightdot"] = {"type": "geojson", "data": {"type": "FeatureCollection", "features": []}}
style["sources"]["blabels"] = {"type": "geojson", "data": {"type": "FeatureCollection", "features": [
    {"type": "Feature", "properties": {"t": s["label"], "k": i}, "geometry": {"type": "Point", "coordinates": [s["lon"], s["lat"]]}}
    for i, s in enumerate(TRIP["stops"]) if s.get("label")]}}
AIR = ["==", ["get", "air"], 1]
W_CAS = ["interpolate", ["linear"], ["zoom"], 1, 4.0, 4, 5.5, 10, 8]
W_RED = ["interpolate", ["linear"], ["zoom"], 1, 2.2, 4, 3.0, 10, 4.5]
first_sym = next(i for i, l in enumerate(style["layers"]) if l["type"] == "symbol")
style["layers"][first_sym:first_sym] = [
    {"id": "route-ahead", "type": "line", "source": "route", "layout": {"line-cap": "round", "line-join": "round"},
     "paint": {"line-color": ["case", AIR, "#1d4f91", "#4a2c1a"], "line-width": ["interpolate", ["linear"], ["zoom"], 1, 1.4, 10, 2.6], "line-dasharray": [1, 1.6]}},
    {"id": "route-casing", "type": "line", "source": "route", "layout": {"line-cap": "round", "line-join": "round"},
     "paint": {"line-color": ["case", AIR, "#0b2f66", "#5a0c0c"], "line-width": W_CAS}},
    {"id": "route-line", "type": "line", "source": "route", "layout": {"line-cap": "round", "line-join": "round"},
     "paint": {"line-color": ["case", AIR, "#3d8bf0", "#d62020"], "line-width": W_RED}}]
style["layers"].append({"id": "briefing-labels", "type": "symbol", "source": "blabels",
    "layout": {"text-field": ["get", "t"], "text-font": ["Noto Sans Bold"], "text-size": 16, "symbol-sort-key": ["get", "k"],
               "text-anchor": "bottom", "text-offset": [0, -0.85]},
    "paint": {"text-color": "#1c140c", "text-halo-color": "#fffaf0", "text-halo-width": 2.5}})
style["layers"] += [{"id": "dot-ring", "type": "circle", "source": "flightdot"}, {"id": "dot-core", "type": "circle", "source": "flightdot"}]
EXTRUDE = [l["id"] for l in style["layers"] if l["type"] == "fill-extrusion"]
json.dump(style, open(f"{WORK}/style.json", "w"))

class Worker:
    def __init__(self):
        self.logf = f"{WORK}/worker.log"; open(self.logf, "w").close()
        json.dump(dict(style=f"{WORK}/style.json", cache=f"{A.cache}/res", ua=A.ua, record_log=None, pack_root=None, tile_index=None,
                       missing_log=None), open(f"{WORK}/worker.json", "w"))
        env = {**os.environ, "LIBGL_ALWAYS_SOFTWARE": "1", "RV_LOG": self.logf}
        self.p = subprocess.Popen(["xvfb-run", "-a", "-s", "-screen 0 1920x1080x24", "sh", "-c", 'exec node "$0" "$1" 2>>"$RV_LOG"',
                                   f"{NODE}/worker.js", f"{WORK}/worker.json"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, cwd=NODE, env=env)
        self.key = None
    def send(self, o): self.p.stdin.write((json.dumps(o) + "\n").encode()); self.p.stdin.flush()
    def render(self, cam, mile):
        key = round(mile, 4)
        if key != self.key: self.send({"cmd": "route", "mode": "upto", "mile": mile, "dot": -1, "hide": EXTRUDE}); self.key = key
        c = dict(cam); c["center"] = [(cam["center"][0] + 180) % 360 - 180, cam["center"][1]]
        self.send({"cmd": "render", "cam": c}); n = W * H * 4; buf = self.p.stdout.read(n)
        if len(buf) != n: raise SystemExit("map worker stopped:\n" + open(self.logf).read()[-1500:])
        return np.frombuffer(buf, np.uint8).reshape(H, W, 4)[..., :3]
    def close(self):
        self.send({"cmd": "stats"}); self.p.stdin.close(); self.p.wait()

# ====================================================================== overlays
IF = "/usr/share/fonts/opentype/inter/Inter-{}.otf"
def ui(w, s):
    for p in (IF.format(w), "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        if os.path.exists(p): return ImageFont.truetype(p, s)
    return ImageFont.load_default(s)
def serif(s):
    p = "/usr/share/fonts/truetype/google-fonts/Lora-Variable.ttf"
    if not os.path.exists(p): return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf", s)
    f = ImageFont.truetype(p, s); f.set_variation_by_name(b"Bold"); return f
F = dict(head=ui("SemiBold", 24), card=ui("Bold", 44), strip_b=ui("Bold", 26), strip=ui("Medium", 23), small=ui("Medium", 15),
         chip_s=ui("SemiBold", 18), chip=serif(40), title=serif(70), sub=ui("Medium", 28))
def wrap(text, font, width=1250):
    lines, cur = [], ""
    for w_ in text.split():
        trial = (cur + " " + w_).strip()
        if font.getlength(trial) <= width or not cur: cur = trial
        else: lines.append(cur); cur = w_
    return lines + [cur]
def screen(cam, lon, lat):
    ws = 512 * 2 ** cam["zoom"]; cx, cy = merc(*cam["center"]); px, py = merc(lon, lat)
    dx = px - cx; dx -= round(dx)
    return VW / 2 * RATIO + dx * ws * RATIO, VH / 2 * RATIO + (py - cy) * ws * RATIO
def heading_px(cam, mm):
    L = leg_at(mm); a = lonlat_at(max(L["m0"], mm - 1)); b = lonlat_at(min(L["m1"], mm + 1))
    (x0, y0), (x1, y1) = screen(cam, *a), screen(cam, *b); return math.atan2(y1 - y0, x1 - x0)
def draw_plane(d, x, y, ang, s=1.0):
    pts = [(14, 0), (2, 3), (-3, 15), (-7, 15), (-4, 3), (-11, 3), (-14, 9), (-17, 9), (-15, 0),
           (-17, -9), (-14, -9), (-11, -3), (-4, -3), (-7, -15), (-3, -15), (2, -3)]
    ca, sa = math.cos(ang), math.sin(ang)
    poly = [(x + s * 1.6 * (px_ * ca - py_ * sa), y + s * 1.6 * (px_ * sa + py_ * ca)) for px_, py_ in pts]
    d.polygon(poly, fill=(255, 255, 255), outline=(11, 47, 102), width=3)
CHIPS = []
for k_, (c_m, nm) in enumerate(crossings):
    s = next((s for s in SEGS if s["kind"] == "drive" and s["m0"] < c_m <= s["m1"]), None)
    if s is None or c_m - s["m0"] < 0.5: continue
    if k_ and crossings[k_ - 1][1] == nm: continue          # a new leg in the same state or country is not a border
    ts_ = np.linspace(s["t0"], s["t1"], 400); CHIPS.append((nm, float(np.interp(c_m, [mile_at(x) for x in ts_], ts_))))
# ---- optional pixel-art sprites (--sprites DIR): car on roads, plane in the air, pins that bounce in on arrival
SPR = None
if A.sprites:
    from tools import sprites as spr
    SPR = spr.Pack(A.sprites, A.sprite_scale); CAR_DIR, PLANE_DIR = spr.Heading(), spr.Heading(hold_deg=5)
    _ts = np.arange(0, DUR, 1 / FPS); _ms = np.array([mile_at(x) for x in _ts])
    ARRIVE = {LEGS[0]["a"]["id"]: SEGS[0]["t1"] if len(SEGS) > 1 else 0.0}     # the start pin drops as the trip begins
    for L in LEGS:
        hit = np.nonzero(_ms >= L["m1"] - max(0.05, 0.002 * L["dist"]))[0]
        ARRIVE.setdefault(L["b"]["id"], float(_ts[hit[0]]) if len(hit) else DUR)
def draw_sprites(fr, t, mm, cam, sh, s):
    """Pins (bouncing in, with a sparkle, when the traveller arrives), the car or plane, and a wave at the end."""
    pf = lambda st: screen(cam, st["lon"], st["lat"])
    for st in TRIP["stops"]:
        ta = ARRIVE.get(st["id"])
        if ta is None or t < ta: continue
        x, y = pf(st)
        if not (-60 < x < W + 60 and -60 < y < H - 100): continue
        k = min(5, int((t - ta) * 12)); im = SPR.pin[k]
        fr.paste(im, (int(x - SPR.pin_tip[0]), int(y - SPR.pin_tip[1])), im)
        ks = int((t - ta) * 10)
        if ks < 6: spr.paste_center(fr, SPR.sparkle[ks], x, y - SPR.size * 0.55)
    if s["kind"] == "outro" and sh["kind"] == "hold":                # the traveller waves beside the last stop
        x, y = pf(LEGS[-1]["b"]); seq = SPR.wave if int(t * 2) % 3 else SPR.idle
        spr.paste_feet(fr, seq[int(t * 6) % len(seq)], x + SPR.size * 0.75, y)
        return
    if s["kind"] in ("intro", "outro") and sh["kind"] != "move": return
    L = leg_at(mm); x, y = screen(cam, *lonlat_at(mm))
    dm = 25.0 if L["mode"] == "flight" else 0.15
    (x0, y0), (x1, y1) = screen(cam, *lonlat_at(max(L["m0"], mm - dm))), screen(cam, *lonlat_at(min(L["m1"], mm + dm)))
    in_air = L["mode"] == "flight" and L["m0"] + 1 < mm < L["m1"] - 1
    if in_air: spr.paste_center(fr, SPR.plane[PLANE_DIR(x1 - x0, y1 - y0)], x, y)
    else:
        moving = sh["kind"] == "hold" and s["kind"] == "drive" and s["t0"] + 0.1 < t < s["t1"] - 0.5
        bob = SPR.scale if moving and int(t * 8) % 2 else 0          # a one-pixel bounce while driving
        spr.paste_center(fr, SPR.car[CAR_DIR(x1 - x0, y1 - y0)], x, y - bob)
def overlays(fr, t, mm, cam):
    d = ImageDraw.Draw(fr, "RGBA"); sh = shot_at(t); s = SEGS[sh["seg"]]
    for i, st in enumerate([] if SPR else TRIP["stops"]):          # stop markers (pins instead when sprites are on)
        x, y = screen(cam, st["lon"], st["lat"])
        if not (-20 < x < W + 20 and -20 < y < H - 100): continue
        if st["id"] == TRIP["stops"][0]["id"]:
            d.ellipse([x - 14, y - 14, x + 14, y + 14], fill=(34, 160, 70), outline="white", width=3)
            d.polygon([(x - 4, y - 7), (x - 4, y + 7), (x + 8, y)], fill="white")
        else: d.ellipse([x - 9, y - 9, x + 9, y + 9], fill=(255, 214, 0), outline=(40, 30, 20), width=3)
    if SPR: draw_sprites(fr, t, mm, cam, sh, s)
    elif s["kind"] not in ("intro", "outro") or sh["kind"] == "move":     # the traveller: a dot on roads, a plane in the air
        x, y = screen(cam, *lonlat_at(mm)); L = leg_at(mm)
        in_air = L["mode"] == "flight" and L["m0"] + 1 < mm < L["m1"] - 1
        if in_air: draw_plane(d, x, y, heading_px(cam, mm))
        else:
            pr = 21 + 7 * math.sin(t * 6)
            d.ellipse([x - pr, y - pr, x + pr, y + pr], outline=(30, 110, 255), width=5)
            d.ellipse([x - 13, y - 13, x + 13, y + 13], fill=(30, 110, 255), outline="white", width=4)
    y0 = H - 104; d.rectangle([0, y0, W, H], fill=(28, 22, 16))       # bottom strip
    head = TRIP.get("short", TRIP["title"]); d.text((32, y0 + 14), head, font=F["strip_b"], fill="white")
    rg = region_at(mm)
    if rg: d.text((40 + d.textlength(head, font=F["strip_b"]), y0 + 16), f"  ·  {rg}", font=F["strip"], fill=(200, 190, 175))
    d.text((W - 32, y0 + 14), f"{mm:,.0f} mi done   ·   {TOTAL - mm:,.0f} mi to go", font=F["strip"], fill=(225, 218, 205), anchor="ra")
    L = leg_at(mm + 0.01) if mm < TOTAL else LEGS[-1]
    verb = "Drive" if L["mode"] == "drive" else "Fly"
    txt = f"Leg {L['i'] + 1} of {NL}: {verb} {L['a']['name']} → {L['b']['name']}"
    if L["i"] + 1 < NL:
        N_ = LEGS[L["i"] + 1]; txt += f"   ·   then {'drive' if N_['mode'] == 'drive' else 'fly'} to {N_['b']['name']}"
    elif mm >= TOTAL - 0.01: txt = "Home again."
    d.text((32, y0 + 50), txt, font=F["strip"], fill=(255, 214, 0))
    bx0, bx1, by = 32, W - 32, H - 12                                # progress bar: red drives, blue flights
    d.rounded_rectangle([bx0, by - 5, bx1, by + 5], radius=5, fill=(85, 72, 58))
    for Lg in LEGS:
        if mm <= Lg["m0"]: break
        xa = bx0 + (bx1 - bx0) * Lg["m0"] / TOTAL; xb = bx0 + (bx1 - bx0) * min(mm, Lg["m1"]) / TOTAL
        d.rectangle([xa, by - 5, max(xa + 1, xb), by + 5], fill=(61, 139, 240) if Lg["mode"] == "flight" else (214, 32, 32))
    for Lg in LEGS[1:]:
        x = bx0 + (bx1 - bx0) * Lg["m0"] / TOTAL; d.line([x, by - 9, x, by + 9], fill=(230, 220, 200), width=2)
    d.text((W - 20, y0 - 6), "OpenFreeMap © OpenMapTiles · Data from OpenStreetMap · Roads: OSRM · Flights: great-circle paths · Preview, not for navigation",
           font=F["small"], fill=(25, 25, 25), anchor="rd", stroke_width=3, stroke_fill=(250, 246, 236, 235))
    if sh["kind"] != "hold": return
    for nm, tc in CHIPS:
        if tc <= t < tc + 2.6:
            a = min(1, (t - tc) / 0.3, (tc + 2.6 - t) / 0.4)
            w_ = max(d.textlength(nm.upper(), font=F["chip"]), 200) + 56
            d.rounded_rectangle([W - 28 - w_, 24, W - 28, 124], radius=16, fill=(250, 244, 228, int(235 * a)), outline=(92, 66, 38, int(255 * a)), width=3)
            d.text((W - 28 - w_ / 2, 44), "NOW ENTERING", font=F["chip_s"], fill=(140, 30, 30, int(255 * a)), anchor="mm")
            d.text((W - 28 - w_ / 2, 88), nm.upper(), font=F["chip"], fill=(50, 34, 20, int(255 * a)), anchor="mm")
    if s["kind"] in ("intro", "outro"):
        a = min(1.0, (s["t1"] - t) / 0.6) if s["kind"] == "intro" else min(1.0, (t - s["t0"]) / 0.5)
        if a <= 0: return
        tt = TRIP["title"] if s["kind"] == "intro" else TRIP.get("outro_title", "Home again")
        ss = TRIP["subtitle"] if s["kind"] == "intro" else TRIP.get("outro_subtitle", "")
        ov = Image.new("RGBA", (W, H), (0, 0, 0, 0)); od = ImageDraw.Draw(ov)
        od.rounded_rectangle([W / 2 - 720, 60, W / 2 + 720, 270], radius=24, fill=(250, 244, 228, int(240 * a)), outline=(92, 66, 38, int(255 * a)), width=5)
        od.text((W / 2, 142), tt, font=F["title"], fill=(50, 34, 20, int(255 * a)), anchor="mm")
        od.text((W / 2, 222), ss, font=F["sub"], fill=(140, 30, 30, int(255 * a)), anchor="mm")
        fr.paste(ov, (0, 0), ov); return
    lines = wrap(s["card"], F["card"]); lh = int(F["card"].size * 1.22)
    wd = max([F["card"].getlength(l) for l in lines] + [F["head"].getlength(s["head"])]) + 64
    d.rounded_rectangle([28, 24, 28 + wd, 24 + 70 + lh * len(lines)], radius=20, fill=(28, 22, 16))
    d.text((60, 42), s["head"], font=F["head"], fill=(255, 214, 0) if s["kind"] == "drive" else (130, 185, 255))
    for i, l in enumerate(lines): d.text((60, 78 + lh * i), l, font=F["card"], fill="white")

WK = Worker(); HOLD = {}
def frame(t):
    mm = mile_at(t); cam = cam_at(t)
    img = WK.render(cam, mm)
    fr = Image.fromarray(np.ascontiguousarray(img)); overlays(fr, t, mm, cam); return fr


def contact_sheet(path, frame_fn, segs, label_font, cols=4, tw=480, th=270):
    """One image with a thumbnail of every narrated view (at the middle of its line), to check a video before rendering it."""
    rows = (len(segs) + cols - 1) // cols; cap = 54
    sheet = Image.new("RGB", (cols * tw, rows * (th + cap)), (28, 22, 16)); d = ImageDraw.Draw(sheet)
    for i, s in enumerate(segs):
        t = min(max((s["say0"] + s["say1"]) / 2, s["t0"] + 0.1), s["t1"] - 0.1)
        x, y = (i % cols) * tw, (i // cols) * (th + cap)
        sheet.paste(frame_fn(t).resize((tw, th), Image.LANCZOS), (x, y))
        txt = f"{i + 1}  ·  {int(t // 60)}:{int(t % 60):02d}  ·  {s['text']}"
        while label_font.getlength(txt) > tw - 16 and len(txt) > 10: txt = txt[:-2]
        d.text((x + 8, y + th + 6), txt if txt.endswith(s["text"][-3:]) else txt.rstrip() + "…", font=label_font, fill=(240, 232, 218))
    sheet.save(path, quality=85); return sheet.size
if A.contact_sheet:
    print("contact sheet: rendering", len(SEGS), "views...", flush=True); t0_ = time.time()
    sz = contact_sheet(A.contact_sheet, frame, SEGS, ui("Medium", 15))
    WK.close(); print(f"contact sheet: {A.contact_sheet} ({sz[0]}x{sz[1]}, {len(SEGS)} views, {time.time() - t0_:.0f} s)"); sys.exit()
if A.stills:
    os.makedirs(f"{WORK}/stills", exist_ok=True)
    for tt in sorted(float(x) for x in A.stills.split(",")):
        t0 = time.time(); frame(tt).save(f"{WORK}/stills/still_{tt:06.1f}.jpg", quality=88)
        print(f"still {tt} {shot_at(tt)['kind']} seg {shot_at(tt)['seg']} ({time.time() - t0:.1f} s)")
    WK.close(); print(open(f"{WORK}/worker.log").read().strip()[-300:]); sys.exit()

def ts(x): h, r = divmod(x, 3600); m_, s_ = divmod(r, 60); return f"{int(h):02d}:{int(m_):02d}:{s_:06.3f}".replace(".", ",")
with open(f"{WORK}/subs.srt", "w") as fh:
    for i, s in enumerate(SEGS): fh.write(f"{i + 1}\n{ts(s['say0'])} --> {ts(s['say1'])}\n{s['text']}\n\n")
with open(f"{WORK}/chapters.txt", "w") as fh:
    fh.write(f";FFMETADATA1\ntitle={TRIP['title']}\n")
    for i, s in enumerate(SEGS):
        end = SEGS[i + 1]["t0"] if i < len(SEGS) - 1 else DUR
        fh.write(f"[CHAPTER]\nTIMEBASE=1/1000\nSTART={int(s['t0'] * 1000)}\nEND={int(max(end, s['t0'] + 0.01) * 1000)}\ntitle={s['title'].replace('=', '-')}\n")
cmd = ["ffmpeg", "-y", "-nostdin", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-"]
if AUDIO: cmd += ["-i", AUDIO]
n_in = 2 if AUDIO else 1
cmd += ["-i", f"{WORK}/subs.srt", "-i", f"{WORK}/chapters.txt", "-map", "0:v"] + (["-map", "1:a"] if AUDIO else [])
cmd += ["-map", f"{n_in}:s", "-map_metadata", str(n_in + 1), "-map_chapters", str(n_in + 1),
        "-c:v", "libx264", "-preset", "veryfast", "-tune", "animation", "-crf", str(A.crf), "-maxrate", A.maxrate, "-bufsize", A.maxrate, "-g", "48",
        "-pix_fmt", "yuv420p", "-c:s", "mov_text"] + (["-c:a", "aac", "-b:a", "128k", "-af", "apad"] if AUDIO else [])
cmd += ["-t", f"{DUR:.2f}", "-movflags", "+faststart", A.out]
p = subprocess.Popen(cmd, stdin=subprocess.PIPE); n, t0 = int(DUR * FPS), time.time()
for f in range(n):
    p.stdin.write(frame(f / FPS).tobytes())
    if f % 240 == 0: print(f"frame {f}/{n}  {time.time() - t0:.0f}s", flush=True)
p.stdin.close(); p.wait(); WK.close()
print(f"done: {A.out} ({DUR:.0f} s, {os.path.getsize(A.out) / 1e6:.1f} MB) in {time.time() - t0:.0f} s")
print(open(f"{WORK}/worker.log").read().strip()[-300:])
