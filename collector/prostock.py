#!/usr/bin/env python3
"""Pro Stock Hockey (BigCommerce) collector, Player Sticks category only.

Kept apart from retail on purpose: rows go to the prostock / prostock_prices tables, never to
variants/prices, so they can't touch deals, lowest-ever, price history or the store count.

Each run:
  1. Reads the Player Sticks category listing (/player-sticks/?limit=100&page=N, ~12 pages): product id,
     name, URL, price, categories. A stick missing from the listing is treated as sold/removed.
  2. Fetches product pages (BCData JSON + spec table) for sticks it has never seen, then for the
     stalest already-known ones (stock refresh), up to MAX_DETAIL pages per run.
Goalie and used/dented sticks are dropped if they show up in the category; junior/intermediate player sticks stay."""
import html, json, re, sqlite3, sys, time, urllib.error, urllib.request
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from collect import UA, DB, allowed, load_models, match, slug, brand_curve

BASE = "https://www.prostockhockey.com"
CAT = "/player-sticks/"
DELAY = 4.0          # seconds between requests (robots.txt sets no crawl-delay for generic bots)
MAX_PAGES = 30
MAX_DETAIL = int(__import__("os").environ.get("PROSTOCK_MAX_DETAIL", "250"))  # product pages per run (~17 min)
BUDGET_S = int(__import__("os").environ.get("PROSTOCK_BUDGET_S", "1200"))  # hard stop for product pages (CI safety)
REFRESH_H = 24       # re-check stock on known sticks at most once a day
SKIP_CAT = re.compile(r"goalie|used|dented", re.I)  # junior/int sticks inside Player Sticks stay

def fetch(url, tries=4):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
    for i in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=30) as r: return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code == 404: return None
            if e.code not in (429, 500, 502, 503, 504) or i == tries - 1: raise
        except (urllib.error.URLError, TimeoutError):
            if i == tries - 1: raise
        time.sleep(15 * (i + 1))

CARD = re.compile(r'data-entity-id="(\d+)"\s*data-position="\d+"\s*data-name="([^"]*)"\s*data-product-category="([^"]*)"\s*'
                  r'data-product-brand="([^"]*)"\s*data-product-price="\s*([\d.]+)\s*"\s*>\s*<figure[^>]*>\s*<a href="([^"]+)"', re.S)

def listing():
    out = {}
    for n in range(1, MAX_PAGES + 1):
        page = fetch(f"{BASE}{CAT}?limit=100&page={n}"); time.sleep(DELAY)
        if not page: break
        cards = CARD.findall(page)
        new = [c for c in cards if c[0] not in out]
        if not new: break
        for pid, name, cats, brand, price, url in new:
            out[pid] = dict(id=pid, title=html.unescape(name).strip(), cats=" ".join(cats.split()), brand=html.unescape(brand),
                            price=float(price), url=url)
    return out

def parse_detail(page):
    d = {}
    m = re.search(r"var BCData = (\{.*?\});\s*\n", page)
    if m:
        try:
            pa = json.loads(m.group(1))["product_attributes"]
            d["price"] = pa["price"]["without_tax"]["value"]; d["currency"] = pa["price"]["without_tax"]["currency"]
            d["stock"] = pa.get("stock"); d["instock"] = 1 if pa.get("instock") and pa.get("purchasable") else 0
        except Exception: pass
    for k, v in re.findall(r'<dt class="productView-info-name">\s*([^<:]+):\s*</dt>\s*<dd class="productView-info-value">\s*(.*?)\s*</dd>', page, re.S):
        d["spec:" + k.strip()] = html.unescape(re.sub(r"<[^>]+>", "", v)).strip()
    img = re.search(r'<meta property="og:image" content="([^"]+)"', page)
    if img: d["img"] = img.group(1)
    d["used_text"] = bool(re.search(r"may be taped|graphic blemishes|minor scrapes", page, re.I))
    return d

