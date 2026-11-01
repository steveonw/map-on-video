#!/usr/bin/env python3
"""Convert a browser one-pass ZIP (schema route-video-onepass-v2, from map-fetcher-onepass.html) into a
route-video-pack-v1 pack that routevid3 --assets can read.

    python3 tools/onepass_to_pack.py route-assets-....zip pack.zip [--reverse reverse.json]

The one-pass ZIP stores files under its own names (assets/tiles/z/x/y.pbf, assets/fonts/<name>/<range>.pbf, ...);
this rebuilds the URL each was fetched from, using the style and TileJSON inside the same ZIP. Place names
(data/reverse.json) are only included if the ZIP has assets/geocode/reverse.json or you pass --reverse.
Run routevid3 --assets pack.zip --asset-plan needs.json afterwards to see what is still missing.
"""
import argparse, json, re, sys, time, urllib.parse, zipfile
from pathlib import Path, PurePosixPath
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools import pack as packlib


def convert(src, out, reverse=None):
    with zipfile.ZipFile(src) as z:
        names = set(z.namelist())
        for n in names:
            p = PurePosixPath(n)
            if n.startswith("/") or "\\" in n or ".." in p.parts: raise packlib.PackError(f"unsafe entry {n!r}")
        req = json.loads(z.read("request.json"))
        if req.get("schema") != "route-video-onepass-v2": raise packlib.PackError("not a route-video-onepass-v2 ZIP")
        rd = lambda n: z.read("assets/" + n)
        style_url = "https://tiles.openfreemap.org/styles/" + req.get("style", "liberty")
        style = json.loads(rd(f"styles/{req.get('style', 'liberty')}/style.json"))
        res = {style_url: rd(f"styles/{req.get('style', 'liberty')}/style.json")}
        tj_url = next((s["url"] for s in style["sources"].values() if s.get("type") == "vector" and s.get("url")), None)
        tj = json.loads(rd("tilejson/planet.json")); res[tj_url] = rd("tilejson/planet.json")
        tpl = tj["tiles"][0]
        sprite = style.get("sprite")
        sprite = sprite if isinstance(sprite, str) else (sprite[0]["url"] if sprite else None)
        fonts = {re.sub(r"[^a-zA-Z0-9_-]", "_", f): f for l in style["layers"] for f in (l.get("layout", {}).get("text-font") or [])
                 if isinstance(f, str)}
        for n in sorted(names):
            if not n.startswith("assets/"): continue
            a = n[len("assets/"):]
            m = re.fullmatch(r"tiles/(\d+)/(\d+)/(\d+)\.pbf", a)
            if m: res[tpl.replace("{z}", m[1]).replace("{x}", m[2]).replace("{y}", m[3])] = z.read(n); continue
            m = re.fullmatch(r"fonts/([^/]+)/(\d+-\d+)\.pbf", a)
            if m and m[1] in fonts:
                res[style["glyphs"].replace("{fontstack}", urllib.parse.quote(fonts[m[1]], safe=",")).replace("{range}", m[2])] = z.read(n)
                continue
            m = re.fullmatch(r"sprites/.*?/([^/]+)$", a)
            if m and sprite: res[sprite + m[1][len(sprite.rsplit("/", 1)[1]):]] = z.read(n)
        ends = json.loads(rd("geocode/endpoints.json"))
        geo = {ends[k]["name"]: [*ends[k]["coordinates"], ends[k]["name"]] for k in ("from", "to")}
        rev = json.loads(rd("geocode/reverse.json")) if "assets/geocode/reverse.json" in names else {}
        route = json.loads(rd("route/route.json"))
    if reverse: rev.update(json.load(open(reverse)))
    man = packlib.write_pack(out, {"from": req["route"]["from"], "to": req["route"]["to"]}, style_url, res,
                             {"geocode.json": geo, "route.json": route, "reverse.json": rev},
                             {"created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                              "created_by": "tools/onepass_to_pack.py from " + Path(src).name})
    return man, len(res)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("onepass_zip"); ap.add_argument("pack_zip"); ap.add_argument("--reverse", help="JSON {\"lat,lon\": \"Town, ST\"}")
    a = ap.parse_args()
    man, n = convert(a.onepass_zip, a.pack_zip, a.reverse)
    print(f"{a.pack_zip}: {len(man['files'])} files ({n} map resources); route {man['route']['from']} -> {man['route']['to']}")
