"""Pick, download and host one product photo per model. Called from build.py.

Candidates come from the `images` table the collector fills (first Shopify product image per matched product).
Files land in static/img/models/<model_slug>.webp (committed, so each run only fetches photos for new models);
data/images.json remembers which source URL each file came from and which URLs failed the quality check."""
import io, json, time, urllib.request
from pathlib import Path
from PIL import Image, ImageStat, ImageChops

ROOT = Path(__file__).resolve().parent
DIR = ROOT / "static" / "img" / "models"
MANIFEST = ROOT / "data" / "images.json"
UA = "TwigDealsBot/0.1 (+https://twigdeals.com/about)"
STORE_RANK = ["bauer", "discounthockey", "sportsexcellence", "thehockeyshop", "prohockeylife", "sourceforsports", "justhockey", "hockeytron", "hockeystickman"]
SIZE_RANK = {"Senior": 0, "Intermediate": 1, "Junior": 2, "Youth": 3, None: 4}
MAX_TRY = 40; WIDTH = 800; VERSION = 3  # v2: all product images, looser bg check, trimmed + centred on square canvas

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r: return r.read()

def ring_stats(im):
    g = im.convert("L"); w, h = g.size; b = max(4, min(w, h) // 25)
    ring = [g.crop((0, 0, w, b)), g.crop((0, h - b, w, h)), g.crop((0, 0, b, h)), g.crop((w - b, 0, w, h))]
    st = [ImageStat.Stat(r) for r in ring]
    return sum(x.mean[0] for x in st) / 4, max(x.stddev[0] for x in st)

def clean_shot(im):
    """Studio shot: plain white / off-white / light grey background. At least 93% of the border ring must be
    background-coloured (a stick may cross the edge; scenes, collages and charts break the ring)."""
    g = im.convert("L"); w, h = g.size; b = max(4, min(w, h) // 25)
    px = []
    for r in (g.crop((0, 0, w, b)), g.crop((0, h - b, w, h)), g.crop((0, 0, b, h)), g.crop((w - b, 0, w, h))):
        px += list(r.resize((max(1, r.width // 4), max(1, r.height // 4))).getdata())
    px.sort(); bg = px[len(px) // 2]
    near = sum(abs(v - bg) <= 14 for v in px) / len(px)
    return w >= 400 and h >= 400 and bg >= 200 and near >= 0.93

def frame(im):
    """Trim background, centre the stick on a square canvas of the background colour with a fixed margin."""
    g = im.convert("RGB"); w, h = g.size; b = max(4, min(w, h) // 25)
    bg = tuple(int(v) for v in ImageStat.Stat(g.crop((0, 0, w, b))).median)
    diff = ImageChops.difference(g, Image.new("RGB", g.size, bg)).convert("L").point(lambda v: 255 if v > 28 else 0)
    box = diff.getbbox()
    if not box: return None
    m = max(2, min(w, h) // 100)  # stick runs off the frame: a detail/close-up crop, not a full product shot
    if sum((box[0] <= m, box[1] <= m, box[2] >= w - m, box[3] >= h - m)) >= 3: return None  # close-up / detail crop
    g = g.crop(box); side = round(max(g.size) * 1.08)
    c = Image.new("RGB", (side, side), bg); c.paste(g, ((side - g.width) // 2, (side - g.height) // 2))
    return c.resize((WIDTH, WIDTH), Image.LANCZOS) if side > WIDTH else c

def process(raw, trim=True):
    im = Image.open(io.BytesIO(raw)); im.load()
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA"); bg = Image.new("RGBA", im.size, (255, 255, 255, 255)); bg.alpha_composite(im); im = bg
    im = im.convert("RGB")
    if not clean_shot(im): return None
    return frame(im)

def pick(db, slugs):
    """-> {slug: {"file": "/img/models/x.webp", "w":..., "h":..., "store":...}} for models that have a good photo."""
    DIR.mkdir(parents=True, exist_ok=True)
    man = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    out = {}; fetched = 0
    rows = db.execute("""SELECT i.store, i.model_slug, i.size, COALESCE(s.src, i.src), i.title, COALESCE(s.pos, 0)
        FROM images i LEFT JOIN image_srcs s ON s.store=i.store AND s.handle=i.handle WHERE i.pro_stock=0""").fetchall()
    cands = {}; seen = set()
    for store, slug, size, src, title, pos in rows:
        if src in seen: continue
        seen.add(src); cands.setdefault(slug, []).append((store, size, src, title, pos))
    block = set(json.loads((ROOT / "data" / "image_blocklist.json").read_text())) if (ROOT / "data" / "image_blocklist.json").exists() else set()
    for slug in slugs:
        cs = sorted(cands.get(slug, []), key=lambda c: (SIZE_RANK.get(c[1], 4), c[4] > 0, c[4], STORE_RANK.index(c[0]) if c[0] in STORE_RANK else 99, c[3]))
        ent = man.get(slug, {}); f = DIR / f"{slug}.webp"
        if ent.get("src") and ent["src"].split("?")[0] not in block and f.exists() and any(c[2] == ent["src"] for c in cs):  # still offered by a store: keep the cached file
            out[slug] = ent; continue
        rejected = set(ent.get("rejected", [])) if ent.get("v") == VERSION else set(); ent = {"rejected": sorted(rejected)}; tried = 0
        for store, size, src, title, pos in cs:
            if src in rejected or src.split("?")[0] in block or tried >= MAX_TRY: continue
            tried += 1
            try:
                im = process(fetch(src)); fetched += 1; time.sleep(0.4)
            except Exception: rejected.add(src); continue
            if im is None: rejected.add(src); continue
            im.save(f, "WEBP", quality=82, method=6)
            ent.update(src=src, file=f"/img/models/{slug}.webp", w=im.width, h=im.height, store=store, size=size); break
        ent["rejected"] = sorted(rejected)[-60:]; ent["v"] = VERSION
        man[slug] = ent
        if ent.get("file"): out[slug] = ent
        elif f.exists(): f.unlink()
    MANIFEST.write_text(json.dumps(man, indent=1, sort_keys=True))
    print(f"images: {len(out)}/{len(slugs)} models have a photo ({fetched} downloaded)")
    return out
