"""Pick, download and host one product photo per model. Called from build.py.

Candidates come from the `images` table the collector fills (first Shopify product image per matched product).
Files land in static/img/models/<model_slug>.webp (committed, so each run only fetches photos for new models);
data/images.json remembers which source URL each file came from and which URLs failed the quality check."""
import io, json, time, urllib.request
from pathlib import Path
from PIL import Image, ImageStat

ROOT = Path(__file__).resolve().parent
DIR = ROOT / "static" / "img" / "models"
MANIFEST = ROOT / "data" / "images.json"
UA = "TwigDealsBot/0.1 (+https://twigdeals.com/about)"
STORE_RANK = ["bauer", "discounthockey", "sportsexcellence", "thehockeyshop", "prohockeylife", "sourceforsports", "justhockey", "hockeytron", "hockeystickman"]
SIZE_RANK = {"Senior": 0, "Intermediate": 1, "Junior": 2, "Youth": 3, None: 4}
MAX_TRY = 6; WIDTH = 800

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r: return r.read()

def clean_shot(im):
    """Studio shot: light, plain background. Checks the border ring brightness and spread."""
    g = im.convert("L"); w, h = g.size; b = max(4, min(w, h) // 25)
    ring = [g.crop((0, 0, w, b)), g.crop((0, h - b, w, h)), g.crop((0, 0, b, h)), g.crop((w - b, 0, w, h))]
    stats = [ImageStat.Stat(r) for r in ring]
    mean = sum(s.mean[0] for s in stats) / 4; sd = max(s.stddev[0] for s in stats)
    return w >= 400 and h >= 400 and mean >= 228 and sd <= 22

def process(raw):
    im = Image.open(io.BytesIO(raw)); im.load()
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA"); bg = Image.new("RGBA", im.size, (255, 255, 255, 255)); bg.alpha_composite(im); im = bg
    im = im.convert("RGB")
    if not clean_shot(im): return None
    if im.width > WIDTH: im = im.resize((WIDTH, round(im.height * WIDTH / im.width)), Image.LANCZOS)
    return im

def pick(db, slugs):
    """-> {slug: {"file": "/img/models/x.webp", "w":..., "h":..., "store":...}} for models that have a good photo."""
    DIR.mkdir(parents=True, exist_ok=True)
    man = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    out = {}; fetched = 0
    rows = db.execute("SELECT store, model_slug, size, src, title FROM images WHERE pro_stock=0").fetchall()
    cands = {}
    for store, slug, size, src, title in rows: cands.setdefault(slug, []).append((store, size, src, title))
    for slug in slugs:
        cs = sorted(cands.get(slug, []), key=lambda c: (SIZE_RANK.get(c[1], 4), STORE_RANK.index(c[0]) if c[0] in STORE_RANK else 99, c[3]))
        ent = man.get(slug, {}); f = DIR / f"{slug}.webp"
        if ent.get("src") and f.exists() and any(c[2] == ent["src"] for c in cs):  # still offered by a store: keep the cached file
            out[slug] = ent; continue
        rejected = set(ent.get("rejected", [])); ent = {"rejected": sorted(rejected)}; tried = 0
        for store, size, src, title in cs:
            if src in rejected or tried >= MAX_TRY: continue
            tried += 1
            try:
                im = process(fetch(src)); fetched += 1; time.sleep(0.4)
            except Exception: rejected.add(src); continue
            if im is None: rejected.add(src); continue
            im.save(f, "WEBP", quality=82, method=6)
            ent.update(src=src, file=f"/img/models/{slug}.webp", w=im.width, h=im.height, store=store, size=size); break
        ent["rejected"] = sorted(rejected)[-30:]
        man[slug] = ent
        if ent.get("file"): out[slug] = ent
        elif f.exists(): f.unlink()
    MANIFEST.write_text(json.dumps(man, indent=1, sort_keys=True))
    print(f"images: {len(out)}/{len(slugs)} models have a photo ({fetched} downloaded)")
    return out
