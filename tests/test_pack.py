"""Tests for the route-video-pack-v1 format (tools/pack.py) and the one-pass converter.

    python3 -m unittest discover -s tests -v

No network. The JavaScript parity test needs node (skipped without it).
"""
import hashlib, io, json, os, shutil, stat, subprocess, sys, tempfile, unittest, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tools import pack as P

OFM = "https://tiles.openfreemap.org"
URLS = [
    (OFM + "/styles/liberty", "http/tiles.openfreemap.org/styles/liberty/index"),
    (OFM + "/planet", "http/tiles.openfreemap.org/planet/index"),
    (OFM + "/planet/20261025_080012_pt/6/17/25.pbf", "http/tiles.openfreemap.org/planet/20261025_080012_pt/6/17/25.pbf"),
    (OFM + "/fonts/Noto%20Sans%20Bold/0-255.pbf", "http/tiles.openfreemap.org/fonts/Noto Sans Bold/0-255.pbf"),
    (OFM + "/sprites/ofm_f384/ofm@2x.json", "http/tiles.openfreemap.org/sprites/ofm_f384/ofm@2x.json"),
    (OFM + "/natural_earth/ne2sr/6/17/24.png", "http/tiles.openfreemap.org/natural_earth/ne2sr/6/17/24.png"),
    ("https://Example.COM/a/b.json?key=1&x=2", "http/example.com/a/b.json@" + hashlib.sha1(b"key=1&x=2").hexdigest()[:16]),
    ("https://example.com/", "http/example.com/index"),
]


def make_pack(tmp, files, route=("A", "B"), manifest_edit=None, extra_entries=()):
    """Build a pack ZIP by hand so tests can also make broken ones."""
    man = {"schema": P.SCHEMA, "route": {"from": route[0], "to": route[1]}, "style": OFM + "/styles/liberty",
           "files": {n: {"sha256": hashlib.sha256(b).hexdigest(), "size": len(b)} for n, b in files.items()}}
    if manifest_edit: manifest_edit(man)
    zp = Path(tmp) / f"pack{len(os.listdir(tmp))}.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("pack.json", json.dumps(man))
        for n, b in files.items(): z.writestr(n, b)
        for info, b in extra_entries: z.writestr(info, b)
    return zp


class UrlMapping(unittest.TestCase):
    def test_paths(self):
        for url, path in URLS:
            self.assertEqual(P.url_to_path(url), path, url)

    def test_unsafe(self):
        for url in ("ftp://x/y", "https:///nohost", OFM + "/a/%2e%2e/b.pbf", OFM + "/a/..%5c/b.pbf", "file:///etc/passwd"):
            with self.assertRaises(P.PackError, msg=url): P.url_to_path(url)

    def test_tile_key_ignores_version(self):
        a = P.tile_key(P.url_to_path(OFM + "/planet/20261025_080012_pt/12/1166/1569.pbf"))
        b = P.tile_key(P.url_to_path(OFM + "/planet/20261101_000000_pt/12/1166/1569.pbf"))
        self.assertEqual(a, b); self.assertEqual(a, "tiles.openfreemap.org/planet/12/1166/1569.pbf")
        self.assertIsNone(P.tile_key(P.url_to_path(OFM + "/fonts/Noto%20Sans%20Bold/0-255.pbf")))
        self.assertNotEqual(a, P.tile_key(P.url_to_path(OFM + "/planet/20261025_080012_pt/12/1166/1570.pbf")))

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_javascript_matches_python(self):
        """The map worker resolves URLs in JavaScript; it must agree with Python on every case."""
        urls = [u for u, _ in URLS] + [OFM + "/planet/20261101_000000_pt/12/1166/1569.pbf"]
        js = P.PACK_JS + f"\nconst U={json.dumps(urls)};console.log(JSON.stringify(U.map(u=>[packPath(u),tileKey(packPath(u))])));"
        out = json.loads(subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout)
        self.assertEqual(out, [[P.url_to_path(u), P.tile_key(P.url_to_path(u))] for u in urls])
        bad = subprocess.run(["node", "-e", P.PACK_JS + f"\npackPath({json.dumps(OFM + '/a/%2e%2e/b.pbf')})"], capture_output=True, text=True)
        self.assertNotEqual(bad.returncode, 0)


