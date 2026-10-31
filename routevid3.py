#!/usr/bin/env python3
"""routevid v3 - turn an A->B drive into a narrated, offline route-briefing video (MP4).

v3 changes: maps are drawn by native MapLibre (Node, no browser, ~0.2 s a frame) from OpenFreeMap
vector tiles. The camera holds still while a line is spoken and flies (van Wijk smooth zoom, the
flyTo curve) only in the pause between lines. Held views are 3 renders (map, map + full route, and an
"ID image" whose colours encode route miles); Python reveals the red line and places the dot from the
ID image, exactly, even in tilted 3D close-ups. Labels: base map city/state/shield labels plus FROM/TO.

Maps: OpenFreeMap (free, no key, commercial + video use allowed with the attribution
"OpenFreeMap (c) OpenMapTiles Data from OpenStreetMap"). Never uses tile.openstreetmap.org.
Routing: OSRM demo server (light use). Geocoding: Nominatim (1 request/s).
Needs: node + npm, xvfb (xvfb-run), libopengl0; Python numpy, scipy, pillow, geopandas, shapely.

  python3 routevid3.py --from "New York City Hall" --to "Hollywood and Vine, Los Angeles" \
      --from-label "New York City Hall" --to-label "Hollywood & Vine" --contact you@example.com \
      --narrate voices/kokoro-v1 --narrate-py narrate.py --out trip.mp4
  ... --plan-only        route, key turns, borders and the narration script; nothing drawn
  ... --stills 3,20,40   a few frames as JPGs instead of the video
"""
import argparse, json, math, os, re, shutil, subprocess, sys, time, urllib.parse, urllib.request
import numpy as np
from PIL import Image, ImageDraw, ImageFont

MI = 1609.344
W, H, FPS = 1920, 1080, 24

ap = argparse.ArgumentParser()
ap.add_argument("--from", dest="src", required=True); ap.add_argument("--to", dest="dst", required=True)
ap.add_argument("--from-label"); ap.add_argument("--to-label")
ap.add_argument("--contact", required=True, help="email for the User-Agent (Nominatim/OSRM etiquette)")
ap.add_argument("--out", default="route_briefing.mp4")
ap.add_argument("--work", default="routevid_work")
ap.add_argument("--cache", default=os.path.expanduser("~/.cache/routevid"))
ap.add_argument("--narrate", metavar="MODEL_DIR", help="Kokoro v1.0 folder for narrate.py; omit for a silent video")
_here = os.path.dirname(os.path.abspath(__file__))
ap.add_argument("--narrate-py", default=next((p for p in (os.path.join(_here, "tools", "narrate.py"), "narrate.py") if os.path.exists(p)), "narrate.py"),
                help="path to narrate.py (default: tools/narrate.py next to this script)")
ap.add_argument("--voice", default="af_heart")
ap.add_argument("--max-turns", type=int); ap.add_argument("--turns-json")
ap.add_argument("--style", default="https://tiles.openfreemap.org/styles/liberty")
ap.add_argument("--crf", type=int, default=24); ap.add_argument("--maxrate", default="3M", help="x264 bitrate cap (flights over cities are costly)")
ap.add_argument("--plan-only", action="store_true"); ap.add_argument("--stills")
A = ap.parse_args()
UA = f"RouteVideo/3.0 ({A.contact})"
WORK = os.path.abspath(A.work); os.makedirs(WORK, exist_ok=True); os.makedirs(A.cache, exist_ok=True)

# ====================================================================== web helpers
def http(url, params=None, binary=False, retries=4):
    if params: url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for k in range(retries):
        try:
            data = urllib.request.urlopen(req, timeout=60).read()
            return data if binary else json.loads(data)
        except Exception as e:
            if k == retries - 1: raise RuntimeError(f"request failed: {url} ({e})")
            time.sleep(2 + 3 * k)
def cached_json(name, fn):
    p = f"{A.cache}/{name}.json"
    if os.path.exists(p): return json.load(open(p))
    v = fn(); json.dump(v, open(p, "w")); return v
def slug(s): return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:60]
def geocode(q):
    m = re.match(r"^\s*(-?\d+(\.\d+)?)\s*,\s*(-?\d+(\.\d+)?)\s*$", q)
    if m: return float(m.group(3)), float(m.group(1))
    def go():
        time.sleep(1.1)
        r = http("https://nominatim.openstreetmap.org/search", {"q": q, "format": "json", "limit": 1})
        if not r: raise SystemExit(f"could not find place: {q}")
        return [float(r[0]["lon"]), float(r[0]["lat"]), r[0]["display_name"]]
    v = cached_json("geo_" + slug(q), go); return v[0], v[1]
US_ABBR = {"Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR", "California": "CA", "Colorado": "CO", "Connecticut": "CT",
           "Delaware": "DE", "Florida": "FL", "Georgia": "GA", "Hawaii": "HI", "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA",
           "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD", "Massachusetts": "MA", "Michigan": "MI",
           "Minnesota": "MN", "Mississippi": "MS", "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV", "New Hampshire": "NH",
           "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY", "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK",
           "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI", "South Carolina": "SC", "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX",
           "Utah": "UT", "Vermont": "VT", "Virginia": "VA", "Washington": "WA", "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY",
           "District of Columbia": "DC"}
ABBR_US = {v: k for k, v in US_ABBR.items()}
def place_name(lon, lat):
    def go():
        time.sleep(1.1)
        r = http("https://nominatim.openstreetmap.org/reverse", {"lat": lat, "lon": lon, "format": "json", "zoom": 12})
        a = r.get("address", {})
        town = a.get("city") or a.get("town") or a.get("village") or a.get("hamlet") or a.get("suburb") or a.get("county") or ""
        st = a.get("state", "")
        return [f"{town}, {US_ABBR.get(st, st)}".strip(", ")]
    return cached_json(f"rev_{lat:.3f}_{lon:.3f}", go)[0]

# ====================================================================== route
slon, slat = geocode(A.src); dlon, dlat = geocode(A.dst)
FROM, TO = A.from_label or A.src, A.to_label or A.dst
route = cached_json(f"osrm_{slon:.5f}_{slat:.5f}_{dlon:.5f}_{dlat:.5f}", lambda: http(
    f"https://router.project-osrm.org/route/v1/driving/{slon},{slat};{dlon},{dlat}",
    {"overview": "full", "geometries": "geojson", "steps": "true"}))
if route.get("code") != "Ok": raise SystemExit(f"router error: {route.get('code')}")
R = route["routes"][0]
coords = np.array(R["geometry"]["coordinates"])
la1, la2 = np.radians(coords[:-1, 1]), np.radians(coords[1:, 1])
hh = np.sin((la2 - la1) / 2) ** 2 + np.cos(la1) * np.cos(la2) * np.sin(np.radians(coords[1:, 0] - coords[:-1, 0]) / 2) ** 2
seg = 2 * 6371008.8 * np.arcsin(np.sqrt(hh))
cum = np.concatenate([[0], np.cumsum(seg)]) * (R["distance"] / max(seg.sum(), 1)) / MI
TOTAL, TOTAL_S = R["distance"] / MI, R["duration"]
steps = R["legs"][0]["steps"]
step_mi, step_t, ad, at_ = [], [], 0.0, 0.0
for s in steps: step_mi.append(ad / MI); step_t.append(at_); ad += s["distance"]; at_ += s["duration"]
step_mi, step_t = np.array(step_mi), np.array(step_t)
def lonlat_at(m): return [float(np.interp(m, cum, coords[:, 0])), float(np.interp(m, cum, coords[:, 1]))]
print(f"route: {TOTAL:,.0f} mi, {TOTAL_S/3600:.1f} h, {len(steps)} steps")

