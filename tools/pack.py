"""route-video-pack-v1: one asset format for every way of getting map data to routevid3.

A pack is a ZIP (or an already-unpacked folder) holding everything one trip needs, so the
renderer can run with no network at all:

    pack.json                     manifest: schema, route, style, and a sha256 + size for every file
    http/<host>/<path>            each map resource (style, TileJSON, tiles, sprites, glyphs) stored
                                  under the URL it is requested by; see url_to_path() for the exact rule
    data/geocode.json             {"<query as typed>": [lon, lat, "display name"]}
    data/route.json               the OSRM /route response, unchanged (overview=full, geometries=geojson, steps=true)
    data/reverse.json             {"<lat>,<lon>" (3 decimals): "Town, ST"}  place names for turn cards and narration

Anything that writes this layout works: routevid3 --make-pack (online), the browser fetcher, or a hand-built
folder. docs/PACK_FORMAT.md is the human-readable spec; tests/test_pack.py pins the behaviour, including that
the JavaScript resolver used inside the map worker (PACK_JS) maps URLs exactly like url_to_path().
"""
import hashlib, json, os, re, shutil, stat, urllib.parse, zipfile
from pathlib import Path, PurePosixPath

SCHEMA = "route-video-pack-v1"
NEEDS_SCHEMA = "route-video-needs-v1"
LIMITS = dict(entries=100_000, entry_bytes=64 * 2**20, total_bytes=4 * 2**30)
ROOTS = ("http/", "data/")
TILE_RE = re.compile(r"^http/([^/]+)/(.*?)/?([^/]+)/(\d+)/(\d+)/(\d+)\.([A-Za-z0-9]+)$")


class PackError(ValueError):
    pass


def url_to_path(url):
    """Map a resource URL to its file in the pack.

    http/<host lower-case>/<percent-decoded path>; a last segment with no "." gets "/index" appended
    (so ".../planet" and ".../planet/<version>/6/17/25.pbf" can both exist); a query string becomes
    "@<first 16 hex of sha1(query)>" on the end. Only http(s) URLs with a host are allowed.
    """
    u = urllib.parse.urlsplit(url)
    if u.scheme not in ("http", "https") or not u.hostname: raise PackError(f"not an http(s) URL: {url}")
    parts = [urllib.parse.unquote(p) for p in u.path.split("/") if p != ""]
    if any(p in (".", "..") or "\\" in p or "\x00" in p for p in parts): raise PackError(f"unsafe URL path: {url}")
    if not parts or "." not in parts[-1]: parts.append("index")
    if u.query: parts[-1] += "@" + hashlib.sha1(u.query.encode()).hexdigest()[:16]
    return "/".join(["http", u.hostname.lower()] + parts)


def tile_key(path):
    """Version-free key for a tile path: host/prefix/z/x/y.ext (drops the segment before z, e.g. a dated
    OpenFreeMap build like 20261025_080012_pt), so a pack can serve a tile requested under another build."""
    m = TILE_RE.match(path)
    return f"{m.group(1)}/{m.group(2)}/{m.group(4)}/{m.group(5)}/{m.group(6)}.{m.group(7)}" if m else None


# The same mapping in JavaScript, embedded in the map worker. Keep in step with url_to_path/tile_key;
# tests/test_pack.py runs both on the same URLs.
PACK_JS = r"""
function packPath(url){const raw=url.split(/[?#]/)[0].replace(/^[a-z][a-z0-9+.-]*:\/\/[^/]*/i,'');
 if(raw.split('/').some(s=>/^(\.|%2e){1,2}$/i.test(s)))throw new Error('unsafe URL path: '+url);  // before URL() normalizes them away
 const u=new URL(url);if(!/^https?:$/.test(u.protocol)||!u.hostname)throw new Error('not an http(s) URL: '+url);
 const parts=u.pathname.split('/').filter(p=>p!=='').map(p=>decodeURIComponent(p));
 if(parts.some(p=>p==='.'||p==='..'||p.includes('\\')||p.includes('\0')))throw new Error('unsafe URL path: '+url);
 if(!parts.length||!parts[parts.length-1].includes('.'))parts.push('index');
 const q=u.search.replace(/^\?/,'');if(q)parts[parts.length-1]+='@'+require('crypto').createHash('sha1').update(q).digest('hex').slice(0,16);
 return ['http',u.hostname.toLowerCase(),...parts].join('/');}
const TILE_RE=/^http\/([^/]+)\/(.*?)\/?([^/]+)\/(\d+)\/(\d+)\/(\d+)\.([A-Za-z0-9]+)$/;
function tileKey(p){const m=TILE_RE.exec(p);return m?`${m[1]}/${m[2]}/${m[4]}/${m[5]}/${m[6]}.${m[7]}`:null;}
"""


