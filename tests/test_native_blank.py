"""Native MapLibre must survive blank map resources (offline packs with gaps, 204/404 online).

    python3 -m unittest tests.test_native_blank -v

--asset-plan always runs with --on-missing blank, so every resource a pack lacks is answered "blank". Native MapLibre
6.4.1 is picky about what blank means (measured on Linux x64, Node 22):

    missing resource   answered {}        answered with an empty buffer
    vector tile        ok                 ok
    raster tile        ok                 error "unsupported image type"
    glyph range        SEGFAULT           ok
    sprite             render never ends  error "unsupported image type"

A ChatGPT runtime's --asset-plan segfaulted in the intro hold of a partial pack (sampled tiles and "initial fonts"):
the glyph row. The worker now answers with blankAnswer() from tools/pack.py, and this test renders a style that uses
every kind of resource (raster, vector, glyphs, sprite) with all of them missing, through that function.

It uses the renderer's own native module, <cache>/node3 (ROUTEVID_CACHE, default ~/.cache/routevid), with
<cache>/node3/lib on LD_LIBRARY_PATH for a portable bundle, under xvfb-run. Skipped when any of that is missing,
so the quick tests stay quick and offline.
"""
import os, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tools import pack as P

CACHE = Path(os.environ.get("ROUTEVID_CACHE", os.path.expanduser("~/.cache/routevid")))
NODE_DIR = CACHE / "node3"
MODULE = NODE_DIR / "node_modules" / "@maplibre" / "maplibre-gl-native"

SCRIPT = P.PACK_JS + r"""
const mbgl=require(process.argv[2]);const only=process.argv[3];
const B='https://tiles.openfreemap.org';
const sources={
  relief:{type:'raster',tiles:[B+'/natural_earth/ne2sr/{z}/{x}/{y}.png'],tileSize:256,maxzoom:6},
  planet:{type:'vector',tiles:[B+'/planet/20261025_080012_pt/{z}/{x}/{y}.pbf'],maxzoom:14},
  pt:{type:'geojson',data:{type:'FeatureCollection',features:[{type:'Feature',properties:{t:'Billings, Montana'},geometry:{type:'Point',coordinates:[-108.5,45.8]}}]}}};
const layers={
  relief:{id:'relief',type:'raster',source:'relief',paint:{'raster-opacity':0.5}},
  planet:{id:'water',type:'fill',source:'planet','source-layer':'water',paint:{'fill-color':'#a0c8f0'}},
  glyphs:{id:'label',type:'symbol',source:'pt',layout:{'text-field':['get','t'],'text-font':['Noto Sans Regular']}},
  sprite:{id:'icon',type:'symbol',source:'pt',layout:{'icon-image':'town'}}};
const use=only==='all'?Object.keys(layers):[only];
const style={version:8,sources:{},layers:[{id:'bg',type:'background',paint:{'background-color':'#f8f4f0'}}]};
if(use.includes('glyphs'))style.glyphs=B+'/fonts/{fontstack}/{range}.pbf';
if(use.includes('sprite'))style.sprite=B+'/sprites/ofm_f384/ofm';
for(const k of use){const l=layers[k];style.layers.push(l);style.sources[l.source]=sources[l.source];}
const map=new mbgl.Map({request:(r,cb)=>cb(null,blankAnswer(r.url)),ratio:1.5});map.load(style);
const cams=[{zoom:2,center:[-95,40]},{zoom:5.5,center:[-100,46]},{zoom:15,center:[-108.5,45.8],pitch:40,bearing:30}];
(async()=>{for(const c of cams){
  const b=await new Promise((res,rej)=>map.render({...c,width:256,height:256},(e,x)=>e?rej(e):res(x)));
  if(b.length!==256*256*4*1.5*1.5)throw new Error('frame size '+b.length);}
 map.release();console.log('ok '+cams.length);})().catch(e=>{console.log('render error: '+e.message);process.exit(3);});
"""


@unittest.skipUnless(MODULE.exists() and shutil.which("node") and shutil.which("xvfb-run"),
                     f"needs native MapLibre in {NODE_DIR}, node and xvfb-run")
class BlankResources(unittest.TestCase):
    def render_blank(self, only):
        with tempfile.TemporaryDirectory() as d:
            js = Path(d) / "blank.js"; js.write_text(SCRIPT)
            env = dict(os.environ)
            if (NODE_DIR / "lib").is_dir():
                env["LD_LIBRARY_PATH"] = str(NODE_DIR / "lib") + (":" + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else "")
            try:
                p = subprocess.run(["xvfb-run", "-a", "-s", "-screen 0 1280x720x24", "node", str(js), str(MODULE), only],
                                   capture_output=True, text=True, timeout=90, env=env)
            except subprocess.TimeoutExpired:
                self.fail(f"{only}: the render never finished (a blank answer MapLibre waits on forever)")
            # a segfault is exit -11, or 139 through xvfb-run's shell
            self.assertEqual(p.returncode, 0, f"{only}: exit {p.returncode}\n{p.stdout}\n{p.stderr[-2000:]}")
            self.assertIn("ok 3", p.stdout)

    def test_raster_tiles_missing(self): self.render_blank("relief")
    def test_vector_tiles_missing(self): self.render_blank("planet")
    def test_glyphs_missing(self): self.render_blank("glyphs")
    def test_sprite_missing(self): self.render_blank("sprite")
    def test_everything_missing(self): self.render_blank("all")


class BlankAnswerKinds(unittest.TestCase):
    """Which URLs get which blank (needs only node)."""
    @unittest.skipUnless(shutil.which("node"), "needs node")
    def test_kinds(self):
        js = P.PACK_JS + r"""
const k=u=>{const a=blankAnswer(u);return a.data===undefined?'none':a.data.length===0?'empty':a.data[0]===0x89?'png':a.data.toString();};
console.log(JSON.stringify([
 k('https://tiles.openfreemap.org/planet/20261025_080012_pt/6/17/25.pbf'),
 k('https://tiles.openfreemap.org/natural_earth/ne2sr/5/10/10.png'),
 k('https://tiles.openfreemap.org/fonts/Noto%20Sans%20Bold/256-511.pbf'),
 k('https://tiles.openfreemap.org/sprites/ofm_f384/ofm@2x.json'),
 k('https://tiles.openfreemap.org/sprites/ofm_f384/ofm@2x.png')]));
"""
        out = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=30).stdout.strip()
        self.assertEqual(out, '["none","none","empty","{}","png"]')


if __name__ == "__main__":
    unittest.main()