def init(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS prostock(id TEXT PRIMARY KEY, url TEXT, title TEXT, brand TEXT, cats TEXT, player TEXT, team TEXT,
      model TEXT, dressed_as TEXT, model_slug TEXT, hand TEXT, flex TEXT, curve TEXT, retail_curve TEXT, lie TEXT, length TEXT,
      age_group TEXT, grip TEXT, price REAL, currency TEXT, stock INTEGER, instock INTEGER, img TEXT, wear_note INTEGER,
      listed INTEGER, first_seen TEXT, last_seen TEXT, detail_ts TEXT);
    CREATE TABLE IF NOT EXISTS prostock_prices(id TEXT, ts TEXT, price REAL, stock INTEGER, instock INTEGER);
    CREATE TABLE IF NOT EXISTS runs(ts TEXT, store TEXT, products INTEGER, matched INTEGER, variants INTEGER, status TEXT);""")

def model_slug(brand, model, models):
    """Real Model field -> our retail model page slug (same matcher as retail titles), else None."""
    if not model: return None
    hit = match({"title": f"{brand} {model} Stick", "vendor": brand, "product_type": ""}, {"id": "prostockhockey"}, models)
    return slug(hit[0]["brand"] + " " + hit[1]) if hit else None

def run(db, ts):
    models = load_models()
    if not allowed(BASE, CAT): return "blocked by robots.txt", 0, 0
    lst = listing()
    keep = {k: v for k, v in lst.items() if not SKIP_CAT.search(v["cats"].replace("Hockey Sticks/Player Sticks", ""))
            and "/goalie-sticks/" not in v["url"]}
    db.execute("UPDATE prostock SET listed=0")
    for p in keep.values():
        db.execute("""INSERT INTO prostock(id,url,title,brand,cats,price,currency,listed,first_seen,last_seen) VALUES(?,?,?,?,?,?,'USD',1,?,?)
          ON CONFLICT(id) DO UPDATE SET url=excluded.url,title=excluded.title,cats=excluded.cats,price=excluded.price,listed=1,last_seen=excluded.last_seen""",
                   (p["id"], p["url"], p["title"], p["brand"], p["cats"], p["price"], ts, ts))
    # new sticks first, then the stalest stock checks
    todo = [r[0] for r in db.execute("SELECT id FROM prostock WHERE listed=1 AND (detail_ts IS NULL OR detail_ts < ?) ORDER BY detail_ts IS NOT NULL, detail_ts",
                                      (datetime.fromtimestamp(time.time() - REFRESH_H * 3600, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),))][:MAX_DETAIL]
    nd = 0; t0 = time.time()
    for pid in todo:
        if time.time() - t0 > BUDGET_S: print(f"  time budget hit after {nd} pages"); break
        url = keep[pid]["url"]
        try: page = fetch(url)
        except Exception as e: print(f"  {url}: {e}"); time.sleep(DELAY); continue
        time.sleep(DELAY)
        if not page: db.execute("UPDATE prostock SET listed=0 WHERE id=?", (pid,)); continue
        d = parse_detail(page); s = lambda k: d.get("spec:" + k) or None
        model = s("Model"); title = keep[pid]["title"]
        dressed = re.search(r"dressed as (.+?)['\"]?\s+\d{2,3} Flex", title, re.I)
        brand = keep[pid]["brand"]
        db.execute("""UPDATE prostock SET player=?,team=?,model=?,dressed_as=?,model_slug=?,hand=?,flex=?,curve=?,retail_curve=?,lie=?,length=?,
          age_group=?,grip=?,price=coalesce(?,price),currency=coalesce(?,currency),stock=?,instock=?,img=?,wear_note=?,detail_ts=? WHERE id=?""",
          (s("Player"), s("Team"), model, dressed.group(1) if dressed else None, model_slug(brand, model, models), s("Hand"),
           (re.match(r"\d{2,3}", s("Flex") or "") or [None])[0], s("Curve"), s("Similar Retail Curve"), s("Lie"), s("Height") or s("Length"),
           s("Age Group"), s("Grip"), d.get("price"), d.get("currency"), d.get("stock"), d.get("instock"), d.get("img"), int(d["used_text"]), ts, pid))
        nd += 1
        r = db.execute("SELECT price, stock, instock FROM prostock WHERE id=?", (pid,)).fetchone()
        last = db.execute("SELECT price, stock, instock FROM prostock_prices WHERE id=? ORDER BY ts DESC LIMIT 1", (pid,)).fetchone()
        if last != r: db.execute("INSERT INTO prostock_prices VALUES(?,?,?,?,?)", (pid, ts, *r))
        if nd % 25 == 0: db.commit(); print(f"  {nd}/{len(todo)} product pages")
    # listing price changes on sticks not re-fetched this run
    for p in keep.values():
        last = db.execute("SELECT price FROM prostock_prices WHERE id=? ORDER BY ts DESC LIMIT 1", (p["id"],)).fetchone()
        if last and last[0] != p["price"]:
            r = db.execute("SELECT price, stock, instock FROM prostock WHERE id=?", (p["id"],)).fetchone()
            db.execute("INSERT INTO prostock_prices VALUES(?,?,?,?,?)", (p["id"], ts, *r))
    return "ok", len(keep), nd

def main(db=None, ts=None):
    own = db is None
    db = db or sqlite3.connect(DB); init(db)
    ts = ts or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"); t0 = time.time()
    try: status, n, nd = run(db, ts)
    except Exception as e: status, n, nd = f"error: {e}"[:300], 0, 0
    db.execute("INSERT INTO runs VALUES(?,?,?,?,?,?)", (ts, "prostockhockey", n, n, nd, status)); db.commit()
    print(f"Pro Stock Hockey (Player Sticks): {n} listed, {nd} product pages fetched, {status}, {time.time()-t0:.0f}s")
    if own: db.close()

if __name__ == "__main__":
    main()
