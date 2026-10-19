#!/usr/bin/env python3
"""Twig Deals price collector: Shopify /products.json -> SQLite price history."""
import csv, json, re, sqlite3, sys, time, urllib.request, urllib.robotparser
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "prices.db"
SEED = ROOT / "data" / "seed_sticks.csv"
UA = "TwigDealsBot/0.1 (+https://twigdeals.com/about)"
DELAY = 3.0  # seconds between requests per store
STORES = [
    dict(id="bauer", name="Bauer.com", base="https://www.bauer.com", currency="USD"),
    dict(id="prohockeylife", name="Pro Hockey Life", base="https://www.prohockeylife.com", currency="CAD"),
    dict(id="sourceforsports", name="Source for Sports", base="https://www.sourceforsports.ca", currency="CAD"),
    dict(id="hockeystickman", name="HockeyStickMan", base="https://www.hockeystickman.com", currency="USD"),
]
EXCLUDE = re.compile(r"\b(mini|tape|wax|bag|rack|grip tape|blade only|replacement blade|street|ball hockey|goalie|knob|plug|extension|pants|gloves?|skates?|helmet|tee|hoodie|polo|shirt|sock|pucks?|toe system|holder)\b|^mybauer", re.I)

def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())

def allowed(base, path="/products.json"):
    rp = urllib.robotparser.RobotFileParser(base + "/robots.txt")
    try: rp.read()
    except Exception: return True
    return rp.can_fetch(UA, base + path)

def load_models():
    rows = list(csv.DictReader(open(SEED)))
    # longest model names first so "Ribcor Trigger 10" beats "Ribcor Trigger"
    return sorted(rows, key=lambda r: -len(r["model"]))

def slug(s): return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")

TIER_WORDS = ["top shaft", "pro", "team", "elite", "strike", "rev", "plus", "max", "unleashed", "legend", "morph", "2", "3", "4", "5"]

def tier_name(model, title):
    """Base seed model + sub-tier from the product title, e.g. Code Encrypt -> Code Encrypt 4 / Code Encrypt Pro,
    Jetspeed FT8 -> Jetspeed FT880 / Jetspeed FT8 Pro, Hzrdus 9X -> Hzrdus 9X4."""
    t = re.sub(r"\s+", " ", title)
    i = t.lower().find(model.lower())
    if i < 0: return model
    rest = t[i + len(model):]
    adj = re.match(r"[0-9A-Za-z+]*", rest).group(0)
    if adj and (adj[0].isdigit() or adj.upper() in ("X", "+")):
        last = model.split()[-1]
        name = model + adj.upper() if any(ch.isdigit() for ch in last) else f"{model} {adj.upper()}"
    else:
        name = model
    rest = rest[len(adj):] if name != model else rest
    while True:
        r = rest.lstrip(" -").lower()
        w = next((w for w in TIER_WORDS if r.startswith(w) and (len(r) == len(w) or not r[len(w)].isalnum())), None)
        if not w: break
        word = w.upper() if w.isdigit() else w.title()
        if not name.endswith(" " + word): name += " " + word
        rest = rest.lstrip(" -")[len(w):]
    return name

def size_of(title, ptype):
    t = f"{title} {ptype}".lower()
    for k, v in [("senior", "Senior"), (" sr", "Senior"), ("intermediate", "Intermediate"), (" int", "Intermediate"),
                 ("junior", "Junior"), (" jr", "Junior"), ("youth", "Youth"), ("yth", "Youth")]:
        if k in t: return v
    return None

def opt(product, variant, pattern):
    for i, o in enumerate(product.get("options", [])[:3]):
        if re.search(pattern, o["name"], re.I):
            v = variant.get(f"option{i+1}")
            return v if v not in (None, ".", "Default Title") else None
    return None

def specs(p, v):
    hand, flex, curve = opt(p, v, r"hand"), opt(p, v, r"flex"), opt(p, v, r"curve|pattern|blade")
    combo = opt(p, v, r"spec")  # e.g. HockeyStickMan: "Right - P28 (McDavid) - 65 Flex/58\" (Blade 6)"
    if combo and not (hand or flex or curve):
        m = re.match(r"\s*(Left|Right)\s*-\s*([^-(]+?)\s*(?:\([^)]*\))?\s*-\s*(\d{2,3})\s*Flex", combo, re.I)
        if m: hand, curve, flex = m.group(1).title(), m.group(2).strip(), m.group(3)
    if flex: flex = re.sub(r"\s*flex", "", flex, flags=re.I).strip()
    return hand, flex, curve

