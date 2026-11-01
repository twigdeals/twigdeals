#!/usr/bin/env python3
"""Twig Deals static site generator: data/prices.db -> dist/"""
import html, json, re, shutil, sqlite3, urllib.parse
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import urllib.request
import images, sys
sys.path.insert(0, str(Path(__file__).resolve().parent / "collector"))
from collect import size_from_flex
ET = ZoneInfo("America/New_York")
STOCK_UNKNOWN = {"sourceforsports", "sportsexcellence"}  # stock flags not trustworthy (SFS: all variants available; SE: Shopify Markets, US visitors often see sold out)

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "dist"
AFF = json.load(open(ROOT / "data/affiliates.json"))
# id, display name, home page, currency the store lists in. Order = order on the About page and footer.
STORES = [
    ("bauer", "Bauer.com", "https://www.bauer.com", "USD"),
    ("prohockeylife", "Pro Hockey Life", "https://www.prohockeylife.com", "CAD"),
    ("sourceforsports", "Source for Sports", "https://www.sourceforsports.ca", "CAD"),
    ("hockeystickman", "HockeyStickMan", "https://www.hockeystickman.com", "USD"),
    ("justhockey", "Just Hockey", "https://www.justhockeytoronto.com", "CAD"),
    ("discounthockey", "Discount Hockey", "https://discounthockey.com", "USD"),
    ("thehockeyshop", "TheHockeyShop.com", "https://www.thehockeyshop.com", "CAD"),
    ("hockeytron", "HockeyTron", "https://hockeytron.com", "USD"),
    ("sportsexcellence", "Sports Excellence", "https://sportsexcellence.com", "CAD"),
    ("icewarehouse", "Ice Warehouse", "https://www.icewarehouse.com", "USD"),
    ("hockeymonkey", "Hockey Monkey", "https://www.hockeymonkey.com", "USD"),
]
STORE_NAMES = {i: n for i, n, _, _ in STORES}
# Beehiiv subscribe page. Change only here if the subdomain is renamed.
BEEHIIV_BASE_URL = "https://twigdeals.beehiiv.com"
BEEHIIV_SUBSCRIBE_URL = BEEHIIV_BASE_URL + "/subscribe"
SITE = "Twig Deals"; TAGLINE = "Twig Deals: hockey stick price tracker"
e = html.escape

def fx_rate():
    """USD->CAD from Bank of Canada Valet API (public, no key); cached in data/fx.json."""
    cache = ROOT / "data/fx.json"
    try:
        with urllib.request.urlopen("https://www.bankofcanada.ca/valet/observations/FXUSDCAD/json?recent=1", timeout=15) as r:
            o = json.loads(r.read())["observations"][-1]
        d = {"usdcad": float(o["FXUSDCAD"]["v"]), "date": o["d"]}; cache.write_text(json.dumps(d))
    except Exception:
        d = json.loads(cache.read_text()) if cache.exists() else {"usdcad": None, "date": None}
    return d
FX = fx_rate()
def usd(p, c): return p if c == "USD" else (p / FX["usdcad"] if FX["usdcad"] else None)

def slug(s): return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")
def cslug(c): return slug((c or "").replace("+", " plus "))  # "P28+" must not share a URL with "P28"
def money(p, c): return f"${p:,.2f} {c}"
def aff(store, url):
    t = AFF.get(store) or ""
    return t.replace("{url_enc}", urllib.parse.quote(url, safe="")).replace("{url}", url) if t else url
def norm_curve(c):
    if not c: return None
    c = re.sub(r"\s*\(.*\)", "", c).strip().upper().replace("1/4", "").replace("+", "+")
    return c

CSS = open(ROOT / "static/site.css").read()
import hashlib
CSS_V = hashlib.md5((open(ROOT/"static/fonts/fonts.css").read()+CSS).encode()).hexdigest()[:10]

REG = {"CAD": "ca", "USD": "us"}  # store region from listing currency
REG_EMPTY = {"ca": "No Canadian stores carry this right now.", "us": "No US stores carry this right now."}
def rsw(all_html, ca_html, us_html):
    """Region-switchable block. 'All' is the real, crawlable content; Canada/US versions sit in inert <template>s
    that region.js swaps in client-side."""
    return (f'<div class="rsw"><div data-v="all">{all_html}</div><template data-v="ca">{ca_html}</template>'
            f'<template data-v="us">{us_html}</template></div>')
RTOGGLE = """<div class="rgn" role="radiogroup" aria-label="Show stores in"><button type="button" role="radio" data-set="all" aria-checked="true">All</button><button type="button" role="radio" data-set="ca" aria-checked="false">Canada</button><button type="button" role="radio" data-set="us" aria-checked="false">US</button></div>"""
RHEAD = """<script>try{var r=localStorage.getItem("twig-region");if(r==="ca"||r==="us")document.documentElement.setAttribute("data-region",r)}catch(e){}</script><script defer src="/region.js?v=1"></script>"""
REGION_JS = r"""(function(){
var K="twig-region",H=document.documentElement;
function cur(){return H.getAttribute("data-region")||"all"}
function apply(r){
 if(r==="all")H.removeAttribute("data-region");else H.setAttribute("data-region",r);
 try{r==="all"?localStorage.removeItem(K):localStorage.setItem(K,r)}catch(e){}
 document.querySelectorAll(".rgn button").forEach(function(b){b.setAttribute("aria-checked",b.getAttribute("data-set")===r?"true":"false")});
 document.querySelectorAll(".rsw").forEach(function(w){
  var a=w.querySelector(':scope>[data-v="all"]'),live=w.querySelector(":scope>.rlive");
  if(live)live.remove();
  if(r==="all"){a.hidden=false;return}
  var t=w.querySelector(':scope>template[data-v="'+r+'"]');if(!t)return;
  var d=document.createElement("div");d.className="rlive";d.appendChild(t.content.cloneNode(true));a.hidden=true;w.appendChild(d);
 });
}
document.addEventListener("click",function(e){var b=e.target.closest&&e.target.closest(".rgn button");if(b)apply(b.getAttribute("data-set"))});
apply(cur());
})();
"""
LOGO = """<span class="logo-lock"><img class="wm" src="/wordmark.svg" alt="Twig Deals" width="74" height="46"></span>"""