class Validation(unittest.TestCase):
    def setUp(self): self.tmp = tempfile.mkdtemp()
    def tearDown(self): shutil.rmtree(self.tmp)
    def good(self):
        return {"data/route.json": b'{"code":"Ok"}',
                "http/tiles.openfreemap.org/planet/20261025_080012_pt/6/17/25.pbf": b"tile-6-17-25",
                "http/tiles.openfreemap.org/styles/liberty/index": b'{"version":8}'}

    def test_good_pack_opens_and_resolves(self):
        p = P.open_pack(make_pack(self.tmp, self.good()), Path(self.tmp) / "x")
        self.assertEqual(p.get(OFM + "/planet/20261025_080012_pt/6/17/25.pbf"), b"tile-6-17-25")
        self.assertEqual(p.get(OFM + "/planet/20991231_000000_pt/6/17/25.pbf"), b"tile-6-17-25")   # other build, same z/x/y
        self.assertIsNone(p.get(OFM + "/planet/20261025_080012_pt/6/17/26.pbf"))
        self.assertEqual(p.get(OFM + "/styles/liberty"), b'{"version":8}')
        self.assertEqual(p.data("route.json"), {"code": "Ok"})
        self.assertEqual(json.loads(p.index_file.read_text())["tiles.openfreemap.org/planet/6/17/25.pbf"],
                         "http/tiles.openfreemap.org/planet/20261025_080012_pt/6/17/25.pbf")
        p2 = P.open_pack(make_pack(self.tmp, self.good()), Path(self.tmp) / "x")      # same bytes: reuses the unpacked copy
        self.assertEqual(p2.root.parent, p.root.parent)

    def test_rejects(self):
        g = self.good()
        cases = {
            "traversal": make_pack(self.tmp, g, extra_entries=[("http/../../evil.txt", b"x")]),
            "absolute": make_pack(self.tmp, g, extra_entries=[("/etc/evil", b"x")]),
            "backslash": make_pack(self.tmp, g, extra_entries=[("http\\evil", b"x")]),
            "outside roots": make_pack(self.tmp, g, extra_entries=[("other/file", b"x")]),
            "unlisted": make_pack(self.tmp, g, extra_entries=[("http/example.com/extra.pbf", b"x")]),
            "listed but absent": make_pack(self.tmp, g, manifest_edit=lambda m: m["files"].update(
                {"data/reverse.json": {"sha256": "0" * 64, "size": 2}})),
            "size mismatch": make_pack(self.tmp, g, manifest_edit=lambda m: m["files"]["data/route.json"].update(size=1)),
            "wrong schema": make_pack(self.tmp, g, manifest_edit=lambda m: m.update(schema="route-video-onepass-v2")),
            "no route": make_pack(self.tmp, g, manifest_edit=lambda m: m.pop("route")),
        }
        link = zipfile.ZipInfo("http/example.com/link.pbf"); link.external_attr = (stat.S_IFLNK | 0o777) << 16
        cases["symlink"] = make_pack(self.tmp, g, extra_entries=[(link, b"/etc/passwd")],
                                     manifest_edit=lambda m: m["files"].update({"http/example.com/link.pbf": {
                                         "sha256": hashlib.sha256(b"/etc/passwd").hexdigest(), "size": 11}}))
        for why, zp in cases.items():
            with self.assertRaises(P.PackError, msg=why): P.open_pack(zp, Path(self.tmp) / "x")
        self.assertFalse((Path(self.tmp).parent / "evil.txt").exists())

    def test_sha256_checked(self):
        zp = make_pack(self.tmp, self.good(), manifest_edit=lambda m: m["files"]["data/route.json"].update(sha256="f" * 64))
        with self.assertRaises(P.PackError): P.open_pack(zp, Path(self.tmp) / "x")
        self.assertFalse(any((Path(self.tmp) / "x").glob("*/.verified")))

    def test_limits(self):
        zp = make_pack(self.tmp, self.good())
        with self.assertRaises(P.PackError): P.validate_zip(zp, dict(P.LIMITS, entries=2))
        with self.assertRaises(P.PackError): P.validate_zip(zp, dict(P.LIMITS, entry_bytes=5))
        with self.assertRaises(P.PackError): P.validate_zip(zp, dict(P.LIMITS, total_bytes=10))

    def test_folder_pack(self):
        d = Path(self.tmp) / "folder"
        with zipfile.ZipFile(make_pack(self.tmp, self.good())) as z: z.extractall(d)
        p = P.open_pack(d, Path(self.tmp) / "x")
        self.assertEqual(p.get(OFM + "/styles/liberty"), b'{"version":8}')
        self.assertFalse((d / ".tileindex.json").exists())        # nothing written into the user's folder
        (d / "data/route.json").write_bytes(b"tampered")
        with self.assertRaises(P.PackError): P.open_pack(d, Path(self.tmp) / "x")

    def test_write_pack_round_trip(self):
        out = Path(self.tmp) / "w.zip"
        res = {OFM + "/planet": b'{"tiles":[]}', OFM + "/fonts/Noto%20Sans%20Bold/0-255.pbf": b"glyphs"}
        P.write_pack(out, {"from": "A", "to": "B"}, OFM + "/styles/liberty", res,
                     {"route.json": {"code": "Ok"}, "reverse.json": {P.reverse_key(-77.5, 38.3): "Town, VA"}})
        p = P.open_pack(out, Path(self.tmp) / "x")
        self.assertEqual(p.get(OFM + "/fonts/Noto%20Sans%20Bold/0-255.pbf"), b"glyphs")
        self.assertEqual(p.data("reverse.json"), {"38.300,-77.500": "Town, VA"})


