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
    dict(id="discounthockey", name="Discount Hockey", base="https://discounthockey.com", currency="USD"),
    dict(id="thehockeyshop", name="TheHockeyShop.com", base="https://www.thehockeyshop.com", currency="CAD"),
    dict(id="hockeytron", name="HockeyTron", base="https://hockeytron.com", currency="USD"),
    dict(id="sportsexcellence", name="Sports Excellence", base="https://sportsexcellence.com", currency="CAD"),
]
MAX_PAGES = 100  # TheHockeyShop is ~56 pages of 250
EXCLUDE = re.compile(r"\b(mini|tape|wax|bag|rack|grip tape|blade only|replacement blade|street|ball hockey|goalie|knob|plug|extension|pants|gloves?|skates?|helmet|tee|hoodie|polo|shirt|sock|pucks?|toe system|holder|goal|ringette|lacrosse|field hockey|floorball|floor hockey|dek|roller|inline|in-line|custom|quick turn|tyke|blades?)\b|(?<!top )\bshafts?\b|^mybauer", re.I)
# Store spellings that differ from the seed list (e.g. "FLYLTE", "PROTO 2").
# "Super Tacks AS-V" is CCM's full name for the seed's "Tacks AS-V".
ALIASES = [(re.compile(r"\bflylte\b", re.I), "FlyLite"), (re.compile(r"\bproto 2\b", re.I), "Proto2"),
           (re.compile(r"\bsuper tacks (as-v)\b(?!i)", re.I), r"Tacks \1")]

def has_model(model, title):
    """Model name in title as its own word. A glued digit or single letter is a sub-model that
    tier_name keeps: "Jetspeed FT8"+"80" -> FT880, "Ribcor Trigger 9"+"K" -> 9K, "Tacks AS-V"+"I" -> AS-VI."""
    return re.search(r"(?<![a-z0-9])" + re.escape(model.lower()) + r"(?![a-z]{2})", title.lower()) is not None

def clean_title(title):
    t = re.sub(r"\s+", " ", title).strip()
    for rx, sub in ALIASES: t = rx.sub(sub, t)
    return t

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

TIER_WORDS = ["top shaft", "pro", "team", "elite", "strike", "rev", "plus", "max", "unleashed", "legend", "morph", "xt", "2", "3", "4", "5"]

def tier_name(model, title):
    """Base seed model + sub-tier from the product title, e.g. Code Encrypt -> Code Encrypt 4 / Code Encrypt Pro,
    Jetspeed FT8 -> Jetspeed FT880 / Jetspeed FT8 Pro, Hzrdus 9X -> Hzrdus 9X4."""
    t = re.sub(r"\s+", " ", title)
    i = t.lower().find(model.lower())
    if i < 0: return model
    rest = t[i + len(model):]
    adj = re.match(r"[0-9A-Za-z+]*", rest).group(0)
    if adj and (adj[0].isdigit() or adj.upper() in ("X", "+") or (len(adj) == 1 and adj.isalpha())):
        last = model.split()[-1]
        glue = any(ch.isdigit() for ch in last) or (len(adj) == 1 and adj.isalpha())
        name = model + adj.upper() if glue else f"{model} {adj.upper()}"
    else:
        name = model
    rest = rest[len(adj):] if name != model else rest
    # A separate 2-4 digit tier number is a different stick, e.g. "Tacks XF 70" or the 2017
    # "Super Tacks 9380". Years ("Bauer X 2025") and flex ("... 50 Flex") are not tiers.
    num = re.match(r"\s+(\d{2,4}|AS\d{1,3})\b(?!\s*(?:flex|\"|in\b))", rest, re.I)
    if name == model and num and not re.fullmatch(r"(19|20)\d\d", num.group(1)):
        name = f"{model} {num.group(1).upper()}"; rest = rest[num.end():]
    while True:
        r = rest.lstrip(" -").lower()
        w = next((w for w in TIER_WORDS if r.startswith(w) and (len(r) == len(w) or not r[len(w)].isalnum())), None)
        if w == "pro" and re.match(r"pro[ -](stock|return)", r): w = None  # "Pro Stock" is not the Pro tier
        if not w: break
        word = w.upper() if w.isdigit() or w == "xt" else w.title()
        if not name.endswith(" " + word): name += " " + word
        rest = rest.lstrip(" -")[len(w):]
    # "Super Novium" (2022) is an older line than "Novium"
    if not model.lower().startswith("super") and re.search(r"\bsuper " + re.escape(model.lower()), t.lower()):
        name = "Super " + name
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
    hand, flex, curve = opt(p, v, r"hand|side"), opt(p, v, r"flex"), opt(p, v, r"curve|pattern|blade")
    combo = opt(p, v, r"spec")  # e.g. HockeyStickMan: "Right - P28 (McDavid) - 65 Flex/58\" (Blade 6)"
    if combo and not (hand or flex or curve):
        m = re.match(r"\s*(Left|Right)\s*-\s*([^-(]+?)\s*(?:\([^)]*\))?\s*-\s*(\d{2,3})\s*Flex", combo, re.I)
        if m: hand, curve, flex = m.group(1).title(), m.group(2).strip(), m.group(3)
    hf = re.fullmatch(r"\s*([LR])\s*-\s*(\d{2,3})\s*", hand or "")  # TheHockeyShop pro stock: "Hand / Flex" = "L-90"
    if hf: hand, flex = hf.group(1), hf.group(2)
    if not flex:  # flex only in the title, e.g. "... JUNIOR PLAYER STICK - 40 FLEX"
        m = re.search(r"\b(\d{2,3})\s*flex\b", p.get("title", ""), re.I)
        if m: flex = m.group(1)
    if flex:
        flex = re.sub(r"\s*flex", "", flex, flags=re.I).strip()
        m = re.fullmatch(r"(\d{2,3})\s*\(.*\)", flex)  # "65 (SR)", "50 ( INT)"
        if m: flex = m.group(1)
    if hand: hand = {"LEFT": "Left", "LFT": "Left", "L": "Left", "RIGHT": "Right", "RHT": "Right", "R": "Right"}.get(hand.strip().upper(), hand)
    if hand and re.fullmatch(r"LEF+T", hand.strip(), re.I): hand = "Left"  # "LEFFT" typo
    if curve:  # "P28 +1/4", "P28(+1/4\")" -> "P28+1/4", as the existing stores list it
        curve = re.sub(r"\s*\(\s*\+?\s*1/4\s*\"?\s*\)", "+1/4", curve.strip())
        curve = re.sub(r"\s*\+\s*", "+", curve)
    return hand, flex, curve

