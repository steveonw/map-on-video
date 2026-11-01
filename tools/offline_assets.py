"""Seed routevid v3's URL-keyed caches from a route-video-onepass-v2 archive."""
import hashlib
import json
import re
import zipfile
from pathlib import Path
from urllib.parse import quote

BASE = "https://tiles.openfreemap.org"

def slug(s):
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:60]

def seed(archive, cache, src, dst, style_url):
    cache = Path(cache).expanduser()
    res = cache / "res"
    res.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        req = json.loads(z.read("request.json"))
        if req.get("schema") != "route-video-onepass-v2":
            raise ValueError("Expected route-video-onepass-v2 package")
        if (req["route"]["from"], req["route"]["to"]) != (src, dst):
            raise ValueError("ZIP route differs from --from/--to")
        report = json.loads(z.read("download-report.json"))
        if report.get("failed"):
            raise ValueError("Incomplete asset ZIP: " + str(report["failed"][:5]))
        endpoints = json.loads(z.read("assets/geocode/endpoints.json"))
        route = json.loads(z.read("assets/route/route.json"))
        if route.get("code") != "Ok" or not route.get("routes"):
            raise ValueError("Missing valid OSRM route")
        points = []
        for label, key in ((src, "from"), (dst, "to")):
            point = endpoints[key]["coordinates"]
            if len(point) != 2:
                raise ValueError("Invalid geocoding coordinates")
            points.append(point)
            (cache / ("geo_" + slug(label) + ".json")).write_text(json.dumps([*point, label]))
        slon, slat = points[0]
        dlon, dlat = points[1]
        (cache / f"osrm_{slon:.5f}_{slat:.5f}_{dlon:.5f}_{dlat:.5f}.json").write_text(json.dumps(route))
        if style_url != BASE + "/styles/liberty":
            raise ValueError("Offline ZIP currently supports only OpenFreeMap Liberty")
        style = json.loads(z.read("assets/styles/liberty/style.json"))
        raster = {key for key, value in style["sources"].items() if value.get("type") == "raster"}
        style["layers"] = [layer for layer in style["layers"] if layer.get("source") not in raster]
        for key in raster:
            style["sources"].pop(key, None)
        (cache / ("style_" + slug(style_url) + ".json")).write_text(json.dumps(style))
        tile_template = json.loads(z.read("assets/tilejson/planet.json"))["tiles"][0]
        links = {"assets/tilejson/planet.json": BASE + "/planet"}
        sprite_root = style["sprite"]
        for suffix in (".json", ".png", "@2x.json", "@2x.png"):
            links[f"assets/sprites/ofm_f384/ofm{suffix}"] = sprite_root + suffix
        for name in z.namelist():
            tile = re.fullmatch(r"assets/tiles/(\d+)/(\d+)/(\d+)\.pbf", name)
            if tile:
                zz, xx, yy = tile.groups()
                links[name] = tile_template.replace("{z}", zz).replace("{x}", xx).replace("{y}", yy)
            font = re.fullmatch(r"assets/fonts/([^/]+)/([^/]+\.pbf)", name)
            if font:
                stack = font.group(1).replace("_", " ")
                links[name] = style["glyphs"].replace("{fontstack}", quote(stack, safe="")).replace("{range}", font.group(2)[:-4])
        count = 0
        for name, url in links.items():
            if name not in z.namelist():
                continue
            (res / hashlib.sha1(url.encode()).hexdigest()).write_bytes(z.read(name))
            count += 1
        return {"seeded_resources": count,
                "sampled_tiles": sum(name.startswith("assets/tiles/") for name in links),
                "route_miles": round(route["routes"][0]["distance"] / 1609.344),
                "warning": "Sampled tiles do not guarantee full coverage; missing resources abort offline rendering."}