def init(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS variants(id TEXT PRIMARY KEY, store TEXT, model_slug TEXT, brand TEXT, model TEXT,
      product_title TEXT, url TEXT, size TEXT, hand TEXT, flex TEXT, curve TEXT, currency TEXT, pro_stock INTEGER,
      first_seen TEXT, last_seen TEXT);
    CREATE TABLE IF NOT EXISTS prices(variant_id TEXT, ts TEXT, price REAL, compare_at REAL, available INTEGER);
    CREATE INDEX IF NOT EXISTS ix_prices ON prices(variant_id, ts);
    CREATE TABLE IF NOT EXISTS runs(ts TEXT, store TEXT, products INTEGER, matched INTEGER, variants INTEGER, status TEXT);
    """)

def collect_store(db, store, models, ts):
    if not allowed(store["base"]):
        db.execute("INSERT INTO runs VALUES(?,?,?,?,?,?)", (ts, store["id"], 0, 0, 0, "blocked by robots.txt")); return
    nprod = nmatch = nvar = 0; status = "ok"
    for page in range(1, 60):
        try:
            data = get(f"{store['base']}/products.json?limit=250&page={page}")
        except Exception as e:
            status = f"error page {page}: {e}"; break
        prods = data.get("products", [])
        if not prods: break
        nprod += len(prods)
        for p in prods:
            title, ptype = p["title"], p.get("product_type", "")
            if not re.search(r"stick", f"{title} {ptype}", re.I) or EXCLUDE.search(title): continue
            m = next((m for m in models if m["model"].lower() in title.lower()
                      and (m["brand"].lower() in title.lower() or m["brand"].lower() in p.get("vendor", "").lower()
                           or store["id"] == "bauer")), None)
            if not m: continue
            nmatch += 1
            pro = 1 if re.search(r"pro stock|used|refurb", f"{title} {ptype}", re.I) else 0
            size = size_of(title, ptype)
            tname = tier_name(m["model"], title)
            for v in p["variants"]:
                vid = f"{store['id']}:{v['id']}"
                row = (vid, store["id"], slug(m["brand"] + " " + tname), m["brand"], tname, title,
                       f"{store['base']}/products/{p['handle']}?variant={v['id']}", size,
                       *specs(p, v),
                       store["currency"], pro, ts, ts)
                db.execute("""INSERT INTO variants VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET last_seen=excluded.last_seen, product_title=excluded.product_title, size=excluded.size, hand=excluded.hand, flex=excluded.flex, curve=excluded.curve, pro_stock=excluded.pro_stock, model=excluded.model, model_slug=excluded.model_slug""", row)
                ca = float(v["compare_at_price"]) if v.get("compare_at_price") else None
                db.execute("INSERT INTO prices VALUES(?,?,?,?,?)", (vid, ts, float(v["price"]), ca, 1 if v.get("available") else 0))
                nvar += 1
        time.sleep(DELAY)
    db.execute("INSERT INTO runs VALUES(?,?,?,?,?,?)", (ts, store["id"], nprod, nmatch, nvar, status))
    print(f"{store['name']}: {nprod} products scanned, {nmatch} matched, {nvar} variants, {status}")

def retier():
    """Re-derive sub-tier names for stored variants without re-fetching stores."""
    db = sqlite3.connect(DB); models = load_models(); n = 0
    for vid, title, brand in db.execute("SELECT id, product_title, brand FROM variants").fetchall():
        m = next((m for m in models if m["model"].lower() in title.lower() and m["brand"] == brand), None)
        if not m: continue
        t = tier_name(m["model"], title)
        db.execute("UPDATE variants SET model=?, model_slug=? WHERE id=?", (t, slug(brand + " " + t), vid)); n += 1
    db.commit(); print(f"retiered {n} variants")

def main():
    if "--retier" in sys.argv: return retier()
    DB.parent.mkdir(exist_ok=True)
    db = sqlite3.connect(DB); init(db)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    models = load_models()
    for s in STORES:
        collect_store(db, s, models, ts); db.commit()
    db.close()

if __name__ == "__main__":
    main()