class OnepassConversion(unittest.TestCase):
    def test_convert(self):
        from tools.onepass_to_pack import convert
        tmp = Path(tempfile.mkdtemp())
        try:
            tpl = OFM + "/planet/20261025_080012_pt/{z}/{x}/{y}.pbf"
            style = {"version": 8, "sprite": OFM + "/sprites/ofm_f384/ofm", "glyphs": OFM + "/fonts/{fontstack}/{range}.pbf",
                     "sources": {"openmaptiles": {"type": "vector", "url": OFM + "/planet"}},
                     "layers": [{"id": "l", "type": "symbol", "layout": {"text-font": ["Noto Sans Bold"]}}]}
            src = tmp / "onepass.zip"
            with zipfile.ZipFile(src, "w") as z:
                z.writestr("request.json", json.dumps({"schema": "route-video-onepass-v2", "job_id": "t", "style": "liberty",
                                                       "route": {"from": "A town", "to": "B town"}}))
                z.writestr("download-report.json", "{}")
                z.writestr("assets/styles/liberty/style.json", json.dumps(style))
                z.writestr("assets/tilejson/planet.json", json.dumps({"tiles": [tpl]}))
                z.writestr("assets/tiles/6/17/25.pbf", b"t")
                z.writestr("assets/fonts/Noto_Sans_Bold/0-255.pbf", b"g")
                z.writestr("assets/sprites/ofm_f384/ofm@2x.png", b"s")
                z.writestr("assets/geocode/endpoints.json", json.dumps({"from": {"name": "A town", "coordinates": [-77, 38]},
                                                                        "to": {"name": "B town", "coordinates": [-82, 37]}}))
                z.writestr("assets/route/route.json", json.dumps({"code": "Ok", "routes": []}))
            convert(src, tmp / "pack.zip")
            p = P.open_pack(tmp / "pack.zip", tmp / "x")
            self.assertEqual(p.get(OFM + "/planet/20261025_080012_pt/6/17/25.pbf"), b"t")
            self.assertEqual(p.get(OFM + "/fonts/Noto%20Sans%20Bold/0-255.pbf"), b"g")
            self.assertEqual(p.get(OFM + "/sprites/ofm_f384/ofm@2x.png"), b"s")
            self.assertEqual(json.loads(p.get(OFM + "/styles/liberty")), style)
            self.assertEqual(p.data("geocode.json")["A town"][:2], [-77, 38])
            self.assertEqual(p.manifest["route"], {"from": "A town", "to": "B town"})
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