# ====================================================================== key turns (same rules as v1, tested on 4 routes)
def pretty_ref(r):
    m = re.match(r"^([A-Z]+)\s+(\d+[A-Z]?)(.*)$", r.strip())
    if not m: return r.strip()
    pre, num, rest = m.groups(); rest = rest.strip().title().replace("Bus", "Bus.")
    return f"{pre}-{num}" + (f" {rest}" if rest else "")
def norm_ref(r): return pretty_ref(re.sub(r"\s+", " ", re.sub(r"\b(EXPR|Express(Lanes)?|Metro ExpressLanes|Toll)\b", "", r, flags=re.I)).strip())
def ident(i):
    s = steps[i]; ref = (s.get("ref") or "").split(";")[0].strip()
    return norm_ref(ref) if ref else (s.get("name") or "").strip()
def display(i):
    s = steps[i]; idn = ident(i); nm = (s.get("name") or "").strip()
    if nm and idn != nm and len(nm) <= 24 and not re.search(r"Express|Ramp|\b(Highway|Route|Hwy|Rte)\s*\d|^(US|U\.S\.|State|County)\b", nm):
        return f"{idn} ({nm})"
    return idn
def road_after_idx(i):
    for j in range(i, min(i + 5, len(steps))):
        if ident(j) and steps[j]["distance"] > 400: return j
    return i
def run_miles(i):
    j0 = road_after_idx(i); idn, tot = ident(j0), 0.0
    for j in range(j0, len(steps)):
        if ident(j) and ident(j) != idn: break
        tot += steps[j]["distance"]
    return tot / MI
def direction(dest):
    m = re.search(r"\b(North|South|East|West)\b", dest or ""); return m.group(1) if m else ""
def toward(dest):
    if not dest or ":" not in dest: return ""
    return dest.split(":", 1)[1].split(",")[0].strip()
def instruction(i, j_road, stay=False):
    s = steps[i]; m = s["maneuver"]; typ, mod = m["type"], m.get("modifier", "")
    dest = s.get("destinations") or ""; road = display(j_road); d = direction(dest)
    if d and re.match(r"^(I|US)-", road) and d not in road: road = re.sub(r"^(\S+)", r"\1 " + d, road, count=1)
    tw = toward(dest); tw = f" toward {tw}" if tw and tw not in road else ""
    side = "left" if "left" in mod else ("right" if "right" in mod else "")
    if stay: return f"Keep {side or 'straight'} to stay on {road}{tw}"
    if typ == "turn": return f"Turn {mod.replace('slight ', 'slightly ')} onto {road}"
    if typ == "fork": return f"Keep {side} onto {road}{tw}" if side else f"Continue onto {road}{tw}"
    if typ == "off ramp": return f"Take the exit for {road}{tw}"
    if typ == "on ramp": return f"Take the ramp onto {road}{tw}"
    if typ == "merge": return f"Merge onto {road}{tw}"
    if typ == "end of road": return f"At the end of the road, turn {side} onto {road}"
    if "roundabout" in typ or typ == "rotary": return f"At the roundabout, take {road}"
    return f"Continue onto {road}"
KEY = {"turn", "fork", "off ramp", "on ramp", "merge", "end of road", "roundabout", "rotary", "roundabout turn"}
END_R = max(1.5, min(8.0, TOTAL * 0.02))
MIN_RUN = max(3.0, TOTAL * 0.004)
K = A.max_turns or int(np.clip(round(TOTAL / 35) + 4, 6, 14))
def chain_text(idx, lead):
    big = sorted(idx, key=lambda i: -steps[i]["distance"])[:3]; names, seen = [], set()
    for i in sorted(big):
        n = display(i)
        if n and ident(i) not in seen: names.append(n); seen.add(ident(i))
    return f"{lead} via " + (", ".join(names) if names else "local streets")
if A.turns_json:
    turns = [dict(steps=t["steps"], title=t["title"], text=t["text"]) for t in json.load(open(A.turns_json))]
else:
    first = [i for i in range(len(steps)) if step_mi[i] < END_R]
    last = [i for i in range(len(steps)) if step_mi[i] > TOTAL - END_R]
    cands, cur_long, last_long_start = [], None, 0
    for i in range(len(steps)):
        if i in last: break
        j = road_after_idx(i); after = ident(j); r = run_miles(i)
        if r >= MIN_RUN and after and after != cur_long:
            if i not in first and steps[i]["maneuver"]["type"] in KEY | {"new name", "continue"}:
                # the decision point: a maneuver between here and the new road (e.g. a roundabout),
                # else the earliest one shortly before (e.g. the fork before a merge)
                j0 = None if steps[i]["maneuver"]["type"] in KEY else next((q for q in range(i, j + 1) if steps[q]["maneuver"]["type"] in KEY), None)
                if j0 is None:
                    j0 = i
                    for q in range(i - 1, last_long_start, -1):
                        if step_mi[i] - step_mi[q] > 1.5: break
                        if steps[q]["maneuver"]["type"] in KEY: j0 = q
                if steps[j0]["maneuver"]["type"] in KEY: cands.append((r, j0, i, j, False))
            cur_long, last_long_start = after, i
        elif i not in first and after and after == cur_long and steps[i]["maneuver"]["type"] in ("fork", "off ramp"):
            refs = {re.sub(r"\s(North|South|East|West)$", "", norm_ref(x.split(":")[0].strip()))
                    for x in re.findall(r"\b(?:I|US)\s?\d+\w*(?:\s(?:North|South|East|West))?", steps[i].get("destinations") or "")}
            if refs - {after} and r >= MIN_RUN: cands.append((r * 0.5, i, i, j, True))
    MERGE_MI = max(1.5, TOTAL * 0.002); dedup = []
    for c in sorted(cands, key=lambda c: c[1]):
        if dedup and step_mi[c[1]] - step_mi[dedup[-1][1]] < MERGE_MI:
            if c[0] > dedup[-1][0] and not c[4]: dedup[-1] = c
            continue
        dedup.append(c)
    keep = sorted(sorted(dedup, reverse=True)[:K], key=lambda c: c[1])
    st_idx = first or [0]
    hw = next((c for c in cands if c[1] > st_idx[-1]), None)
    tail = f", then onto {display(hw[3])}" if hw and step_mi[hw[1]] < END_R * 3 else ""
    turns = [dict(steps=[st_idx[0], st_idx[-1]], title="START", text=chain_text(st_idx, "Head out") + tail)]
    for r, j0, i, j, stay in keep: turns.append(dict(steps=sorted({j0, i}), title=None, text=instruction(j0, j, stay)))
    en_idx = last or [len(steps) - 1]
    turns.append(dict(steps=[en_idx[0], len(steps) - 1], title="DESTINATION", text=chain_text(en_idx, "Final approach")))
for t in turns:
    t["mile"] = float(step_mi[t["steps"][-1]]); t["first_mile"] = float(step_mi[t["steps"][0]])
    t["locs"] = [steps[j]["maneuver"]["location"] for j in t["steps"]]
    if not t.get("title"): lo, la = t["locs"][-1]; t["title"] = place_name(lo, la)
    t["text"] = re.sub(r"\s+", " ", t["text"]).strip()
turns[-1]["mile"] = TOTAL

