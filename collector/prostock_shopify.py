#!/usr/bin/env python3
"""Pro stock Shopify sellers (Canada, CAD): Pro Stock North America and North Prostock.
Rows go to the same separate `prostock` table as Pro Stock Hockey (store column), never to retail variants/prices.
One row per available variant (each listing is one hand/flex/curve). Condition is kept and shown as a badge."""
import html, re, sqlite3, sys, time, urllib.request
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from collect import UA, DB, allowed, get, load_models, size_from_flex
import prostock

DELAY = 3.0
BRANDS = r"Bauer|CCM|True|TRUE|Warrior|Sherwood|STX|Easton|Reebok"
LEAGUES = r"NHL|AHL|ECHL|WHL|OHL|QMJHL|CHL|NCAA|USHL|PWHL|KHL|SHL"

NPS_ALIAS = [(r"^FT(\d|\+)", r"Jetspeed FT\1"), (r"^(Hyperlite|Flylite)", r"Vapor \1"), (r"^Trigger", "Ribcor Trigger"),
             (r"^Tacks ASV\b", "Tacks AS-V"), (r"^SuperTacks", "Super Tacks")]  # North Prostock short names -> seed names

def model_ok(m): return bool(m and len(m) >= 2)

def cond_norm(c):
    c = (c or "").strip().lower()
    return {"new": "New", "new unused": "New", "team issue": "Team Issue", "pro return": "Pro Return", "like new": "Like New",
            "game used": "Used", "used": "Used", "restored": "Used", "player edition": "New"}.get(c, c.title() or None)

def psna_conditions():
    """Condition lives only on the collection cards (a metafield chip), keyed by product handle."""
    out = {}
    for n in range(1, 15):
        page = urllib.request.urlopen(urllib.request.Request(f"https://prostocknorthamerica.com/collections/prostock-sticks?page={n}",
                                      headers={"User-Agent": UA}), timeout=30).read().decode("utf-8", "replace"); time.sleep(DELAY)
        cards = re.findall(r'href="/products/([^"?]+)"[^>]*>.*?psna-spec-chip--condition[^"]*">([^<]+)<', page, re.S)
        new = {h: c for h, c in cards if h not in out}
        if not new: break
        out.update(new)
    return out

def psna(store, models):
    conds = psna_conditions()
    for page in range(1, 10):
        prods = get(f"{store['base']}/collections/prostock-sticks/products.json?limit=250&page={page}")["products"]; time.sleep(DELAY)
        for p in prods:
            body = html.unescape(re.sub(r"<[^>]+>", "\n", p.get("body_html") or ""))
            spec = {k.strip().split(" (")[0]: v.strip() for k, v in re.findall(r"^\s*([A-Za-z ()]+?):\s*(.+?)\s*$", body, re.M)}
            model = spec.get("Model") or p["title"].title()
            brand = p.get("vendor") or model.split()[0]
            model = re.sub(rf"^({BRANDS})\s+", "", model, flags=re.I)
            for v in p["variants"]:
                if not v.get("available"): continue
                hand = "Left" if "left" in (v.get("option1") or "").lower() else "Right" if "right" in (v.get("option1") or "").lower() else None
                yield dict(id=f"psna:{v['id']}", url=f"{store['base']}/products/{p['handle']}?variant={v['id']}", title=p["title"], brand=brand,
                           model=model, hand=hand, flex=v.get("option2"), curve=v.get("option3"), length=spec.get("Height"),
                           grip=spec.get("Grip"), price=float(v["price"]), condition=cond_norm(conds.get(p["handle"]) or "New"), player=None, team=None)
        if len(prods) < 250: break

NPS_HEAD = re.compile(r"^(Left|Right) Hand (\d{2,3})\s*Flex\s+((?:Custom\s+)?\S+)\s+(.*)$", re.I)
NPS_COND = re.compile(r"\(?\b(Like New|New|Used|Restored)\b\)?", re.I)

def nps_parse(t):
    m = NPS_HEAD.match(t)
    if not m: return None
    hand, flex, curve, rest = m.groups()
    conds = list(NPS_COND.finditer(rest)); b = re.search(rf"\b({BRANDS})\b", rest, re.I)
    if not conds or not b: return None
    c = conds[-1]
    dressed = re.search(r"\(?\s*(?:wrapped|dressed) as ([^()]+?)\s*\)?(?=\s*(?:\(|$|\b(?:New|Used|Like New|Restored)\b))", rest, re.I)
    model = rest[b.end():c.start() if c.start() > b.end() else len(rest)]
    model = re.sub(r"\(?\s*(?:wrapped|dressed) as [^()]*\)?", "", model, flags=re.I)
    model = re.sub(rf"\b(Pro Stock|{LEAGUES})\b", "", model).strip(" -()")
    who = rest[c.end():] if c.start() > b.end() else ""
    who = re.sub(r"\(?\s*(?:wrapped|dressed) as [^()]*\)?|\bPro Stock\b", "", who, flags=re.I)
    return hand, flex, curve, b.group(1), model, c.group(1), who.strip(), dressed