def ld(obj):
    """schema.org JSON-LD <script>; '</' escaped so data can never close the tag."""
    return '<script type="application/ld+json">' + json.dumps(obj, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/") + "</script>"

def page(title, body, desc="", head=""):
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title><meta name="description" content="{e(desc or TAGLINE)}"><meta name="theme-color" content="#0E0F11"><link rel="icon" href="/favicon.ico" sizes="any"><link rel="icon" type="image/png" sizes="32x32" href="/favicon-32.png"><link rel="apple-touch-icon" href="/apple-touch-icon.png"><meta property="og:type" content="website"><meta property="og:site_name" content="Twig Deals"><meta property="og:title" content="{e(title)}"><meta property="og:description" content="{e(desc or TAGLINE)}"><meta property="og:image" content="https://twigdeals.com/og.png"><meta property="og:image:width" content="1200"><meta property="og:image:height" content="630"><meta name="twitter:card" content="summary_large_image"><meta name="twitter:image" content="https://twigdeals.com/og.png">
<link rel="preload" href="/fonts/BarlowCondensed-800.woff2" as="font" type="font/woff2" crossorigin>{RHEAD}<link rel="stylesheet" href="/style.css?v={CSS_V}"><script defer src="https://static.cloudflareinsights.com/beacon.min.js" data-cf-beacon='{{"token": "84d077f07747412a876284c5975f5122"}}'></script>{head}</head><body>
<header class="top"><div class="w bar"><a class="logo" href="/">{LOGO}</a>{RTOGGLE}<nav><a href="/sticks/">Sticks</a><a href="/curves/">Curve + flex</a><a href="/pro-stock/">Pro stock</a><a href="/guides/when-do-hockey-sticks-go-on-sale/">Sale calendar</a><a href="/about/">About</a><a class="nav-cta" href="#newsletter">Weekly drops</a></nav></div></header>
<main><p class="w rnote">Canadian stores list prices in CAD and ship to the US; on their sites US visitors may see different prices or stock.</p>{body}{NEWSLETTER}</main><footer><div class="w foot"><div>{LOGO}<p>Hockey stick price tracker. Prices are pulled from retailer sites twice a day and can change; confirm on the store page before you buy. Some links earn us a commission at no cost to you. CAD and USD are shown as listed, not converted.</p><p>Stores tracked: {e(", ".join(n for _, n, _, _ in STORES))}. Pro stock page (listed separately): Pro Stock Hockey, Pro Stock North America, North Prostock, plus pro stock from HockeyStickMan, Ice Warehouse, TheHockeyShop.com, Just Hockey and Hockey Monkey.</p></div><div class="flinks"><a href="/sticks/">All sticks</a><a href="/curves/">Curve + flex</a><a href="/pro-stock/">Pro stock</a><a href="/guides/when-do-hockey-sticks-go-on-sale/">When sticks go on sale</a><a href="/about/">About + stores</a></div></div></footer></body></html>"""

NEWSLETTER = f"""<section class="nl" id="newsletter"><div class="w nl-in"><div><p class="kicker">Every Thursday</p><h2>The drop sheet.</h2><p>One email. The biggest real price cuts on senior and intermediate twigs, sorted by curve and flex. No fluff.</p></div>
<!-- NEWSLETTER: Beehiiv free plan, no API. The subscribe page doesn't prefill ?email= (checked Oct 19, 2026), so this is a plain link. -->
<div class="nl-cta"><a class="nl-btn" href="{BEEHIIV_SUBSCRIBE_URL}" rel="noopener">Get the drop sheet <span aria-hidden="true">→</span></a><p class="nl-fine">Free. Sign up on our Beehiiv page. Unsubscribe anytime.</p></div></div></section>"""

def spark(vals, w=96, h=24):
    if len(vals) < 2: return '<span class="spark-na">1st check</span>'
    lo, hi = min(vals), max(vals); hi = hi if hi > lo else lo + 1
    pts = " ".join(f"{w*i/(len(vals)-1):.1f},{h-2-(h-4)*(v-lo)/(hi-lo):.1f}" for i, v in enumerate(vals))
    return f'<svg class="spark" viewBox="0 0 {w} {h}" width="{w}" height="{h}"><polyline points="{pts}" fill="none" stroke="currentColor" stroke-width="1.6"/></svg>'

def write(path, content):
    canon = "https://twigdeals.com" + ("/" if path in ("", "/") else "/" + path.strip("/") + "/")
    content = content.replace("</title>", f'</title><link rel="canonical" href="{canon}">', 1)
    p = OUT / path.strip("/") / "index.html" if not path.endswith(".css") else OUT / path
    p.parent.mkdir(parents=True, exist_ok=True); p.write_text(content)

def chart(series):
    """series: {currency: [(date, minprice), ...]} -> inline SVG"""
    pts = [p for s in series.values() for p in s]
    if not pts: return ""
    W, H, P = 640, 220, 40
    dates = sorted({d for d, _ in pts})
    if len(dates) < 2:
        return f'<div class="chart-empty"><b>History starts {dates[0]} (UTC).</b> We log every price twice a day; the line draws itself from here.</div>'
    lo = min(p for _, p in pts); hi = max(p for _, p in pts)
    if hi == lo: hi, lo = hi + 10, max(0, lo - 10)
    x = lambda d: P + (W - 2 * P) * (dates.index(d) / max(1, len(dates) - 1)) if len(dates) > 1 else W / 2
    y = lambda v: H - P - (H - 2 * P) * (v - lo) / (hi - lo)
    colors = {"USD": "#0E0F11", "CAD": "#E2231A"}; out = []
    for cur, s in series.items():
        s = sorted(s); c = colors.get(cur, "#333")
        out.append(f'<polyline fill="none" stroke="{c}" stroke-width="2.5" points="{" ".join(f"{x(d):.1f},{y(v):.1f}" for d, v in s)}"/>')
        out += [f'<circle cx="{x(d):.1f}" cy="{y(v):.1f}" r="3.5" fill="{c}"><title>{d}: ${v:.2f} {cur}</title></circle>' for d, v in s]
    legend = " ".join(f'<tspan fill="{colors.get(c,"#333")}">■ {c} lowest</tspan>' for c in series)
    return f'''<svg class="chart" viewBox="0 0 {W} {H}" role="img" aria-label="Price history"><text x="{P}" y="20" font-size="12">{legend}</text>
<text x="4" y="{y(hi)+4:.0f}" font-size="11" fill="#64748b">${hi:.0f}</text><text x="4" y="{y(lo)+4:.0f}" font-size="11" fill="#64748b">${lo:.0f}</text>
<line x1="{P}" y1="{H-P}" x2="{W-P}" y2="{H-P}" stroke="#cbd5e1"/><text x="{P}" y="{H-12}" font-size="11" fill="#64748b">{dates[0]}</text>
<text x="{W-P}" y="{H-12}" font-size="11" fill="#64748b" text-anchor="end">{dates[-1]}</text>{"".join(out)}</svg>
<p class="meta">{len(dates)} day(s) of history so far. The chart fills in as the collector runs twice daily.</p>'''

# ---------- Pro stock. Separate from retail: never in deals, history, lowest-ever, curve pages or the retail store count.
# Sources: dedicated sellers (prostock table) + pro stock rows the retail collectors already find (variants.pro_stock=1).
PS_SELLERS = {"prostockhockey": ("Pro Stock Hockey", "USD", "https://www.prostockhockey.com/player-sticks/"),
              "psna": ("Pro Stock North America", "CAD", "https://prostocknorthamerica.com/collections/prostock-sticks"),
              "northprostock": ("North Prostock", "CAD", "https://northprostock.com")}
PS_FROM_RETAIL = ("hockeystickman", "icewarehouse", "thehockeyshop", "justhockey", "hockeymonkey")
PS_SKIP = re.compile(r"refurb|blackout|\bused\b", re.I)   # HSM refurbished / house-brand sticks are not pro stock
COND_ORDER = ["New", "Team Issue", "Pro Return", "Like New", "Used"]

def ps_player(store, title):
    pats = {"hockeystickman": r"^(.+?) Pro Stock\s*-", "icewarehouse": r"Pro Stock (.+?)(?: Hockey)? Stick$",
            "thehockeyshop": r"Pro Stock .*? - (.+)$"}  # Just Hockey titles put the name in varying places; left blank
    m = re.search(pats.get(store, r"$^"), title or "")
    return m.group(1).strip().title() if m else None

def load_prostock(db, live):
    rows = []
    try:
        for r in db.execute("SELECT * FROM prostock WHERE listed=1 AND detail_ts IS NOT NULL AND coalesce(instock,1)=1"):
            r = dict(r); st = r.get("store") or "prostockhockey"
            r.update(store=st, store_name=PS_SELLERS[st][0], currency=r["currency"] or PS_SELLERS[st][1],
                     condition=r.get("condition") or ("Used" if r["wear_note"] else "New"), link=r["url"], sponsored=False)
            rows.append(r)
    except sqlite3.OperationalError: pass
    for v in live:
        if not v["pro_stock"] or v["store"] not in PS_FROM_RETAIL or v["available"] == 0: continue
        if PS_SKIP.search(v["product_title"] or ""): continue
        rows.append(dict(store=v["store"], store_name=STORE_NAMES[v["store"]], currency=v["currency"], title=v["product_title"],
            brand=v["brand"], model=v["model"], model_slug=v["model_slug"], dressed_as=None, player=ps_player(v["store"], v["product_title"]),
            team=None, hand=v["hand"], flex=v["flex"], curve=v["curve"], retail_curve=None, lie=None, length=None, age_group=v["size"],
            price=v["price"], stock=None, condition="Pro Return" if re.search(r"pro return", v["product_title"] or "", re.I) else "New",
            wear_note=0, link=aff(v["store"], v["url"]), sponsored=bool(AFF.get(v["store"]))))
    for r in rows:
        if r["hand"]: r["hand"] = {"L": "Left", "R": "Right"}.get(r["hand"][:1].upper(), r["hand"])
        r["flex"] = (re.match(r"\d{2,3}", str(r["flex"] or "")) or [None])[0]
        r["size"] = r.get("age_group") or size_from_flex(r["flex"])
        base = r.get("retail_curve") or r.get("curve") or ""
        r["rcurve"] = (re.sub(r"(?i)^custom\s*|\s*\(.*", "", base.split("/")[0]).strip().upper() or None)
        r["r"] = REG[r["currency"]]; r["usd"] = usd(r["price"], r["currency"]) or r["price"]
    rows.sort(key=lambda r: r["usd"])
    return rows

def ps_link(s, by_model):
    vl = by_model.get(s, [])
    if not vl: return ""
    n = {rg: sum(1 for x in vl if x["r"] == rg) for rg in ("ca", "us")}
    return (f'<p class="pslink"><a href="/pro-stock/?model={s}">Pro stock options (<span class="ro-all">{len(vl)}</span><span class="ro-ca">{n["ca"]}</span><span class="ro-us">{n["us"]}</span>) →</a> '
            '<span>Player-spec team sticks from pro stock sellers, matched on the real model. Listed separately from the prices below.</span></p>')

PS_JS = r"""(function(){
var f=document.getElementById("psf");if(!f)return;var H=document.documentElement,L=[].slice.call(document.querySelectorAll("#psl>li.pscard")),C=document.getElementById("psn");
var K=["hand","size","curve","model","flex","cond","store"],q=new URLSearchParams(location.search);K.forEach(function(k){if(q.get(k)&&f[k])f[k].value=q.get(k)});
function go(){var v={};K.forEach(function(k){v[k]=f[k].value});var rg=H.getAttribute("data-region")||"all",n=0;
 L.forEach(function(li){var d=li.dataset,fl=+d.flex||0,ok=(rg==="all"||d.r===rg)&&(!v.hand||d.hand===v.hand)&&(!v.size||d.size===v.size)&&(!v.curve||d.curve===v.curve)&&(!v.model||d.model===v.model)&&(!v.cond||d.cond===v.cond)&&(!v.store||d.store===v.store)&&
  (!v.flex||(v.flex==="lt75"?fl&&fl<75:v.flex==="75-85"?fl>=75&&fl<=85:v.flex==="87-95"?fl>=87&&fl<=95:fl>=100));li.hidden=!ok;if(ok)n++});
 C.textContent=n;}
f.addEventListener("change",go);f.addEventListener("reset",function(){setTimeout(go,0)});
document.addEventListener("click",function(e){if(e.target.closest&&e.target.closest(".rgn button"))setTimeout(go,0)});go();})();"""

def ps_li(x, names):
    who = " · ".join(filter(None, [x.get("player"), x.get("team")]))
    spec = " · ".join(filter(None, [x["hand"] and x["hand"][0] + "H", x["flex"] and x["flex"] + " flex",
               x.get("curve") and ("curve " + x["curve"]), x.get("retail_curve") and ("≈ " + x["retail_curve"]),
               x.get("lie") and ("lie " + x["lie"]), x.get("length"), x["size"]]))
    mdl = f'<a href="/sticks/{x["model_slug"]}/">{e(x["model"])}</a>' if x["model_slug"] in names else f'<b>{e(x["model"] or x["title"])}</b>'
    dr = f'<span class="dr">dressed as {e(x["dressed_as"])}</span>' if x.get("dressed_as") else ""
    stock = f'<span class="ok">{x["stock"]} in stock</span>' if x.get("stock") else '<span class="ok">In stock</span>'
    cc = slug(x["condition"])
    wear = '<span class="wear">Listing notes possible tape/cosmetic wear</span>' if x.get("wear_note") else ""
    rel = "sponsored nofollow" if x["sponsored"] else "nofollow"
    return (f'<li class="pscard" data-r="{x["r"]}" data-store="{x["store"]}" data-cond="{e(x["condition"])}" data-hand="{e(x["hand"] or "")}" data-flex="{e(x["flex"] or "")}" '
            f'data-curve="{e(x["rcurve"] or "")}" data-size="{e(x["size"] or "")}" data-model="{e(x["model_slug"] or "")}">'
            f'<span class="psbadges"><span class="psbadge">Pro stock</span><span class="cond cond-{cc}">{e(x["condition"])}</span></span>'
            f'<div class="d-name"><span class="brand">{e(x["brand"] or "")} · {e(x["store_name"])}</span>{mdl}{dr}<span class="who">{e(who)}</span><span class="spec">{e(spec)}</span>{wear}</div>'
            f'<div class="d-price"><b>{x["price"]:,.2f}</b><small>{x["currency"]}</small>{stock}</div>'
            f'<a class="go" rel="{rel}" href="{e(x["link"])}" aria-label="View at {e(x["store_name"])}">View →</a></li>')

def prostock_page(PS, models):
    names = {s: f"{b} {m}" for s, b, m in models}
    opts = lambda vals: "".join(f'<option value="{e(v)}">{e(l)}</option>' for v, l in vals)
    cnt = lambda key: defaultdict(int, {k: sum(1 for x in PS if x[key] == k) for k in {x[key] for x in PS}})
    curves = sorted(k for k, n in cnt("rcurve").items() if k and n >= 3)
    msl = sorted({x["model_slug"] for x in PS if x["model_slug"] in names}, key=lambda k: names[k])
    sizes = [z for z in ("Senior", "Intermediate", "Junior", "Youth") if any(x["size"] == z for x in PS)]
    stores = sorted({(x["store"], x["store_name"], x["currency"]) for x in PS}, key=lambda t: t[1])
    conds = [c for c in COND_ORDER if any(x["condition"] == c for x in PS)]
    empty = '<li class="empty">No pro stock sticks right now.</li>'
    by_store = ", ".join(f"{n} ({sum(1 for x in PS if x['store']==s)}, {c})" for s, n, c in stores)
    body = (f'<div class="w page"><p class="kicker">Pro stock · separate from retail</p><h1>Pro stock player sticks</h1>'
            '<p class="lede">Sticks built to NHL, AHL, junior and NCAA players\' custom specs, sold by pro stock sellers in the US and Canada. '
            'Curves are often custom, so we show the closest retail curve where the store gives one. Condition is shown as each store grades it, from New to Used. '
            'Prices are in the store\'s currency and never count toward retail deals or lowest-ever prices.</p>'
            f'<p class="meta">Sellers: {e(by_store)}.</p>'
            f'<form id="psf" class="psf"><label>Hand<select name="hand"><option value="">Any</option>{opts([("Left","Left"),("Right","Right")])}</select></label>'
            f'<label>Flex<select name="flex"><option value="">Any</option>{opts([("lt75","Under 75"),("75-85","75–85"),("87-95","87–95"),("100+","100+")])}</select></label>'
            f'<label>Curve<select name="curve"><option value="">Any</option>{opts((c, c) for c in curves)}</select></label>'
            f'<label>Size<select name="size"><option value="">Any</option>{opts((z, z) for z in sizes)}</select></label>'
            f'<label>Condition<select name="cond"><option value="">All</option>{opts((c, c) for c in conds)}</select></label>'
            f'<label>Store<select name="store"><option value="">All</option>{opts((s, f"{n} ({c})") for s, n, c in stores)}</select></label>'
            f'<label>Model<select name="model"><option value="">Any</option>{opts((k, names[k]) for k in msl)}</select></label>'
            f'<button type="reset">Clear</button><p class="meta"><b id="psn">{len(PS)}</b> sticks in stock, cheapest first (CAD compared at the Bank of Canada rate).</p></form>'
            f'<ol class="deals pslist" id="psl">{"".join(ps_li(x, names) for x in PS) or empty}</ol></div><script src="/prostock.js?v=2" defer></script>')
    (OUT / "prostock.js").write_text(PS_JS)
    write("/pro-stock/", page(f"Pro stock hockey sticks by hand, flex, curve and condition | {SITE}", body,
          "Pro stock NHL and team-issue player sticks from US and Canadian pro stock sellers, with curve, flex, hand, condition and stock, kept separate from retail prices."))

def main():
    if OUT.exists(): shutil.rmtree(OUT)
    OUT.mkdir()
    (OUT / "style.css").write_text(open(ROOT/"static/fonts/fonts.css").read() + CSS); shutil.copytree(ROOT/"static/fonts", OUT/"fonts", dirs_exist_ok=True); shutil.copy(ROOT/"static/og.png", OUT/"og.png"); [shutil.copy(ROOT/"static"/f, OUT/f) for f in ("favicon.ico","favicon-32.png","apple-touch-icon.png","icon-512.png","wordmark.svg","wordmark-email.png")]
    db = sqlite3.connect(ROOT / "data/prices.db"); db.row_factory = sqlite3.Row
    last_ts = db.execute("SELECT max(last_seen) FROM variants").fetchone()[0]
    vs = {r["id"]: dict(r) for r in db.execute("SELECT * FROM variants")}
    # A store whose latest run failed (503, robots.txt unreachable) keeps the variants from its last complete run
    # for up to 2 days instead of vanishing from the site.
    stale = (datetime.strptime(last_ts, "%Y-%m-%dT%H:%M:%SZ") - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    last_ok = {r[0]: r[1] for r in db.execute("SELECT store, max(ts) FROM runs WHERE status='ok' GROUP BY store")}
    hist = defaultdict(list)
    for r in db.execute("SELECT * FROM prices ORDER BY ts"): hist[r["variant_id"]].append(dict(r))
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    for vid, v in vs.items():
        h = hist[vid]; cur = h[-1]
        v["size"] = v["size"] or size_from_flex(v["flex"])  # same flex fallback as the collector
        v.update(price=cur["price"], compare_at=cur["compare_at"], available=(None if v["store"] in STOCK_UNKNOWN else cur["available"]), current=v["last_seen"] == last_ts or (last_ok.get(v["store"], "") >= stale and v["last_seen"] >= last_ok[v["store"]]),
                 lowest=min(x["price"] for x in h), curve_n=norm_curve(v["curve"]))
        wk = [x["price"] for x in h if x["ts"] >= week_ago and x["ts"] != cur["ts"]]
        v["week_high"] = max(wk) if wk else None
        ref = max(filter(None, [v["week_high"], v["compare_at"]]), default=None)
        v["drop"] = (ref - v["price"]) if ref and ref > v["price"] else 0
        v["drop_pct"] = round(100 * v["drop"] / ref) if v["drop"] else 0
        v["drop_basis"] = "vs. 7-day high" if v["week_high"] and v["week_high"] > v["price"] else "vs. store's list price"
    live_all = [v for v in vs.values() if v["current"]]
    live = [v for v in live_all if not v["pro_stock"]]  # pro stock lives on /pro-stock/ only
    models = defaultdict(list)
    for v in live_all: models[(v["model_slug"], v["brand"], v["model"])].append(v)
    PS = load_prostock(db, live_all)
    MODEL_NAMES = {k[0]: f"{k[1]} {k[2]}" for k in models}
    ps_by_model = defaultdict(list)
    for x in PS:
        if x["model_slug"]: ps_by_model[x["model_slug"]].append(x)
    PHOTOS = images.pick(db, sorted({k[0] for k in models}))
    if (ROOT / "static/img").exists(): shutil.copytree(ROOT / "static/img", OUT / "img", dirs_exist_ok=True)

    def card(v, extra=""):
        spec = " · ".join(filter(None,[v["size"] and v["size"][:3].upper()+".",v["curve"],(v["flex"] and v["flex"]+" flex"),v["hand"] and v["hand"][0]+"H"]))
        was = f'<s>{v["compare_at"]:,.2f}</s>' if v["compare_at"] and v["compare_at"]>v["price"] else ""
        badge = f'<span class="drop">−{v["drop_pct"]}%</span>' if v["drop_pct"] else '<span class="drop zero">—</span>'
        return f"""<li class="deal" data-r="{REG[v['currency']]}">{badge}<div class="d-name"><span class="brand">{e(v["brand"])}</span><a href="/sticks/{v["model_slug"]}/">{e(v["model"])}</a><span class="spec">{e(spec)}</span></div>
<div class="d-store">{e(STORE_NAMES[v["store"]])}</div><div class="d-spark">{spark([x["price"] for x in hist[v["id"]]])}</div>
<div class="d-price"><b>{v["price"]:,.2f}</b><small>{v["currency"]}</small>{was}</div><a class="go" rel="sponsored nofollow" href="{e(aff(v["store"],v["url"]))}" aria-label="View at {e(STORE_NAMES[v["store"]])}">View →</a></li>"""

    # Curve + flex landing pages
    combos = defaultdict(list)
    for v in live_all:
        if v["curve_n"] and v["flex"] and v["size"] and re.fullmatch(r"\d{2,3}", v["flex"].strip()):
            combos[(v["curve_n"], v["flex"].strip(), v["size"])].append(v)
    combos = {k: vl for k, vl in combos.items() if len(vl) >= 4}
    POPULAR = sorted(((f"/curves/{cslug(c)}-{f}-flex-{slug(sz)}/", f"{c} · {f} · {sz[:3].upper()}") for (c,f,sz),vl in combos.items() if sz=="Senior"), key=lambda t: -len(combos[next(k for k in combos if f"/curves/{cslug(k[0])}-{k[1]}-flex-{slug(k[2])}/"==t[0])]))
    # Homepage: best in-stock drop per model, new (non-pro-stock) sticks only
    # Same size rule as stick pages: senior variants when the model has any, else all sizes.
    cands = defaultdict(list)
    for v in live:
        # Deals only from rows confirmed in stock by the latest run; rows carried over from an earlier run are excluded.
        if v["available"] and v["last_seen"] == last_ts and v["drop_pct"] >= 10 and not v["pro_stock"]: cands[v["model_slug"]].append(v)
    def top_for(rg=None):
        b = {}
        for k, vl in cands.items():
            vl = [v for v in vl if rg is None or REG[v["currency"]] == rg]
            if vl: b[k] = max([v for v in vl if v["size"] == "Senior"] or vl, key=lambda v: v["drop_pct"])
        return sorted(b.values(), key=lambda v: -v["drop_pct"])[:24]
    top = top_for()
    def deals_ol(vs, empty): return f'<ol class="deals">{"".join(card(v) for v in vs) or f"<li class=empty>{empty}</li>"}</ol>'
    n_instock = sum(1 for v in live if v["available"])
    n_reg = {rg: sum(1 for v in live if v["available"] and REG[v["currency"]] == rg) for rg in ("ca", "us")}
    upd = datetime.strptime(last_ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).astimezone(ET)
    elite_low = sorted([v for v in live if v["available"] and not v["pro_stock"] and v["size"]=="Senior"], key=lambda v: v["price"])
    body = f"""<section class="hero"><div class="w"><p class="kicker">Updated {upd:%b %-d, %Y} · {upd:%-I:%M %p} ET</p>
<h1>Stop paying<br>full price for<br>a <em>twig.</em></h1>
<p class="lede">We check every stick at {len(STORE_NAMES)} stores twice a day, curve by curve and flex by flex, and show you what actually dropped.</p>
<dl class="figs"><div><dt>Models tracked</dt><dd>{len(models)}</dd></div><div><dt>Variants</dt><dd>{len(live):,}</dd></div><div><dt>In stock now</dt><dd><span class="ro-all">{n_instock:,}</span><span class="ro-ca">{n_reg["ca"]:,}</span><span class="ro-us">{n_reg["us"]:,}</span></dd></div><div><dt>Stores</dt><dd>{len(STORES)}</dd></div></dl></div></section>
<section class="w block"><div class="sec-head"><h2>This week's biggest drops</h2><p>Best in-stock cut per model, new sticks only. % is vs. the 7-day high or the store's own list price.</p></div>
{rsw(deals_ol(top, "No drops of 10%+ right now."), deals_ol(top_for("ca"), "No Canadian stores have a 10%+ drop right now."), deals_ol(top_for("us"), "No US stores have a 10%+ drop right now."))}</section>
<section class="w block split"><div><div class="sec-head"><h2>Shop your spec</h2><p>Pick the curve and flex you already play.</p></div><div class="chips">{"".join(f'<a href="{p}">{e(t)}</a>' for p,t in POPULAR[:18])}</div></div>
<div><div class="sec-head"><h2>Every model</h2></div><ul class="index">{"".join(f'<li><a href="/sticks/{s}/"><span>{e(b)}</span> {e(m)}</a></li>' for s,b,m in sorted(models, key=lambda k:(k[1],k[2])))}</ul></div></section>"""
    home_ld = ld({"@context": "https://schema.org", "@graph": [
        {"@type": "WebSite", "@id": "https://twigdeals.com/#website", "name": SITE, "url": "https://twigdeals.com/", "description": "Hockey stick price tracker: current and lowest-ever prices by curve, flex and hand at " + str(len(STORES)) + " stores.", "publisher": {"@id": "https://twigdeals.com/#org"}, "inLanguage": "en"},
        {"@type": "Organization", "@id": "https://twigdeals.com/#org", "name": SITE, "url": "https://twigdeals.com/", "logo": "https://twigdeals.com/icon-512.png", "sameAs": [BEEHIIV_BASE_URL]}]})
    write("/", page(f"{SITE}: hockey stick price tracker", body, "Track hockey stick prices and the best drops this week across Bauer, CCM, Warrior, True and Sherwood.", home_ld))
    # Machine-readable current top deals (same list as the homepage)
    # Real 404 page (Cloudflare Pages serves dist/404.html with status 404 for unknown paths). noindex, no canonical.
    (OUT / "region.js").write_text(REGION_JS)
    (OUT / "404.html").write_text(page(f"Page not found | {SITE}", '<div class="w page"><p class="kicker">404</p><h1>Page not found</h1><p class="lede">That page doesn&rsquo;t exist or has moved. Try <a href="/">this week&rsquo;s biggest drops</a>, <a href="/sticks/">every stick we track</a> or <a href="/curves/">curve + flex</a>.</p></div>', "Page not found.", '<meta name="robots" content="noindex">'))
    (OUT / "deals.json").write_text(json.dumps({"site": SITE, "url": "https://twigdeals.com/", "updated": last_ts,
        "note": "Best in-stock price cut per model, new sticks only, 10%+ off. Prices in the store's listed currency. reference_price is the 7-day high or the store's list price (see drop_basis). Confirm on the store page before buying.",
        "deals": [{"brand": v["brand"], "model": v["model"], "stick_page": f"https://twigdeals.com/sticks/{v['model_slug']}/", "store": STORE_NAMES[v["store"]],
                   "size": v["size"], "curve": v["curve"], "flex": v["flex"], "hand": v["hand"], "price": v["price"], "currency": v["currency"],
                   "list_price": v["compare_at"] if v["compare_at"] and v["compare_at"] > v["price"] else None,
                   "reference_price": round(v["price"] + v["drop"], 2), "percent_off": v["drop_pct"], "drop_basis": v["drop_basis"],
                   "store_url": v["url"]} for v in top]}, indent=1))

    # Stick index + pages
    def froms(vl, c): return min((v["price"] for v in vl if v["available"] and v["currency"]==c and not v["pro_stock"]), default=None)
    def regs(vl): return " ".join(sorted({REG[v["currency"]] for v in vl}))
    idx_rows = "".join(f'''<tr data-has="{regs(vl)}"><td class="brand-c">{e(b)}</td><td><a href="/sticks/{s}/">{e(m)}</a></td><td class="num">{len(vl)}</td><td class="num"><span class="ro-all">{sum(1 for v in vl if v["available"])}</span><span class="ro-ca">{sum(1 for v in vl if v["available"] and v["currency"]=="CAD")}</span><span class="ro-us">{sum(1 for v in vl if v["available"] and v["currency"]=="USD")}</span></td>
<td class="num">{" / ".join(f'<span data-r="{REG[c]}">{p:,.2f} {c}</span>' for c,p in sorted({c: froms(vl, c) for c in ("USD","CAD")}.items()) if p) or "—"}</td></tr>'''
        for (s, b, m), vl in sorted(models.items(), key=lambda kv: (kv[0][1], kv[0][2])))
    write("/sticks/", page(f"All tracked hockey sticks | {SITE}", f'''<div class="w page"><p class="kicker">The index</p><h1>Every stick we track</h1><p class="lede">{len(models)} current models from Bauer, CCM, Warrior, True and Sherwood.</p>
<div class="tw"><table><thead><tr><th>Brand</th><th>Model</th><th class="num">Variants</th><th class="num">In stock</th><th class="num">From (new)</th></tr></thead><tbody>{idx_rows}</tbody></table></div></div>'''))
    for (s, b, m), vl in models.items():
        series = defaultdict(lambda: defaultdict(lambda: 1e9))
        for v in vl:
            if v["pro_stock"]: continue
            for x in hist[v["id"]]:
                d = x["ts"][:10]; series[v["currency"]][d] = min(series[v["currency"]][d], x["price"])
        series = {c: list(dd.items()) for c, dd in series.items()}
        low = {}
        for v in vl:
            if not v["pro_stock"]:
                c = v["currency"]; low[c] = min(low.get(c, 1e9), v["lowest"])
        SO={"Senior":0,"Intermediate":1,"Junior":2,"Youth":3}
        rows = sorted([v for v in vl if not v["pro_stock"]], key=lambda v: ({1: 0, None: 1, 0: 2}[v["available"]], v["pro_stock"], SO.get(v["size"],4), v["price"]))
        tr = "".join(f'''<tr data-r="{REG[v['currency']]}" class="{'oos' if v['available'] == 0 else ''}"><td>{e(STORE_NAMES[v["store"]])}{' <span class="tag">Pro stock / used</span>' if v["pro_stock"] else ''}</td><td>{e(v["size"] or "")}</td><td class="mono">{e(v["curve"] or "")}</td><td class="num">{e(v["flex"] or "")}</td><td>{e(v["hand"] or "")}</td>
<td class="num"><b>{v["price"]:,.2f}</b> <small>{v["currency"]}</small>{f' <s>{v["compare_at"]:,.2f}</s>' if v["compare_at"] and v["compare_at"]>v["price"] else ""}</td><td class="num">{v["lowest"]:,.2f}</td><td>{'<span class="ok">In stock</span>' if v["available"] else ('<span class="unk">Check store</span>' if v["available"] is None else "Out")}</td>
<td><a class="go" rel="sponsored nofollow" href="{e(aff(v["store"],v["url"]))}">View →</a></td></tr>''' for v in rows)
        for rg in ("ca", "us"):
            if not any(REG[v["currency"]] == rg for v in vl): tr += f'<tr class="rempty" data-only="{rg}"><td colspan="9">{REG_EMPTY[rg]}</td></tr>'
        stores = sorted({STORE_NAMES[v["store"]] for v in vl if not v["pro_stock"]})
        def figs_for(vl):
          new = [v for v in vl if not v["pro_stock"]]
          inst = [v for v in new if v["available"]]
          buyable = [v for v in new if v["available"] is not False and v["available"] != 0]
          sen = [v for v in buyable if v["size"] == "Senior"] or buyable
          szl = "senior" if any(v["size"] == "Senior" for v in buyable) else "any size"
          def best(vs, key):
              vs = [v for v in vs if usd(v[key], v["currency"]) is not None]
              return min(vs, key=lambda v: usd(v[key], v["currency"])) if vs else None
          bn = best(sen, "price"); be = best([v for v in new if v["size"] == "Senior"] or new, "lowest")
          def fig(label, v, key):
              if not v: return f"<div><dt>{label}</dt><dd>—</dd></div>"
              u = usd(v[key], v["currency"]); orig = f"{v[key]:,.2f} CAD at {e(STORE_NAMES[v['store']])}" if v["currency"] == "CAD" else f"at {e(STORE_NAMES[v['store']])}"
              return f"<div><dt>{label}</dt><dd>${u:,.2f}<small> USD</small></dd><p class='fig-sub'>{orig}</p></div>"
          maxdrop = max((v["drop_pct"] for v in buyable), default=0)
          figs = fig(f"Lowest now · {szl}", bn, "price") + fig("Lowest ever · " + ("senior" if any(v["size"]=="Senior" for v in new) else "any size"), be, "lowest")
          figs += f"<div><dt>Biggest cut</dt><dd class='red'>{('−'+str(maxdrop)+'%') if maxdrop else '—'}</dd></div><div><dt>Confirmed in stock</dt><dd>{len(inst)}<small>/{len(vl)}</small></dd></div>"
          return f'<dl class="figs">{figs}</dl>' if vl else f'<p class="empty">{"No stores carry this right now."}</p>'
        fxnote = f"CAD prices converted at the Bank of Canada rate of {FX['usdcad']:.4f} ({FX['date']})." if FX["usdcad"] else ""
        ph = PHOTOS.get(s)
        photo = (f'<figure class="photo"><img src="{ph["file"]}" alt="{e(b)} {e(m)} hockey stick" width="{ph["w"]}" height="{ph["h"]}" loading="lazy" decoding="async">'
                 f'<figcaption>Product photo: {e(STORE_NAMES[ph["store"]])}</figcaption></figure>') if ph else ""
        body = f'''<div class="w page"><p class="crumb"><a href="/sticks/">Sticks</a> / {e(b)}</p><div class="{'phead has-photo' if ph else 'phead'}"><div><p class="kicker">{e(b)}</p><h1>{e(m)}</h1>
<p class="lede">Tracking {sum(1 for v in vl if not v["pro_stock"])} retail variants at {", ".join(stores) or "no retail store right now"}. New sticks and pro stock are kept separate, and lowest-ever counts new sticks only. {fxnote}</p>{ps_link(s, ps_by_model)}</div>{photo}</div>
{rsw(figs_for(vl), figs_for([v for v in vl if v["currency"]=="CAD"]).replace("No stores", "No Canadian stores"), figs_for([v for v in vl if v["currency"]=="USD"]).replace("No stores", "No US stores"))}<h2 class="h2">Price history</h2>{chart(series)}<h2 class="h2">Every variant: senior first, cheapest in stock first</h2>
<div class="tw"><table><thead><tr><th>Store</th><th>Size</th><th>Curve</th><th class="num">Flex</th><th>Hand</th><th class="num">Price</th><th class="num">Low</th><th>Stock</th><th></th></tr></thead><tbody>{tr}</tbody></table></div></div>'''
        desc = f"Current and lowest-ever prices for the {b} {m} hockey stick by curve, flex and hand."
        new = [v for v in vl if not v["pro_stock"]]
        # One Offer per store: its cheapest new (non-pro-stock) variant. Currency as the store lists it.
        per = {}
        for v in new:
            k = v["store"]
            if k not in per or ({1: 0, None: 1, 0: 2}[v["available"]], v["price"]) < ({1: 0, None: 1, 0: 2}[per[k]["available"]], per[k]["price"]): per[k] = v
        offers = []
        for v in sorted(per.values(), key=lambda v: STORE_NAMES[v["store"]]):
            o = {"@type": "Offer", "price": f'{v["price"]:.2f}', "priceCurrency": v["currency"], "url": v["url"], "seller": {"@type": "Organization", "name": STORE_NAMES[v["store"]]}, "itemCondition": "https://schema.org/NewCondition"}
            if v["available"] is not None: o["availability"] = "https://schema.org/" + ("InStock" if v["available"] else "OutOfStock")
            offers.append(o)
        prod = {"@context": "https://schema.org", "@type": "Product", "name": f"{b} {m} hockey stick", "brand": {"@type": "Brand", "name": b}, "url": f"https://twigdeals.com/sticks/{s}/", "description": desc}
        if ph: prod["image"] = "https://twigdeals.com" + ph["file"]
        curs = {o["priceCurrency"] for o in offers}
        if len(curs) == 1 and offers:
            ps = [float(o["price"]) for o in offers]
            prod["offers"] = {"@type": "AggregateOffer", "priceCurrency": curs.pop(), "lowPrice": f"{min(ps):.2f}", "highPrice": f"{max(ps):.2f}", "offerCount": len(offers), "offers": offers}
        elif offers: prod["offers"] = offers
        write(f"/sticks/{s}/", page(f"{b} {m} price tracker: lowest price by curve & flex | {SITE}", body, desc, ld(prod)))

    links = []
    for (c, f, sz), vl in sorted(combos.items()):
        path = f"/curves/{cslug(c)}-{f}-flex-{slug(sz)}/"; links.append((path, f"{c} {f} flex {sz}"))
        inst = sorted([v for v in vl if v["available"] and not v["pro_stock"]], key=lambda v: v["price"])
        psx = [x for x in PS if x["flex"] == f and x["size"] == sz and (x["rcurve"] == c or norm_curve(x.get("curve")) == c)]
        ps_sec = (f'<section class="pssec"><h2 class="h2">Pro stock <span class="psbadge">Separate from retail</span></h2><p class="sub">{len(psx)} pro stock sticks in this spec from pro stock sellers. '
                  f'Player-spec team sticks, graded by each store; prices in the store\'s currency, cheapest first. <a href="/pro-stock/">All pro stock →</a></p>'
                  f'<ol class="deals pslist">{"".join(ps_li(x, MODEL_NAMES) for x in psx[:40])}</ol></section>') if psx else ""
        body = f'''<div class="w page"><p class="crumb"><a href="/curves/">Curve + flex</a></p><h1>{e(c)} {e(f)} flex {e(sz.lower())} hockey sticks: best prices</h1>
<p class="sub">{len(inst)} in-stock retail options across {len({v["model_slug"] for v in inst})} models, cheapest first. Prices in original currency.</p>{rsw(deals_ol(inst[:30], "No retail stock in this spec right now."), deals_ol([v for v in inst if v["currency"]=="CAD"][:30], REG_EMPTY["ca"]), deals_ol([v for v in inst if v["currency"]=="USD"][:30], REG_EMPTY["us"]))}{ps_sec}</div>'''
        write(path, page(f"{c} {f} flex {sz} hockey stick deals | {SITE}", body))
    write("/curves/", page(f"Hockey stick deals by curve and flex | {SITE}", "<div class='w page'><p class='kicker'>Shop your spec</p><h1>Curve + flex</h1><p class='lede'>Every curve, flex and size combo with at least four live listings.</p><div class='chips'>" + "".join(f'<a href="{p}">{e(t)}</a>' for p, t in links) + "</div></div>"))

    prostock_page(PS, models)

    # Guide (real sources only)
    guide = """<article class="w page prose"><p class="kicker">Buying guide</p><h1>When do hockey sticks go on sale?</h1><p class="sub">Short answer: when the next generation launches and stores clear the old one, usually in late spring and summer, plus holiday sales. Here is what players and shops report.</p>
<h2>1. When new models launch (often May–July)</h2><p>Top-end sticks are refreshed roughly once a year and other tiers about every two years. The outgoing model goes on clearance around the launch. Players report prior-generation models getting marked down "typically in June/July", and that curve and flex choices shrink as the summer goes on.
Sources: <a href="https://www.reddit.com/r/hockeyplayers/comments/go9o7g/what_time_of_the_year_is_it_cheaper_to_order_new/">r/hockeyplayers: cheaper time of year</a>, <a href="https://www.reddit.com/r/hockeyplayers/comments/1n5uqiv/best_spot_to_buy_new_sticks/">r/hockeyplayers: best spot to buy new sticks</a>.</p>
<h2>2. Store year-end and summer clearance</h2><p>Some shops run year-end sales in summer. One player says Perani's in Michigan "typically [has] year-end sales in July every year". In Canada, Sport Chek has paired clearance with an extra 25% off. Players also warn that brands stagger releases and stores are getting better at running down stock, so there's no single sale date.
Source: <a href="https://www.reddit.com/r/hockeyplayers/comments/1kuauq1/best_time_of_year_to_buy_gear_on_sale/">r/hockeyplayers: best time of year to buy gear on sale</a>.</p>
<h2>3. Holiday and end-of-season sales</h2><p>Players point to holiday and end-of-season sales as the other good windows, and say last year's clearance is often cheaper than the current model ever gets.
Sources: <a href="https://www.reddit.com/r/hockeyplayers/comments/szj2o9/best_time_to_buy_new_hockey_gear/">r/hockeyplayers: best time to buy new gear</a>, <a href="https://www.reddit.com/r/hockeyplayers/comments/18pdf4g/really_how_much_should_a_stick_cost/">r/hockeyplayers: how much should a stick cost</a>.</p>
<h2>4. Buy last year's flagship or pro stock</h2><p>Many players aim for $150–$250 by buying the previous flagship on clearance or pro stock sticks instead of paying $350–$400+ for the newest model (same threads as above).</p>
<h2>How to use Twig Deals</h2><p>Open your stick's page to see current prices by curve, flex and hand at every tracked store, along with the lowest price we've seen. Or browse <a href="/curves/">by curve and flex</a>. Sign up below for the weekly deals email.</p></article>"""
    write("/guides/when-do-hockey-sticks-go-on-sale/", page(f"When do hockey sticks go on sale? | {SITE}", guide, "When hockey sticks go on sale: new-model launches, summer clearance and holiday sales, with sources."))
    # About: what we track and how. TwigDealsBot's user agent points here.
    srows = "".join(f'<li><a href="{e(u)}" rel="noopener"><span>{c}</span> {e(n)}</a></li>' for i, n, u, c in STORES)
    about = f"""<article class="w page prose"><p class="kicker">About</p><h1>How Twig Deals works</h1>
<p class="lede">Twig Deals tracks player hockey stick prices at {len(STORES)} stores, curve by curve and flex by flex, and keeps the history so you can see what actually dropped.</p>
<h2>Stores we track</h2><p>Prices are shown in the currency each store lists. On stick pages, the headline lowest-price figures convert CAD to USD at the Bank of Canada rate so stores can be compared.</p>
<ul class="index">{srows}</ul>
<h2>What we collect</h2><p>Senior, intermediate, junior and youth player sticks from the models in our index. Goalie sticks, blades, shafts, tape and accessories are left out. Pro stock sticks are listed only on the Pro stock page and never count toward the lowest-ever price.</p><h2>Pro stock section</h2><p>The <a href="/pro-stock/">Pro stock page</a> lists player-spec team sticks from three pro stock sellers, <a href="https://www.prostockhockey.com/player-sticks/" rel="noopener">Pro Stock Hockey</a> (US, USD), <a href="https://prostocknorthamerica.com/" rel="noopener">Pro Stock North America</a> and <a href="https://northprostock.com/" rel="noopener">North Prostock</a> (Canada, CAD), plus the pro stock sticks our retail stores carry. Each stick shows the store&rsquo;s condition grade. It is kept apart from the retail stores above and never counts toward deals, price history or lowest-ever prices.</p>
<h2>How we collect</h2><p>Twice a day, our collector reads each store's public product feed. It identifies itself as TwigDealsBot, checks the store's robots.txt first, and waits between requests. A store that asks us not to read its feed is skipped.</p>
<h2>Links</h2><p>Store links go straight to the product page. Some links may earn us a commission at no cost to you; that never changes the order or the prices we show. Prices change quickly, so confirm on the store page before you buy.</p></article>"""
    write("/about/", page(f"About Twig Deals and the stores we track | {SITE}", about, f"How Twig Deals tracks hockey stick prices at {len(STORES)} stores: {', '.join(n for _, n, _, _ in STORES)}."))
    AI_BOTS = ["GPTBot", "OAI-SearchBot", "ChatGPT-User", "PerplexityBot", "Perplexity-User", "ClaudeBot", "Claude-User", "Claude-SearchBot", "Google-Extended", "Applebot-Extended", "Applebot"]
    (OUT / "robots.txt").write_text("# AI search and assistant crawlers are welcome. Machine-readable summary: https://twigdeals.com/llms.txt\n"
        + "".join(f"User-agent: {u}\nAllow: /\n\n" for u in AI_BOTS) + "User-agent: *\nAllow: /\n\nSitemap: https://twigdeals.com/sitemap.xml\n")
    (OUT / "llms.txt").write_text(f"""# Twig Deals

> Twig Deals (twigdeals.com) is an independent hockey stick price tracker. It checks player stick prices at {len(STORES)} online stores twice a day, curve by curve and flex by flex, keeps the price history, and shows the biggest real price drops. Twig Deals is not affiliated with any stick brand or retailer, including Twig Hockey Company.

Currently tracking {len(models)} stick models and {len(live):,} live variants (size, curve, flex, hand) from Bauer, CCM, Warrior, True and Sherwood. Last updated {upd:%b %-d, %Y %-I:%M %p} ET.

## How prices are measured

- Updated twice daily, at about 6:15 AM and 6:15 PM Eastern Time, by reading each store's public product feed (crawler: TwigDealsBot, respects robots.txt).
- Prices are shown in the currency each store lists (CAD or USD), not converted. Stick-page headline figures convert CAD to USD at the Bank of Canada daily rate for comparison only.
- "% off" is measured against the higher of the stick's 7-day high price or the store's own list (compare-at) price.
- "Lowest ever" is the lowest price seen since tracking began on Oct 18, 2026, new sticks only. Pro stock / used sticks are tagged separately and never count toward lowest-ever.
- Prices change quickly; always confirm on the store page before buying. Some store links earn a commission; this never changes ordering or prices.

## Stores tracked

""" + "".join(f"- [{n}]({u}): lists in {c}\n" for _, n, u, c in STORES) + f"""
## Key pages

- [Home: this week's biggest drops](https://twigdeals.com/)
- [All tracked sticks](https://twigdeals.com/sticks/): one page per model with every variant, current price, lowest-ever price and stock at each store
- [Deals by curve and flex](https://twigdeals.com/curves/)
- [When do hockey sticks go on sale?](https://twigdeals.com/guides/when-do-hockey-sticks-go-on-sale/)
- [About and methodology](https://twigdeals.com/about/)
- [Sitemap](https://twigdeals.com/sitemap.xml)

## Data

- [Current top deals (JSON)](https://twigdeals.com/deals.json): best in-stock cut per model with stick, store, price, currency, list price, % off, URL and update timestamp
- Stick pages include schema.org Product JSON-LD with one Offer per store.

## Optional

- [Weekly "drop sheet" newsletter](https://twigdeals.beehiiv.com/subscribe): free email every Thursday with the biggest price cuts
""")
    urls = [str(p.parent.relative_to(OUT)) for p in OUT.rglob("index.html")]
    (OUT / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' +
        "".join(f"<url><loc>https://twigdeals.com/{'' if u=='.' else u+'/'}</loc></url>" for u in urls) + "</urlset>")
    print(f"built {len(urls)} pages: {len(models)} models, {len(combos)} curve pages, {len(live)} live variants")

if __name__ == "__main__":
    main()