# ====================================================================== borders (Natural Earth admin-1, from GitHub)
crossings = [dict(mile=0.0, state="")]
try:
    NE = f"{A.cache}/ne"; os.makedirs(NE, exist_ok=True)
    base = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/10m_cultural/ne_10m_admin_1_states_provinces"
    for ext in ("shp", "shx", "dbf", "prj"):
        if not os.path.exists(f"{NE}/admin1.{ext}"): open(f"{NE}/admin1.{ext}", "wb").write(http(f"{base}.{ext}", binary=True))
    import geopandas as gpd
    sm_ = np.arange(0, TOTAL, max(0.5, TOTAL / 4000))
    lo, la = np.interp(sm_, cum, coords[:, 0]), np.interp(sm_, cum, coords[:, 1])
    adm = gpd.read_file(f"{NE}/admin1.shp", bbox=(lo.min() - 1, la.min() - 1, lo.max() + 1, la.max() + 1))[["name", "geometry"]]
    j = gpd.sjoin(gpd.GeoDataFrame(geometry=gpd.points_from_xy(lo, la), crs=4326), adm.to_crs(4326), how="left", predicate="within")
    names = j.sort_index()["name"].groupby(level=0).first().ffill().bfill().fillna("").tolist()
    raw, cur = [], None
    for m, nm in zip(sm_, names):
        if nm != cur: raw.append(dict(mile=float(m), state=nm)); cur = nm
    clean = []
    for i, c in enumerate(raw):
        nxt = raw[i + 1]["mile"] if i + 1 < len(raw) else TOTAL
        if (nxt - c["mile"] >= min(3, TOTAL * 0.01) or i == 0) and (not clean or clean[-1]["state"] != c["state"]): clean.append(c)
    crossings = clean or crossings
except Exception as e:
    print("borders skipped:", e)