def nps(store, models):
    for page in range(1, 20):
        prods = get(f"{store['base']}/products.json?limit=250&page={page}")["products"]; time.sleep(DELAY)
        for p in prods:
            t = re.sub(r"\s+", " ", p["title"]).strip()
            if re.search(r"blckstck|goalie|\bfits\b|blade|skate|glove|pant|helmet|jersey", t, re.I): continue
            parsed = nps_parse(t)
            if not parsed or not model_ok(parsed[4]): continue
            hand, flex, curve, brand, model, cond, who, dressed = parsed
            for rx, sub in NPS_ALIAS: model = re.sub(rx, sub, model, flags=re.I)
            league = re.search(rf"\b({LEAGUES})\b", who)
            player = re.sub(rf"\b({LEAGUES})\b", "", who).strip(" -") or None
            for v in p["variants"]:
                if not v.get("available"): continue
                yield dict(id=f"nps:{v['id']}", url=f"{store['base']}/products/{p['handle']}?variant={v['id']}", title=t, brand=brand.title() if brand.lower() == "true" else brand,
                           model=model.strip(), dressed_as=dressed.group(1).strip() if dressed else None, hand=hand.title(), flex=flex, curve=curve.strip(),
                           length=None, grip=None, price=float(v["price"]), condition=cond_norm(cond), player=player and player.title(),
                           team=(league.group(1).upper() if league else None))
        if len(prods) < 250: break

STORES = [dict(id="psna", name="Pro Stock North America", base="https://prostocknorthamerica.com", rows=psna, probe="/collections/prostock-sticks/products.json"),
          dict(id="northprostock", name="North Prostock", base="https://northprostock.com", rows=nps, probe="/products.json")]

def run_store(db, s, ts, models):
    t0 = time.time()
    if not allowed(s["base"], s["probe"]):
        db.execute("INSERT INTO runs VALUES(?,?,?,?,?,?)", (ts, s["id"], 0, 0, 0, "blocked by robots.txt")); return
    rows = list(s["rows"](s, models))
    db.execute("UPDATE prostock SET listed=0 WHERE store=?", (s["id"],))
    for r in rows:
        slug_ = prostock.model_slug(r["brand"], r["model"], models)
        db.execute("""INSERT INTO prostock(id,store,url,title,brand,player,team,model,dressed_as,model_slug,hand,flex,curve,retail_curve,length,age_group,grip,
             price,currency,stock,instock,condition,listed,first_seen,last_seen,detail_ts) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'CAD',NULL,1,?,1,?,?,?)
           ON CONFLICT(id) DO UPDATE SET url=excluded.url,title=excluded.title,price=excluded.price,instock=1,condition=excluded.condition,listed=1,
             last_seen=excluded.last_seen,detail_ts=excluded.detail_ts,model=excluded.model,model_slug=excluded.model_slug,player=excluded.player,team=excluded.team""",
           (r["id"], s["id"], r["url"], r["title"], r["brand"], r.get("player"), r.get("team"), r["model"], r.get("dressed_as"), slug_, r["hand"], r["flex"],
            r["curve"], r["curve"], r.get("length"), size_from_flex(r["flex"]), r.get("grip"), r["price"], r["condition"], ts, ts, ts))
        last = db.execute("SELECT price FROM prostock_prices WHERE id=? ORDER BY ts DESC LIMIT 1", (r["id"],)).fetchone()
        if not last or last[0] != r["price"]: db.execute("INSERT INTO prostock_prices VALUES(?,?,?,?,?)", (r["id"], ts, r["price"], None, 1))
    db.execute("INSERT INTO runs VALUES(?,?,?,?,?,?)", (ts, s["id"], len(rows), len(rows), len(rows), "ok"))
    print(f"{s['name']} (pro stock): {len(rows)} sticks, {time.time()-t0:.0f}s")

def main(db=None, ts=None):
    own = db is None; db = db or sqlite3.connect(DB); prostock.init(db)
    ts = ts or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"); models = load_models()
    for s in STORES:
        try: run_store(db, s, ts, models); db.commit()
        except Exception as e:
            db.rollback(); db.execute("INSERT INTO runs VALUES(?,?,?,?,?,?)", (ts, s["id"], 0, 0, 0, f"error: {e}"[:300])); db.commit()
            print(f"{s['name']}: FAILED {e}")
    if own: db.close()

if __name__ == "__main__":
    main()