def brand_curve(curve, brand):
    """Bauer/CCM curves are P-codes; some stores drop the P ("90T", "92M", "28")."""
    if curve and brand in ("Bauer", "CCM") and re.fullmatch(r"\d{2}[A-Z]{0,2}", curve.strip()): return "P" + curve.strip()
    return curve

def match(p, store, models):
    """-> (seed row, tier name, size, pro_stock) for a player stick that maps to a seed model, else None."""
    title, ptype = clean_title(p["title"]), p.get("product_type", "")
    if not re.search(r"stick", f"{title} {ptype}", re.I) or EXCLUDE.search(title) or EXCLUDE.search(ptype): return None
    m = next((m for m in models if has_model(m["model"], title)
              and (m["brand"].lower() in title.lower() or m["brand"].lower() in p.get("vendor", "").lower()
                   or store["id"] == "bauer")), None)
    if not m: return None
    pro = 1 if re.search(r"pro stock|pro return|used|refurb", f"{title} {ptype}", re.I) else 0
    return m, tier_name(m["model"], title), size_of(title, ptype), pro

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
    for page in range(1, MAX_PAGES + 1):
        try:
            data = get(f"{store['base']}/products.json?limit=250&page={page}")
        except Exception as e:
            status = f"error page {page}: {e}"; break
        prods = data.get("products", [])
        if not prods: break
        nprod += len(prods)
        for p in prods:
            hit = match(p, store, models)
            if not hit: continue
            m, tname, size, pro = hit; title = p["title"]
            nmatch += 1
            for v in p["variants"]:
                if not v.get("price") or float(v["price"]) <= 0: continue  # $0 placeholders
                vid = f"{store['id']}:{v['id']}"
                hand, flex, curve = specs(p, v)
                row = (vid, store["id"], slug(m["brand"] + " " + tname), m["brand"], tname, title,
                       f"{store['base']}/products/{p['handle']}?variant={v['id']}", size,
                       hand, flex, brand_curve(curve, m["brand"]),
                       store["currency"], pro, ts, ts)
                db.execute("""INSERT INTO variants VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET last_seen=excluded.last_seen, product_title=excluded.product_title, size=excluded.size, hand=excluded.hand, flex=excluded.flex, curve=excluded.curve, pro_stock=excluded.pro_stock, model=excluded.model, model_slug=excluded.model_slug""", row)
                ca = float(v["compare_at_price"]) if v.get("compare_at_price") else None
                new = (float(v["price"]), ca, 1 if v.get("available") else 0)
                last = db.execute("SELECT price, compare_at, available FROM prices WHERE variant_id=? ORDER BY ts DESC LIMIT 1", (vid,)).fetchone()
                if last != new:  # store changes only; variants.last_seen records each check
                    db.execute("INSERT INTO prices VALUES(?,?,?,?,?)", (vid, ts, *new))
                nvar += 1
        time.sleep(DELAY)
    db.execute("INSERT INTO runs VALUES(?,?,?,?,?,?)", (ts, store["id"], nprod, nmatch, nvar, status))
    print(f"{store['name']}: {nprod} products scanned, {nmatch} matched, {nvar} variants, {status}")

def retier():
    """Re-derive sub-tier names for stored variants without re-fetching stores."""
    db = sqlite3.connect(DB); models = load_models(); n = 0
    for vid, title, brand in db.execute("SELECT id, product_title, brand FROM variants").fetchall():
        title = clean_title(title)
        m = next((m for m in models if has_model(m["model"], title) and m["brand"] == brand), None)
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