def sha256_file(path, buf=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while b := f.read(buf): h.update(b)
    return h.hexdigest()


def _check_name(name):
    p = PurePosixPath(name)
    if (not name or name.startswith("/") or "\\" in name or "\x00" in name or re.match(r"^[A-Za-z]:", name)
            or any(s in ("", ".", "..") for s in name.rstrip("/").split("/"))):
        raise PackError(f"unsafe path in pack: {name!r}")
    if name != "pack.json" and not name.startswith(ROOTS): raise PackError(f"unexpected file in pack: {name!r}")
    return p


def _check_manifest(man, present):
    if not isinstance(man, dict) or man.get("schema") != SCHEMA: raise PackError(f"pack.json schema must be {SCHEMA!r}")
    files = man.get("files")
    if not isinstance(files, dict): raise PackError("pack.json needs a 'files' table")
    unlisted = sorted(set(present) - set(files))
    if unlisted: raise PackError(f"{len(unlisted)} files are not listed in pack.json, e.g. {unlisted[:3]}")
    absent = sorted(set(files) - set(present))
    if absent: raise PackError(f"{len(absent)} files listed in pack.json are missing, e.g. {absent[:3]}")
    for name, meta in files.items():
        _check_name(name)
        if not re.fullmatch(r"[0-9a-f]{64}", str(meta.get("sha256", ""))): raise PackError(f"bad sha256 for {name}")
    r = man.get("route") or {}
    if not (isinstance(r.get("from"), str) and isinstance(r.get("to"), str)): raise PackError("pack.json needs route.from and route.to")


def validate_zip(path, limits=LIMITS):
    """Check a pack ZIP without extracting: safe names, no links, size limits, manifest, sizes. Returns pack.json."""
    with zipfile.ZipFile(path) as z:
        infos = z.infolist()
        if len(infos) > limits["entries"]: raise PackError(f"too many entries ({len(infos)} > {limits['entries']})")
        seen, total, files = set(), 0, {}
        for i in infos:
            if i.is_dir(): continue
            _check_name(i.filename)
            if i.filename.lower() in seen: raise PackError(f"duplicate entry {i.filename!r}")
            seen.add(i.filename.lower())
            mode = (i.external_attr >> 16) & 0o170000
            if mode and mode not in (stat.S_IFREG,): raise PackError(f"not a regular file: {i.filename!r}")
            if i.file_size > limits["entry_bytes"]: raise PackError(f"entry too large: {i.filename!r}")
            total += i.file_size
            if total > limits["total_bytes"]: raise PackError("pack too large")
            if i.compress_size and i.file_size / i.compress_size > 1000: raise PackError(f"suspicious compression ratio: {i.filename!r}")
            files[i.filename] = i.file_size
        if "pack.json" not in files: raise PackError("pack.json missing")
        man = json.loads(z.read("pack.json"))
        present = [n for n in files if n != "pack.json"]
        _check_manifest(man, present)
        for n in present:
            if man["files"][n].get("size") not in (None, files[n]): raise PackError(f"size mismatch for {n}")
    return man


def open_pack(src, extract_root):
    """Validate a pack (ZIP or folder) and return a Pack. ZIPs are unpacked once into extract_root/<sha256 of zip>;
    every file's sha256 is checked against pack.json before the pack is used."""
    src = Path(src).expanduser().resolve()
    if src.is_dir():
        root = src
        present = []
        for p in root.rglob("*"):
            if p.is_symlink(): raise PackError(f"symlink in pack folder: {p}")
            if p.is_file():
                rel = p.relative_to(root).as_posix()
                if rel != "pack.json" and rel not in (".verified",): present.append(rel)
        man = json.loads((root / "pack.json").read_text())
        _check_manifest(man, present)
        for n in present: _check_name(n)
        _verify_hashes(root, man)
        idx = Path(extract_root).expanduser() / ("dir-" + hashlib.sha1(str(root).encode()).hexdigest()[:16] + ".tileindex.json")
        return Pack(root, man, idx)
    if not zipfile.is_zipfile(src): raise PackError(f"not a ZIP or folder: {src}")
    man = validate_zip(src)
    root = Path(extract_root).expanduser() / sha256_file(src)
    if not (root / ".verified").exists():
        tmp = root.with_name(root.name + ".tmp")
        shutil.rmtree(tmp, ignore_errors=True); tmp.mkdir(parents=True)
        with zipfile.ZipFile(src) as z:
            for i in z.infolist():
                if i.is_dir(): continue
                target = (tmp / i.filename).resolve()
                if not str(target).startswith(str(tmp.resolve()) + os.sep): raise PackError(f"unsafe path {i.filename!r}")
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(i) as a, open(target, "wb") as b: shutil.copyfileobj(a, b, 1 << 20)
        _verify_hashes(tmp, man)
        (tmp / ".verified").write_text("ok\n")
        shutil.rmtree(root, ignore_errors=True); tmp.rename(root)
    return Pack(root, man, root.with_name(root.name + ".tileindex.json"))


def _verify_hashes(root, man):
    bad = [n for n, meta in man["files"].items() if sha256_file(root / n) != meta["sha256"]]
    if bad: raise PackError(f"sha256 mismatch for {len(bad)} files, e.g. {bad[:3]}")


class Pack:
    def __init__(self, root, manifest, index_file):
        self.root, self.manifest = Path(root), manifest
        self.tiles = {}
        for n in sorted(manifest["files"]):
            k = tile_key(n)
            if k: self.tiles.setdefault(k, n)
        self.index_file = Path(index_file)             # read by the map worker: version-free tile key -> path
        self.index_file.parent.mkdir(parents=True, exist_ok=True)
        self.index_file.write_text(json.dumps(self.tiles))

    def path_for(self, url):
        p = url_to_path(url)
        if p in self.manifest["files"]: return p
        k = tile_key(p)
        return self.tiles.get(k) if k else None

    def get(self, url):
        p = self.path_for(url)
        return (self.root / p).read_bytes() if p else None

    def data(self, name, default=None):
        p = self.root / "data" / name
        return json.loads(p.read_text()) if p.exists() else default


def reverse_key(lon, lat):
    return f"{lat:.3f},{lon:.3f}"


def write_pack(out_zip, route, style, resources, data, meta=None):
    """Write a pack ZIP. resources: {url: bytes}; data: {"route.json": obj, ...}. Returns the manifest."""
    files, blobs = {}, {}
    for url, body in resources.items():
        p = url_to_path(url)
        blobs[p] = body
    for name, obj in data.items():
        blobs["data/" + name] = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode()
    for p, b in blobs.items():
        _check_name(p); files[p] = {"sha256": hashlib.sha256(b).hexdigest(), "size": len(b)}
    man = {"schema": SCHEMA, "route": route, "style": style, **(meta or {}), "files": dict(sorted(files.items()))}
    tmp = str(out_zip) + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        z.writestr("pack.json", json.dumps(man, indent=1, ensure_ascii=False))
        for p in sorted(blobs): z.writestr(p, blobs[p])
    os.replace(tmp, out_zip)
    return man