# ====================================================================== spoken text
ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()
def words(n):
    n = int(round(n))
    if n < 20: return ONES[n]
    if n < 100: return TENS[n // 10] + ("" if n % 10 == 0 else "-" + ONES[n % 10])
    if n < 1000: return ONES[n // 100] + " hundred" + ("" if n % 100 == 0 else " " + words(n % 100))
    if n < 10000: return words(n // 1000) + " thousand" + ("" if n % 1000 == 0 else " " + words(n % 1000))
    return str(n)
def route_num(s):
    """Highway numbers the way people say them: 64 -> sixty-four, 264 -> two sixty-four, 508 -> five oh eight."""
    n = int(re.match(r"\d+", s).group()); suffix = s[len(str(n)):]
    if n < 100: out = words(n)
    elif n < 1000: out = ONES[n // 100] + " " + ("oh " + ONES[n % 100] if 0 < n % 100 < 10 else ("hundred" if n % 100 == 0 else words(n % 100)))
    elif n < 10000: out = words(n // 100) + " " + ("hundred" if n % 100 == 0 else ("oh " + ONES[n % 100] if n % 100 < 10 else words(n % 100)))
    else: out = words(n)
    return out + (" " + " ".join(suffix) if suffix else "")
def speak(text):
    t = text.replace("&", "and").replace("·", ",")
    t = re.sub(r"\(([^)]*)\)", r", \1,", t)
    def ref(m):
        pre, num = m.group(1), m.group(2)
        if pre == "I": return f"I {route_num(num)}"
        if pre == "US": return f"U.S. {route_num(num)}"
        if pre == "SR": return f"state route {route_num(num)}"
        if pre == "CR": return f"county road {route_num(num)}"
        if pre in ABBR_US: return f"{ABBR_US[pre]} {route_num(num)}"
        return f"{pre} {route_num(num)}"
    t = re.sub(r"\b([A-Z]{1,3})-(\d+[A-Z]?)\b", ref, t)
    t = re.sub(r"\bAlt\b\.?", "alternate", t); t = re.sub(r"\bBus\.", "business", t)
    t = re.sub(r",\s*([A-Z]{2})\b", lambda m: ", " + ABBR_US.get(m.group(1), m.group(1)), t)
    for a, b in (("Va Beach", "Virginia Beach"), (" St ", " Street "), (" Ave ", " Avenue "), (" Blvd", " Boulevard"), (" Hwy", " Highway"), (" Pkwy", " Parkway")):
        t = t.replace(a, b)
    t = re.sub(r"\b(\d+)\b", lambda m: words(int(m.group(1))), t)
    t = re.sub(r"\s+,", ",", re.sub(r",\s*,", ",", re.sub(r"\s+", " ", t))).strip(" ,")
    return t[0].upper() + t[1:] if t else t
def hm_words(sec):
    h, m = divmod(int(round(sec / 60)), 60)
    if h and m: return f"{words(h)} hour{'s' if h > 1 else ''} {words(m)} minutes"
    return f"{words(h)} hour{'s' if h > 1 else ''}" if h else f"{words(m)} minutes"

# ====================================================================== segments (story of the trip)
def main_road(m0, m1):
    tot = {}
    for i, s in enumerate(steps):
        a, b = step_mi[i], step_mi[i] + s["distance"] / MI
        ov = max(0.0, min(b, m1) - max(a, m0))
        if ov > 0 and ident(i): tot[display(i)] = tot.get(display(i), 0) + ov
    return max(tot, key=tot.get) if tot else ""
def states_in(m0, m1): return [c["state"] for c in crossings[1:] if m0 < c["mile"] <= m1 and c["state"]]
nkey = len(turns) - 2
SEGS = [dict(kind="intro", m0=0, m1=0, text=f"This is your route from {FROM} to {TO}: {words(TOTAL)} miles, about {hm_words(TOTAL_S)} of driving, "
             f"with {words(nkey)} key turn{'s' if nkey != 1 else ''}.", title="Overview")]
prev_end = 0.0
for ti, t in enumerate(turns):
    if ti == 0:
        a, b = 0.0, min(TOTAL, t["mile"] + 0.3)
        SEGS.append(dict(kind="close", turn=ti, m0=a, m1=b, title="Start: " + t["text"], text=f"Starting from {FROM}: {speak(t['text'])}."))
        prev_end = b; continue
    a = max(prev_end, (t["first_mile"] - 0.35) if ti < len(turns) - 1 else TOTAL - 0.6)
    if a - prev_end >= 1.5:
        road = main_road(prev_end, a); sts = states_in(prev_end, a); d = a - prev_end
        line = f"Then follow {speak(road)} for about {words(d if d < 20 else round(d / 5) * 5)} miles" if road else f"Continue for about {words(d)} miles"
        if sts: line += ", into " + " and then ".join(sts[:3])
        SEGS.append(dict(kind="travel", m0=prev_end, m1=a, title=f"{road or 'Drive'}, {d:,.0f} mi", text=line + "."))
    else:
        a = prev_end
    if ti < len(turns) - 1:
        b = min(TOTAL, t["mile"] + 0.3)
        SEGS.append(dict(kind="close", turn=ti, m0=a, m1=b, title=f"Turn {ti}: {t['text']}",
                         text=f"At mile {words(t['mile'])}, near {speak(t['title'])}: {speak(t['text'])}."))
    else:
        b = TOTAL
        a = max(a, TOTAL - 0.6)          # the arrival close-up shows the last stretch, framed tight
        SEGS.append(dict(kind="close", turn=ti, m0=a, m1=b, title="Arrive: " + t["text"], text=f"{speak(t['text'])}."))
    prev_end = b
SEGS.append(dict(kind="outro", m0=TOTAL, m1=TOTAL, title="Arrived", text=f"You have arrived at {speak(TO)}."))

print(f"key turns ({nkey} + start/arrive):")
for i, t in enumerate(turns): print(f"  {i:2d}  mile {t['mile']:7.1f}  {t['title']:<26} {t['text']}")
print("regions:", [(round(c['mile']), c['state']) for c in crossings])
print("script:"); [print(f"  [{s['kind']:<6}] {s['text']}") for s in SEGS]
if A.plan_only: sys.exit(0)


# ====================================================================== v3: cameras, flights, narration timing
VW, VH, RATIO = 1280, 720, 1.5          # MapLibre viewport in CSS px; output is 1920x1080
def merc(lon, lat):
    s = math.sin(math.radians(max(-85, min(85, lat))))
    return (lon + 180) / 360, 0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)
def unmerc(x, y): return x * 360 - 180, math.degrees(math.atan(math.sinh((0.5 - y) * 2 * math.pi)))
def mile_range_coords(m0, m1):
    i0 = int(max(0, np.searchsorted(cum, m0) - 1)); i1 = int(min(len(cum), np.searchsorted(cum, m1) + 1))
    return coords[i0:max(i1, i0 + 2)]
def fit_cam(m0, m1, pad=(60, 60, 60, 110), zmax=13.5):
    c = mile_range_coords(m0, m1); xs, ys = zip(*[merc(lo, la) for lo, la in c])
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    top, right, left, bottom = pad
    aw, ah = VW - left - right, VH - top - bottom
    z = math.log2(max(1e-9, min(aw / max(1e-12, (x1 - x0) * 512), ah / max(1e-12, (y1 - y0) * 512))))
    z = float(np.clip(z, 1.5, zmax)); ws = 512 * 2 ** z
    cx = (x0 + x1) / 2 + ((right - left) / 2) / ws; cy = (y0 + y1) / 2 + ((bottom - top) / 2) / ws
    lon, lat = unmerc(cx, cy)
    return dict(center=[lon, lat], zoom=z, bearing=0.0, pitch=0.0)
def bearing_deg(a, b):
    r = math.pi / 180; y = math.sin((b[0] - a[0]) * r) * math.cos(b[1] * r)
    x = math.cos(a[1] * r) * math.sin(b[1] * r) - math.sin(a[1] * r) * math.cos(b[1] * r) * math.cos((b[0] - a[0]) * r)
    return math.degrees(math.atan2(y, x))
def close_cam(seg):
    t = turns[seg["turn"]]
    if seg["turn"] == 0:    # the start can chain several steps over miles: fit them all, gently tilted
        cam = fit_cam(seg["m0"], seg["m1"], pad=(220, 120, 120, 170), zmax=15.0)
        cam.update(zoom=cam["zoom"] - 0.3, pitch=30.0); return cam
    br = bearing_deg(lonlat_at(max(0, t["mile"] - 0.6)), lonlat_at(t["mile"]))
    return dict(center=lonlat_at(max(0, t["mile"] - 0.12)), zoom=15.4 if seg["turn"] == len(turns) - 1 else 15.0, bearing=br, pitch=40.0)
for s in SEGS:
    if s["kind"] in ("intro", "outro"): s["cam"] = fit_cam(0, TOTAL, pad=(320, 150, 150, 110), zmax=12)
    elif s["kind"] == "travel": s["cam"] = fit_cam(s["m0"], s["m1"])
    else: s["cam"] = close_cam(s)

def van_wijk(a, b, rho=1.42):
    """Smooth zoom-and-pan (van Wijk & Nuij 2003; the curve MapLibre's flyTo uses). Returns (f(k)->cam center/zoom, S)."""
    ws = 512 * 2 ** a["zoom"]
    p0 = np.array(merc(*a["center"])) * ws; p1 = np.array(merc(*b["center"])) * ws
    u1 = float(np.hypot(*(p1 - p0))); w0 = max(VW, VH); w1 = w0 / 2 ** (b["zoom"] - a["zoom"]); r2 = rho * rho
    if u1 < 1e-6:
        S = abs(math.log(w1 / w0)) / rho
        return (lambda k: (a["center"], a["zoom"] + (b["zoom"] - a["zoom"]) * k)), S
    def r(i):
        bb = (w1 * w1 - w0 * w0 + (-1 if i else 1) * r2 * r2 * u1 * u1) / (2 * (w1 if i else w0) * r2 * u1)
        return math.log(math.sqrt(bb * bb + 1) - bb)
    r0 = r(0); S = (r(1) - r0) / rho
    def f(k):
        s = k * S; w = math.cosh(r0) / math.cosh(r0 + rho * s)
        u = w0 * ((math.cosh(r0) * math.tanh(r0 + rho * s) - math.sinh(r0)) / r2) / u1
        p = (p0 + (p1 - p0) * u) / ws
        return list(unmerc(*p)), a["zoom"] + math.log2(1 / w)
    return f, S
def ang_lerp(a, b, u): d = ((b - a + 540) % 360) - 180; return a + d * u
FLIGHTS = []
for i in range(len(SEGS) - 1):
    a, b = SEGS[i]["cam"], SEGS[i + 1]["cam"]
    f, S = van_wijk(a, b)
    d = float(np.clip(S / 1.6, 1.0, 2.8))
    if abs(a["bearing"] - b["bearing"]) > 1 or abs(a["pitch"] - b["pitch"]) > 1: d = max(d, 1.4)
    FLIGHTS.append(dict(a=a, b=b, f=f, dur=d, mile=SEGS[i]["m1"]))
def flight_cam(fl, k):
    e = k * k * (3 - 2 * k); c, z = fl["f"](e); a, b = fl["a"], fl["b"]
    # tilt/rotate late when flying in to a tilted view, early when leaving one; north-up in between
    if b["pitch"] > 0 or abs(b["bearing"]) > 0.5: u = max(0.0, (e - 0.45) / 0.55)
    else: u = 1.0 - max(0.0, 1.0 - e / 0.45)
    if a["pitch"] > 0 or abs(a["bearing"]) > 0.5:
        ua = min(1.0, e / 0.45); br = ang_lerp(a["bearing"], 0.0, ua); pt = a["pitch"] * (1 - ua)
        if b["pitch"] > 0 or abs(b["bearing"]) > 0.5:
            ub = max(0.0, (e - 0.55) / 0.45); br = ang_lerp(br, b["bearing"], ub); pt = pt + b["pitch"] * ub
        return dict(center=c, zoom=z, bearing=br, pitch=pt)
    u = u * u * (3 - 2 * u)
    return dict(center=c, zoom=z, bearing=ang_lerp(0.0, b["bearing"], u), pitch=b["pitch"] * u)

# ====================================================================== narration timing: hold while speaking, fly in the pause
BUDGET = float(np.clip(25 + TOTAL * 0.035, 30, 110))
for s in SEGS:
    s["want"] = float(np.clip((s["m1"] - s["m0"]) / TOTAL * BUDGET, 2.5, 14)) if s["kind"] == "travel" else (5.5 if s["kind"] != "outro" else 4.0)
need_gap = [fl["dur"] + 0.45 for fl in FLIGHTS] + [0.35]
if A.narrate:
    plan = {"title": f"{FROM} to {TO}", "scenes": [{"title": s["title"], "lines": [{"text": s["text"]}]} for s in SEGS]}
    def run_narrate():
        json.dump(plan, open(f"{WORK}/plan.json", "w"), indent=1)
        r = subprocess.run([sys.executable, A.narrate_py, f"{WORK}/plan.json", "--model-dir", A.narrate, "--voice", A.voice, "--gap", "0.35", "--scene-gap", "0.35"],
                           capture_output=True, text=True)
        if r.returncode: print(r.stdout[-2000:], r.stderr[-2000:]); raise SystemExit("narration failed")
        warn = [l for l in r.stdout.splitlines() if "dropped" in l or "cut off" in l]
        if warn: print("narration warnings:", *warn, sep="\n  ")
        return [tuple(map(float, l.split("\t")[:2])) for l in open(f"{WORK}/labels.txt") if l.strip()]
    lab = run_narrate()
    for i, (s, (a, b), sc) in enumerate(zip(SEGS, lab, plan["scenes"])):
        sc["lines"][0]["pause_after"] = round(max(0.35, s["want"] - (b - a), need_gap[i]), 2)
    lab = run_narrate()
    AUDIO = f"{WORK}/narration.wav"; tail = plan["scenes"][-1]["lines"][0]["pause_after"]
else:
    lab, t = [], 0.4
    for i, s in enumerate(SEGS):
        sp = len(s["text"].split()) / 2.4 + 0.3; lab.append((t, t + sp)); t += sp + max(0.35, s["want"] - sp, need_gap[i])
    AUDIO = None; tail = 4.0
for s, (a, b) in zip(SEGS, lab): s["say0"], s["say1"] = a, b
# shots: hold i, then flight i in the pause after line i
SHOTS, t = [], 0.0
for i, s_ in enumerate(SEGS):
    if i < len(SEGS) - 1:   # hold until the flight must leave to land 0.3 s before the next line starts
        end = max(s_["say1"] + 0.1, SEGS[i + 1]["say0"] - 0.3 - FLIGHTS[i]["dur"])
    else: end = s_["say1"] + tail
    SHOTS.append(dict(kind="hold", seg=i, t0=t, t1=end)); t = end
    if i < len(SEGS) - 1:
        fl = FLIGHTS[i]; SHOTS.append(dict(kind="fly", fl=i, seg=i, t0=t, t1=t + fl["dur"])); t += fl["dur"]
DUR = t
for s, sh in zip(SEGS, [x for x in SHOTS if x["kind"] == "hold"]): s["t0"], s["t1"] = sh["t0"], sh["t1"]
for sh in SHOTS: print(f"  {sh['kind']:<4} {sh['t0']:6.1f}-{sh['t1']:6.1f}  seg {sh['seg']} {SEGS[sh['seg']]['kind']}")
print(f"timeline: {DUR:.1f} s, {len(FLIGHTS)} flights ({sum(f['dur'] for f in FLIGHTS):.0f} s of camera motion)" + (" (narrated)" if AUDIO else ""))
def ease(u): u = min(max(u, 0.0), 1.0); return u * u * (3 - 2 * u)
def hold_mile(s, t):
    if s["kind"] == "travel":
        u = (t - s["t0"]) / max(1e-6, s["t1"] - s["t0"]); return s["m0"] + (s["m1"] - s["m0"]) * (0.25 * ease(u) + 0.75 * min(max(u, 0), 1))
    if s["kind"] == "close":
        u = (t - s["say0"]) / max(0.6, s["t1"] - 0.3 - s["say0"]); return s["m0"] + (s["m1"] - s["m0"]) * ease(u)
    return s["m0"]
def shot_at(t):
    for sh in SHOTS:
        if t < sh["t1"]: return sh
    return SHOTS[-1]
def mile_at(t):
    sh = shot_at(t)
    return hold_mile(SEGS[sh["seg"]], t) if sh["kind"] == "hold" else FLIGHTS[sh["fl"]]["mile"]

# ====================================================================== the map worker (native MapLibre, Node, virtual display)
NODE = f"{A.cache}/node3"; os.makedirs(NODE, exist_ok=True)
if not os.path.exists(f"{NODE}/node_modules/@maplibre/maplibre-gl-native"):
    subprocess.run(["npm", "install", "--prefix", NODE, "@maplibre/maplibre-gl-native@6", "--silent"], check=True)
WORKER = r"""
const mbgl=require('@maplibre/maplibre-gl-native');const fs=require('fs'),path=require('path'),https=require('https'),crypto=require('crypto'),readline=require('readline');
const [styleFile,CACHE,UA]=process.argv.slice(2);fs.mkdirSync(CACHE,{recursive:true});
let net=0;
function get(url){const f=path.join(CACHE,crypto.createHash('sha1').update(url).digest('hex'));
 if(fs.existsSync(f))return Promise.resolve({data:fs.readFileSync(f)});net++;
 return new Promise((res,rej)=>{const go=n=>https.get(url,{headers:{'User-Agent':UA}},r=>{const b=[];r.on('data',d=>b.push(d));r.on('end',()=>{const data=Buffer.concat(b);
   if(r.statusCode===200){fs.writeFileSync(f,data);res({data});}else if(r.statusCode===204||r.statusCode===404)res({data:Buffer.alloc(0)});else if(n>0)setTimeout(()=>go(n-1),1500);else rej(new Error('HTTP '+r.statusCode+' '+url));});}).on('error',e=>n>0?setTimeout(()=>go(n-1),1500):rej(e));go(3);});}
const req=(r,cb)=>get(r.url).then(x=>cb(null,x)).catch(e=>cb(e));
const style=JSON.parse(fs.readFileSync(styleFile));
const map=new mbgl.Map({request:req,ratio:%RATIO%});map.load(style);
const render=(m,cam)=>new Promise((res,rej)=>m.render({...cam,width:%VW%,height:%VH%},(e,b)=>e?rej(e):res(b)));
const out=b=>new Promise(r=>process.stdout.write(b,r));
const rl=readline.createInterface({input:process.stdin});const q=[];let busy=false;
rl.on('line',l=>{q.push(JSON.parse(l));pump();});
async function pump(){if(busy)return;busy=true;while(q.length){const c=q.shift();
 try{
  if(c.cmd==='route'){ // which part of the route is drawn: none / all / up to a mile
    const red=c.mode==='none'?['==',['get','m1'],-1]:c.mode==='all'?['>=',['get','m1'],-1]:['<=',['get','m1'],c.mile+1e-9];
    const ahead=c.mode==='upto'?['>=',['get','m0'],c.mile-1e-9]:['>=',['get','m1'],-1];
    for(const id of ['route-casing','route-line'])map.setFilter(id,red);map.setFilter('route-ahead',ahead);
    for(const id of c.hide||[])map.setLayoutProperty(id,'visibility','none');for(const id of c.show||[])map.setLayoutProperty(id,'visibility','visible');
  }else if(c.cmd==='render'){await out(await render(map,c.cam));}
  else if(c.cmd==='id'){const idStyle=JSON.parse(fs.readFileSync(c.style));const m=new mbgl.Map({request:(r,cb)=>cb(null,{data:Buffer.alloc(0)}),ratio:%RATIO%});
    m.load(idStyle);const b=await render(m,c.cam);m.release();await out(b);}
  else if(c.cmd==='stats'){console.error(JSON.stringify({net,rss:Math.round(process.memoryUsage().rss/1e6)}));}
 }catch(e){console.error('worker error',e.message);process.exit(2);}}busy=false;}
rl.on('close',()=>{const w=()=>{if(busy||q.length)return setTimeout(w,50);map.release();process.exit(0);};w();});
""".replace("%RATIO%", str(RATIO)).replace("%VW%", str(VW)).replace("%VH%", str(VH))
open(f"{NODE}/worker.js", "w").write(WORKER)

# style: OpenFreeMap + route pieces split at every segment boundary + curated labels
style = cached_json("style_" + slug(A.style), lambda: http(A.style))
for l in style["layers"]:
    if l["type"] == "symbol" and not re.search(r"city|town|state|country|shield|village", l["id"]): l.setdefault("layout", {})["visibility"] = "none"
cuts = sorted({0.0, TOTAL} | {float(s["m0"]) for s in SEGS} | {float(s["m1"]) for s in SEGS})
step_m = max(0.25, TOTAL / 1500)
cuts = sorted(set(cuts) | set(np.arange(0, TOTAL, step_m).tolist()))
feats = []
for a, b in zip(cuts, cuts[1:]):
    if b - a < 1e-6: continue
    i0 = int(np.searchsorted(cum, a)); i1 = int(np.searchsorted(cum, b))
    pts = [lonlat_at(a)] + coords[i0:i1].tolist() + [lonlat_at(b)]
    feats.append({"type": "Feature", "properties": {"m0": a, "m1": b}, "geometry": {"type": "LineString", "coordinates": pts}})
style["sources"]["route"] = {"type": "geojson", "data": {"type": "FeatureCollection", "features": feats}}
style["sources"]["blabels"] = {"type": "geojson", "data": {"type": "FeatureCollection", "features": [
    {"type": "Feature", "properties": {"t": FROM}, "geometry": {"type": "Point", "coordinates": lonlat_at(0)}},
    {"type": "Feature", "properties": {"t": TO}, "geometry": {"type": "Point", "coordinates": lonlat_at(TOTAL)}}]}}
W_CAS = ["interpolate", ["linear"], ["zoom"], 4, 5, 10, 8, 15, 15]
W_RED = ["interpolate", ["linear"], ["zoom"], 4, 2.6, 10, 4.5, 15, 9]
first_sym = next(i for i, l in enumerate(style["layers"]) if l["type"] == "symbol")
style["layers"][first_sym:first_sym] = [
    {"id": "route-ahead", "type": "line", "source": "route", "layout": {"line-cap": "round", "line-join": "round"},
     "paint": {"line-color": "#4a2c1a", "line-width": ["interpolate", ["linear"], ["zoom"], 4, 1.6, 15, 3.5], "line-dasharray": [1, 1.6]}},
    {"id": "route-casing", "type": "line", "source": "route", "layout": {"line-cap": "round", "line-join": "round"}, "paint": {"line-color": "#5a0c0c", "line-width": W_CAS}},
    {"id": "route-line", "type": "line", "source": "route", "layout": {"line-cap": "round", "line-join": "round"}, "paint": {"line-color": "#d62020", "line-width": W_RED}}]
style["layers"].append({"id": "briefing-labels", "type": "symbol", "source": "blabels",
    "layout": {"text-field": ["get", "t"], "text-font": ["Noto Sans Bold"], "text-size": 17, "text-allow-overlap": True, "text-ignore-placement": True,
               "text-anchor": "bottom", "text-offset": [0, -0.9]}, "paint": {"text-color": "#1c140c", "text-halo-color": "#fffaf0", "text-halo-width": 2.5}})
EXTRUDE = [l["id"] for l in style["layers"] if l["type"] == "fill-extrusion"]
json.dump(style, open(f"{WORK}/style.json", "w"))

class Worker:
    def __init__(self):
        self.log = open(f"{WORK}/worker.log", "w")
        self.p = subprocess.Popen(["xvfb-run", "-a", "-s", "-screen 0 1920x1080x24", "node", f"{NODE}/worker.js", f"{WORK}/style.json", f"{A.cache}/res", UA],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log, cwd=NODE, env={**os.environ, "LIBGL_ALWAYS_SOFTWARE": "1"})
        self.mode = None
    def send(self, obj): self.p.stdin.write((json.dumps(obj) + "\n").encode()); self.p.stdin.flush()
    def read(self):
        n = W * H * 4; buf = self.p.stdout.read(n)
        if len(buf) != n: raise SystemExit(f"map worker died (see {WORK}/worker.log)")
        return np.frombuffer(buf, np.uint8).reshape(H, W, 4)[..., :3]
    def route(self, mode, mile=0.0, pitch=0.0):
        key = (mode, round(mile, 6), pitch > 0)
        if key == self.mode: return
        self.send({"cmd": "route", "mode": mode, "mile": mile, "show" if pitch > 0 else "hide": EXTRUDE}); self.mode = key
    def render(self, cam): self.send({"cmd": "render", "cam": cam}); return self.read()
    def id_render(self, style_path, cam): self.send({"cmd": "id", "style": style_path, "cam": cam}); return self.read()
    def close(self):
        self.send({"cmd": "stats"}); self.p.stdin.close(); self.p.wait(); self.log.close()

# ====================================================================== held views: plain + full route + ID image
def hold_layers(seg):
    """Render the three images for a held view; return what the compositor needs."""
    cam = seg["cam"]
    mpp = 78271.517 * math.cos(math.radians(cam["center"][1])) / 2 ** cam["zoom"]       # metres per CSS px at the centre
    margin = TOTAL if seg["kind"] in ("intro", "outro") else max(3.0, (seg["m1"] - seg["m0"]) * 0.6)
    a, b = max(0.0, seg["m0"] - margin), min(TOTAL, seg["m1"] + margin)
    seg_mi = max(0.004, 2.5 * mpp / MI)
    if (b - a) / seg_mi > 60000: seg_mi = (b - a) / 60000
    ms = np.arange(a, b + seg_mi, seg_mi); ms[-1] = min(ms[-1], b)
    lo, la = np.interp(ms, cum, coords[:, 0]), np.interp(ms, cum, coords[:, 1])
    idf = [{"type": "Feature", "properties": {"i": int(i)}, "geometry": {"type": "LineString", "coordinates": [[lo[i], la[i]], [lo[i + 1], la[i + 1]]]}}
           for i in range(len(ms) - 1)]
    W_ID = ["interpolate", ["linear"], ["zoom"], 4, 7, 10, 10, 15, 17]
    ids = {"version": 8, "sources": {"r": {"type": "geojson", "data": {"type": "FeatureCollection", "features": idf}}}, "layers": [
        {"id": "bg", "type": "background", "paint": {"background-color": "#000000"}},
        {"id": "id", "type": "line", "source": "r", "layout": {"line-cap": "butt", "line-join": "round"},
         "paint": {"line-width": W_ID, "line-color": ["rgb", ["%", ["get", "i"], 256], ["floor", ["/", ["get", "i"], 256]], 255]}}]}
    path = f"{WORK}/idstyle.json"; json.dump(ids, open(path, "w"))
    WK.route("none", pitch=cam["pitch"]); plain = WK.render(cam)
    WK.route("all", pitch=cam["pitch"]); full = WK.render(cam)
    idimg = WK.id_render(path, cam)
    core = idimg[..., 2] == 255
    idx = idimg[..., 0].astype(np.int32) + 256 * idimg[..., 1].astype(np.int32)
    milegrid = np.where(core, ms[np.clip(idx, 0, len(ms) - 1)], np.inf).astype(np.float32)
    from scipy.ndimage import minimum_filter
    milewide = minimum_filter(milegrid, size=11)
    diff = np.any(full != plain, axis=2)
    yy, xx = np.nonzero(core); mv = milegrid[core]; o = np.argsort(mv)
    return dict(plain=plain, full=full, wide=milewide, diff=diff, ys=yy[o], xs=xx[o], mv=mv[o], step=seg_mi)
def screen_pos(L, m):
    """Exact screen position of route mile m in a held view, from the ID image (works under tilt)."""
    lo_, hi_ = np.searchsorted(L["mv"], m - 2 * L["step"]), np.searchsorted(L["mv"], m + 0.5 * L["step"])
    if hi_ <= lo_: return None
    return float(L["xs"][lo_:hi_].mean()), float(L["ys"][lo_:hi_].mean())

# ====================================================================== drawing (overlays on top of the map)
IF = "/usr/share/fonts/opentype/inter/Inter-{}.otf"
def ui(w, s):
    for p in (IF.format(w), "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        if os.path.exists(p): return ImageFont.truetype(p, s)
    return ImageFont.load_default(s)
def serif(s):
    p = "/usr/share/fonts/truetype/google-fonts/Lora-Variable.ttf"
    if not os.path.exists(p): return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf", s)
    f = ImageFont.truetype(p, s); f.set_variation_by_name(b"Bold"); return f
F = dict(num=ui("Bold", 19), head=ui("SemiBold", 24), card=ui("Bold", 46), strip_b=ui("Bold", 26), strip=ui("Medium", 23),
         small=ui("Medium", 15), chip_s=ui("SemiBold", 18), chip=serif(40), title=serif(74), sub=ui("Medium", 28))
sm = ease
def fmt_hm(s):
    s = max(0, int(s)); h, m = divmod(s // 60, 60); return f"{h} h {m:02d} min" if h else f"{m} min"
def state_at(m):
    st = crossings[0]["state"]
    for c in crossings:
        if c["mile"] <= m: st = c["state"]
    return st
def seg_at(t): return shot_at(t)["seg"]

def draw_marks(d, L, seg, m, t):
    """Turn markers (flat views) and the you-are-here dot, placed from the ID image."""
    close = seg["kind"] == "close"
    if not close:
        for i, tt in enumerate(turns):
            p = screen_pos(L, tt["mile"])
            if p is None: continue
            x, y = p
            if not (0 < x < W and 0 < y < H - 104): continue
            if i == len(turns) - 1: d.regular_polygon((x, y, 17), 5, fill=(255, 214, 0), outline=(40, 30, 20), width=3); continue
            done = tt["mile"] <= m
            d.ellipse([x - 15, y - 15, x + 15, y + 15], fill=(40, 30, 20) if done else (255, 214, 0), outline="white" if done else (40, 30, 20), width=3)
            d.text((x, y), "S" if i == 0 else str(i), font=F["num"], fill="white" if done else (25, 20, 15), anchor="mm")
    if seg["kind"] in ("intro", "outro"): return
    p = screen_pos(L, m)
    if p is None: return
    hx, hy = p; r_ = 15 if close else 12; pr = r_ + 9 + 7 * math.sin(t * 6)
    d.ellipse([hx - pr, hy - pr, hx + pr, hy + pr], outline=(30, 110, 255), width=5)
    d.ellipse([hx - r_, hy - r_, hx + r_, hy + r_], fill=(30, 110, 255), outline="white", width=4)

def draw_card(d, seg):
    tt = turns[seg["turn"]]
    head = ("START  ·  " + FROM.upper()) if seg["turn"] == 0 else ("DESTINATION  ·  " + TO.upper()) if seg["turn"] == len(turns) - 1 \
        else f"TURN {seg['turn']} OF {nkey}  ·  MILE {tt['mile']:,.0f}  ·  {tt['title'].upper()}"
    lines, cur = [], ""
    for w_ in tt["text"].split():
        trial = (cur + " " + w_).strip()
        if d.textlength(trial, font=F["card"]) <= 1250: cur = trial
        else: lines.append(cur); cur = w_
    lines.append(cur); lines = lines[:2]
    d.rounded_rectangle([28, 24, 28 + max(d.textlength(l, font=F["card"]) for l in lines + [head]) + 64, 24 + 70 + 56 * len(lines)], radius=20, fill=(28, 22, 16, 238))
    d.text((60, 42), head, font=F["head"], fill=(255, 214, 0))
    for i, l in enumerate(lines): d.text((60, 78 + 56 * i), l, font=F["card"], fill="white")

def overlays(fr, t, m):
    d = ImageDraw.Draw(fr, "RGBA"); y0 = H - 104
    d.rectangle([0, y0, W, H], fill=(28, 22, 16, 232))
    head = f"{FROM}  →  {TO}"
    while d.textlength(head, font=F["strip_b"]) > 900: head = head[:-2]
    d.text((32, y0 + 14), head, font=F["strip_b"], fill="white")
    st = state_at(m)
    if st: d.text((40 + d.textlength(head, font=F["strip_b"]), y0 + 16), f"  ·  {st}", font=F["strip"], fill=(200, 190, 175))
    left_s = TOTAL_S - float(np.interp(m, step_mi, step_t))
    d.text((W - 32, y0 + 14), f"{m:,.0f} mi done   ·   {TOTAL - m:,.0f} mi left   ·   ~{fmt_hm(left_s)} to go", font=F["strip"], fill=(225, 218, 205), anchor="ra")
    nxt = next((k for k, tt in enumerate(turns) if tt["mile"] > m + 0.05 and k > 0), None)
    txt = (f"{'Arrive' if nxt == len(turns) - 1 else f'Next turn {nxt}'}: {turns[nxt]['text']}   ·   in {turns[nxt]['mile'] - m:,.1f} mi"
           if nxt is not None else f"You have arrived: {TO}.")
    while d.textlength(txt, font=F["strip"]) > W - 64: txt = txt[:-2]
    d.text((32, y0 + 50), txt, font=F["strip"], fill=(255, 214, 0))
    bx0, bx1, by = 32, W - 32, H - 12
    d.rounded_rectangle([bx0, by - 5, bx1, by + 5], radius=5, fill=(85, 72, 58))
    d.rounded_rectangle([bx0, by - 5, bx0 + (bx1 - bx0) * m / TOTAL, by + 5], radius=5, fill=(214, 32, 32))
    for c in crossings[1:]:
        x = bx0 + (bx1 - bx0) * c["mile"] / TOTAL; d.line([x, by - 9, x, by + 9], fill=(230, 220, 200), width=2)
    for tt in turns[1:-1]:
        x = bx0 + (bx1 - bx0) * tt["mile"] / TOTAL; d.ellipse([x - 5, by - 5, x + 5, by + 5], fill=(255, 214, 0))
    d.text((W - 20, y0 - 6), "OpenFreeMap © OpenMapTiles · Data from OpenStreetMap · Route: OSRM · Preview, not for navigation",
           font=F["small"], fill=(25, 25, 25), anchor="rd")
    sh = shot_at(t)
    for c in crossings[1:]:                     # small "now entering" chip while the dot crosses a border
        s = next((s for s in SEGS if s["kind"] == "travel" and s["m0"] <= c["mile"] <= s["m1"]), None)
        if s is None or not c["state"]: continue
        ts_ = np.linspace(s["t0"], s["t1"], 200); tc = float(np.interp(c["mile"], [hold_mile(s, x) for x in ts_], ts_))
        if tc <= t < tc + 3.0 and sh["kind"] == "hold":
            a = min(1, (t - tc) / 0.3, (tc + 3.0 - t) / 0.4)
            w_ = max(d.textlength(c["state"].upper(), font=F["chip"]), 200) + 56
            d.rounded_rectangle([W - 28 - w_, 24, W - 28, 124], radius=16, fill=(250, 244, 228, int(235 * a)), outline=(92, 66, 38, int(255 * a)), width=3)
            d.text((W - 28 - w_ / 2, 44), "NOW ENTERING", font=F["chip_s"], fill=(140, 30, 30, int(255 * a)), anchor="mm")
            d.text((W - 28 - w_ / 2, 88), c["state"].upper(), font=F["chip"], fill=(50, 34, 20, int(255 * a)), anchor="mm")
    if sh["kind"] != "hold": return
    s = SEGS[sh["seg"]]
    if s["kind"] in ("intro", "outro"):
        a = min(1.0, (t - s["t0"]) / 0.5) if s["kind"] == "outro" else min(1.0, (s["t1"] - t) / 0.6)
        if a <= 0: return
        tt = f"{FROM} to {TO}" if s["kind"] == "intro" else f"You made it to {TO}"
        ss = (f"{TOTAL:,.0f} miles  ·  about {fmt_hm(TOTAL_S)} of driving  ·  {nkey} key turn{'s' if nkey != 1 else ''}" if s["kind"] == "intro"
              else f"{TOTAL:,.0f} miles from {FROM}")
        ft = F["title"]
        while d.textlength(tt, font=ft) > 1300 and ft.size > 40: ft = serif(ft.size - 4)
        ov = Image.new("RGBA", (W, H), (0, 0, 0, 0)); od = ImageDraw.Draw(ov)
        od.rounded_rectangle([W / 2 - 700, 150, W / 2 + 700, 370], radius=24, fill=(250, 244, 228, int(240 * a)), outline=(92, 66, 38, int(255 * a)), width=5)
        od.text((W / 2, 238), tt, font=ft, fill=(50, 34, 20, int(255 * a)), anchor="mm")
        od.text((W / 2, 322), ss, font=F["sub"], fill=(140, 30, 30, int(255 * a)), anchor="mm")
        fr.alpha_composite(ov)
    elif s["kind"] == "close":
        draw_card(d, s)

# ====================================================================== frames
WK = Worker()
CACHE = {}
STATS = dict(hold_prep=0.0, fly=0.0, compose=0.0, n_fly=0, n_hold=0)
def hold_L(i):
    if ("L", i) not in CACHE:
        for k in [k for k in CACHE if k[0] == "L"]: del CACHE[k]
        t0 = time.time(); CACHE[("L", i)] = hold_layers(SEGS[i]); STATS["hold_prep"] += time.time() - t0; STATS["n_hold"] += 1
    return CACHE[("L", i)]
def fly_img(i, k):
    """Map image for flight i at progress k: route drawn up to the boundary mile, no 3D buildings."""
    key = ("F", i, round(k, 5))
    if key in CACHE: return CACHE[key]
    t0 = time.time(); fl = FLIGHTS[i]
    WK.route("upto", fl["mile"], pitch=0.0); img = WK.render(flight_cam(fl, k))
    STATS["fly"] += time.time() - t0; STATS["n_fly"] += 1
    if k in (0.0, 1.0): CACHE[key] = img
    return img
BLEND = 0.35        # seconds: 3D buildings and the held view fade in/out instead of popping
def frame(t):
    sh = shot_at(t); m = mile_at(t)
    if sh["kind"] == "fly":
        k = (t - sh["t0"]) / (sh["t1"] - sh["t0"]); img = fly_img(sh["fl"], min(max(k, 0.0), 1.0))
        fr = Image.fromarray(img).convert("RGBA")
    else:
        i = sh["seg"]; L = hold_L(i); t0 = time.time()
        mask = L["diff"] & (L["wide"] <= m + 1e-6)
        img = np.where(mask[..., None], L["full"], L["plain"])
        if i > 0 and t - sh["t0"] < BLEND:
            u = sm((t - sh["t0"]) / BLEND); img = (fly_img(i - 1, 1.0) * (1 - u) + img * u).astype(np.uint8)
        elif i < len(SEGS) - 1 and sh["t1"] - t < BLEND:
            u = sm((sh["t1"] - t) / BLEND); img = (fly_img(i, 0.0) * (1 - u) + img * u).astype(np.uint8)
        fr = Image.fromarray(img).convert("RGBA")
        d = ImageDraw.Draw(fr); draw_marks(d, L, SEGS[i], m, t)
        STATS["compose"] += time.time() - t0
    overlays(fr, t, m)
    return fr.convert("RGB")

if A.stills:
    os.makedirs(f"{WORK}/stills", exist_ok=True)
    for tt in sorted(float(x) for x in A.stills.split(",")):
        frame(tt).save(f"{WORK}/stills/still_{tt:06.1f}.jpg", quality=88); print("still", tt, shot_at(tt)["kind"], f"seg {shot_at(tt)['seg']}")
    WK.close(); print("stills in", f"{WORK}/stills"); sys.exit()

# ====================================================================== subtitles, chapters, encode
def ts(x): h, r = divmod(x, 3600); m, s = divmod(r, 60); return f"{int(h):02d}:{int(m):02d}:{s:06.3f}".replace(".", ",")
with open(f"{WORK}/subs.srt", "w") as fh:
    for i, s in enumerate(SEGS): fh.write(f"{i + 1}\n{ts(s['say0'])} --> {ts(s['say1'])}\n{s['text']}\n\n")
with open(f"{WORK}/chapters.txt", "w") as fh:
    fh.write(f";FFMETADATA1\ntitle=Route briefing: {FROM} to {TO}\n")
    for i, s in enumerate(SEGS):
        end = SEGS[i + 1]["t0"] if i < len(SEGS) - 1 else DUR
        fh.write(f"[CHAPTER]\nTIMEBASE=1/1000\nSTART={int(s['t0'] * 1000)}\nEND={int(max(end, s['t0'] + 0.01) * 1000)}\ntitle={s['title'].replace('=', '-')}\n")
cmd = ["ffmpeg", "-y", "-nostdin", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-"]
if AUDIO: cmd += ["-i", AUDIO]
cmd += ["-i", f"{WORK}/subs.srt", "-i", f"{WORK}/chapters.txt", "-map", "0:v"]
n_in = 1
if AUDIO: cmd += ["-map", "1:a"]; n_in = 2
cmd += ["-map", f"{n_in}:s", "-map_metadata", str(n_in + 1), "-map_chapters", str(n_in + 1),
        "-c:v", "libx264", "-preset", "veryfast", "-tune", "animation", "-crf", str(A.crf), "-maxrate", A.maxrate, "-bufsize", A.maxrate, "-g", "48",
        "-pix_fmt", "yuv420p", "-c:s", "mov_text"]
if AUDIO: cmd += ["-c:a", "aac", "-b:a", "128k", "-af", "apad"]
cmd += ["-t", f"{DUR:.2f}", "-movflags", "+faststart", A.out]
p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
n, t0 = int(DUR * FPS), time.time()
for f in range(n):
    p.stdin.write(frame(f / FPS).tobytes())
    if f % 240 == 0: print(f"frame {f}/{n}  {time.time() - t0:.0f}s", flush=True)
p.stdin.close(); p.wait(); WK.close()
print(f"done: {A.out} ({DUR:.0f} s, {os.path.getsize(A.out) / 1e6:.1f} MB) in {time.time() - t0:.0f} s; "
      f"holds {STATS['n_hold']} ({STATS['hold_prep']:.0f} s prep, {STATS['compose']:.0f} s compose), flight frames {STATS['n_fly']} ({STATS['fly']:.0f} s)")
print(open(f"{WORK}/worker.log").read().strip()[-400:])
