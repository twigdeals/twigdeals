#!/usr/bin/env python3
"""Twig Deals static site generator: data/prices.db -> dist/"""
import html, json, re, shutil, sqlite3, urllib.parse
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import urllib.request
ET = ZoneInfo("America/New_York")
STOCK_UNKNOWN = {"sourceforsports"}  # feed reports every variant available; not trustworthy

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "dist"
AFF = json.load(open(ROOT / "data/affiliates.json"))
STORE_NAMES = {"bauer": "Bauer.com", "prohockeylife": "Pro Hockey Life", "sourceforsports": "Source for Sports", "hockeystickman": "HockeyStickMan"}
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
def money(p, c): return f"${p:,.2f} {c}"
def aff(store, url):
    t = AFF.get(store) or ""
    return t.replace("{url_enc}", urllib.parse.quote(url, safe="")).replace("{url}", url) if t else url
def norm_curve(c):
    if not c: return None
    c = re.sub(r"\s*\(.*\)", "", c).strip().upper().replace("1/4", "").replace("+", "+")
    return c

CSS = open(ROOT / "static/site.css").read()

LOGO = """<svg class="mark" viewBox="0 0 168 32" aria-label="Twig Deals" role="img"><path d="M2 25 L22 25 L30 6" fill="none" stroke="currentColor" stroke-width="4.5" stroke-linecap="square"/><text x="38" y="25" font-family="Barlow Condensed" font-weight="800" font-size="27" letter-spacing=".5" fill="currentColor">TWIG</text><text x="96" y="25" font-family="Barlow Condensed" font-weight="800" font-size="27" letter-spacing=".5" fill="#E2231A">DEALS</text></svg>"""

def page(title, body, desc=""):
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title><meta name="description" content="{e(desc or TAGLINE)}"><meta name="theme-color" content="#0E0F11"><meta property="og:type" content="website"><meta property="og:site_name" content="Twig Deals"><meta property="og:title" content="{e(title)}"><meta property="og:description" content="{e(desc or TAGLINE)}"><meta property="og:image" content="https://twigdeals.com/og.png"><meta property="og:image:width" content="1200"><meta property="og:image:height" content="630"><meta name="twitter:card" content="summary_large_image"><meta name="twitter:image" content="https://twigdeals.com/og.png">
<link rel="preload" href="/fonts/BarlowCondensed-800.woff2" as="font" type="font/woff2" crossorigin><link rel="stylesheet" href="/style.css"></head><body>
<header class="top"><div class="w bar"><a class="logo" href="/">{LOGO}</a><nav><a href="/sticks/">Sticks</a><a href="/curves/">Curve + flex</a><a href="/guides/when-do-hockey-sticks-go-on-sale/">Sale calendar</a><a class="nav-cta" href="#newsletter">Weekly drops</a></nav></div></header>
<main>{body}{NEWSLETTER}</main><footer><div class="w foot"><div>{LOGO}<p>Hockey stick price tracker. Prices are pulled from retailer sites twice a day and can change; confirm on the store page before you buy. Some links earn us a commission at no cost to you. CAD and USD are shown as listed, not converted.</p></div><div class="flinks"><a href="/sticks/">All sticks</a><a href="/curves/">Curve + flex</a><a href="/guides/when-do-hockey-sticks-go-on-sale/">When sticks go on sale</a></div></div></footer></body></html>"""

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

def main():
    if OUT.exists(): shutil.rmtree(OUT)
    OUT.mkdir()
    (OUT / "style.css").write_text(open(ROOT/"static/fonts/fonts.css").read() + CSS); shutil.copytree(ROOT/"static/fonts", OUT/"fonts", dirs_exist_ok=True); shutil.copy(ROOT/"static/og.png", OUT/"og.png")
    db = sqlite3.connect(ROOT / "data/prices.db"); db.row_factory = sqlite3.Row
    last_ts = db.execute("SELECT max(last_seen) FROM variants").fetchone()[0]
    vs = {r["id"]: dict(r) for r in db.execute("SELECT * FROM variants")}
    hist = defaultdict(list)
    for r in db.execute("SELECT * FROM prices ORDER BY ts"): hist[r["variant_id"]].append(dict(r))
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    for vid, v in vs.items():
        h = hist[vid]; cur = h[-1]
        v.update(price=cur["price"], compare_at=cur["compare_at"], available=(None if v["store"] in STOCK_UNKNOWN else cur["available"]), current=v["last_seen"] == last_ts,
                 lowest=min(x["price"] for x in h), curve_n=norm_curve(v["curve"]))
        wk = [x["price"] for x in h if x["ts"] >= week_ago and x["ts"] != cur["ts"]]
        v["week_high"] = max(wk) if wk else None
        ref = max(filter(None, [v["week_high"], v["compare_at"]]), default=None)
        v["drop"] = (ref - v["price"]) if ref and ref > v["price"] else 0
        v["drop_pct"] = round(100 * v["drop"] / ref) if v["drop"] else 0
        v["drop_basis"] = "vs. 7-day high" if v["week_high"] and v["week_high"] > v["price"] else "vs. store's list price"
    live = [v for v in vs.values() if v["current"]]
    models = defaultdict(list)
    for v in live: models[(v["model_slug"], v["brand"], v["model"])].append(v)

    def card(v, extra=""):
        spec = " · ".join(filter(None,[v["size"] and v["size"][:3].upper()+".",v["curve"],(v["flex"] and v["flex"]+" flex"),v["hand"] and v["hand"][0]+"H"]))
        was = f'<s>{v["compare_at"]:,.2f}</s>' if v["compare_at"] and v["compare_at"]>v["price"] else ""
        badge = f'<span class="drop">−{v["drop_pct"]}%</span>' if v["drop_pct"] else '<span class="drop zero">—</span>'
        return f"""<li class="deal">{badge}<div class="d-name"><span class="brand">{e(v["brand"])}</span><a href="/sticks/{v["model_slug"]}/">{e(v["model"])}</a><span class="spec">{e(spec)}</span></div>
<div class="d-store">{e(STORE_NAMES[v["store"]])}</div><div class="d-spark">{spark([x["price"] for x in hist[v["id"]]])}</div>
<div class="d-price"><b>{v["price"]:,.2f}</b><small>{v["currency"]}</small>{was}</div><a class="go" rel="sponsored nofollow" href="{e(aff(v["store"],v["url"]))}" aria-label="View at {e(STORE_NAMES[v["store"]])}">View →</a></li>"""

    # Curve + flex landing pages
    combos = defaultdict(list)
    for v in live:
        if v["curve_n"] and v["flex"] and v["size"] and re.fullmatch(r"\d{2,3}", v["flex"].strip()):
            combos[(v["curve_n"], v["flex"].strip(), v["size"])].append(v)
    combos = {k: vl for k, vl in combos.items() if len(vl) >= 4}
    POPULAR = sorted(((f"/curves/{slug(c)}-{f}-flex-{slug(sz)}/", f"{c} · {f} · {sz[:3].upper()}") for (c,f,sz),vl in combos.items() if sz=="Senior"), key=lambda t: -len(combos[next(k for k in combos if f"/curves/{slug(k[0])}-{k[1]}-flex-{slug(k[2])}/"==t[0])]))
    # Homepage: best in-stock drop per model, new (non-pro-stock) sticks only
    best = {}
    for v in live:
        if v["available"] and v["drop_pct"] >= 10 and not v["pro_stock"]:
            k = v["model_slug"]
            if k not in best or v["drop_pct"] > best[k]["drop_pct"]: best[k] = v
    top = sorted(best.values(), key=lambda v: -v["drop_pct"])[:24]
    n_instock = sum(1 for v in live if v["available"])
    upd = datetime.strptime(last_ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).astimezone(ET)
    elite_low = sorted([v for v in live if v["available"] and not v["pro_stock"] and v["size"]=="Senior"], key=lambda v: v["price"])
    body = f"""<section class="hero"><div class="w"><p class="kicker">Updated {upd:%b %-d, %Y} · {upd:%-I:%M %p} ET</p>
<h1>Stop paying<br>full price for<br>a <em>twig.</em></h1>
<p class="lede">We check every stick at {len(STORE_NAMES)} stores twice a day, curve by curve and flex by flex, and show you what actually dropped.</p>
<dl class="figs"><div><dt>Models tracked</dt><dd>{len(models)}</dd></div><div><dt>Variants</dt><dd>{len(live):,}</dd></div><div><dt>In stock now</dt><dd>{n_instock:,}</dd></div><div><dt>Stores</dt><dd>{len({v["store"] for v in live})}</dd></div></dl></div></section>
<section class="w block"><div class="sec-head"><h2>This week's biggest drops</h2><p>Best in-stock cut per model, new sticks only. % is vs. the 7-day high or the store's own list price.</p></div>
<ol class="deals">{"".join(card(v) for v in top) or "<li>No drops of 10%+ right now.</li>"}</ol></section>
<section class="w block split"><div><div class="sec-head"><h2>Shop your spec</h2><p>Pick the curve and flex you already play.</p></div><div class="chips">{"".join(f'<a href="{p}">{e(t)}</a>' for p,t in POPULAR[:18])}</div></div>
<div><div class="sec-head"><h2>Every model</h2></div><ul class="index">{"".join(f'<li><a href="/sticks/{s}/"><span>{e(b)}</span> {e(m)}</a></li>' for s,b,m in sorted(models, key=lambda k:(k[1],k[2])))}</ul></div></section>"""
    write("/", page(f"{SITE}: hockey stick price tracker", body, "Track hockey stick prices and the best drops this week across Bauer, CCM, Warrior, True and Sherwood."))

    # Stick index + pages
    idx_rows = "".join(f'''<tr><td class="brand-c">{e(b)}</td><td><a href="/sticks/{s}/">{e(m)}</a></td><td class="num">{len(vl)}</td><td class="num">{sum(1 for v in vl if v["available"])}</td>
<td class="num">{" / ".join(f"{p:,.2f} {c}" for c,p in sorted({c: min((v["price"] for v in vl if v["available"] and v["currency"]==c and not v["pro_stock"]), default=None) for c in ("USD","CAD")}.items()) if p) or "—"}</td></tr>'''
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
        rows = sorted(vl, key=lambda v: ({1: 0, None: 1, 0: 2}[v["available"]], v["pro_stock"], SO.get(v["size"],4), v["price"]))
        tr = "".join(f'''<tr class="{'oos' if v['available'] == 0 else ''}"><td>{e(STORE_NAMES[v["store"]])}{' <span class="tag">Pro stock / used</span>' if v["pro_stock"] else ''}</td><td>{e(v["size"] or "")}</td><td class="mono">{e(v["curve"] or "")}</td><td class="num">{e(v["flex"] or "")}</td><td>{e(v["hand"] or "")}</td>
<td class="num"><b>{v["price"]:,.2f}</b> <small>{v["currency"]}</small>{f' <s>{v["compare_at"]:,.2f}</s>' if v["compare_at"] and v["compare_at"]>v["price"] else ""}</td><td class="num">{v["lowest"]:,.2f}</td><td>{'<span class="ok">In stock</span>' if v["available"] else ('<span class="unk">Check store</span>' if v["available"] is None else "Out")}</td>
<td><a class="go" rel="sponsored nofollow" href="{e(aff(v["store"],v["url"]))}">View →</a></td></tr>''' for v in rows)
        stores = sorted({STORE_NAMES[v["store"]] for v in vl})
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
        fxnote = f"CAD prices converted at the Bank of Canada rate of {FX['usdcad']:.4f} ({FX['date']})." if FX["usdcad"] else ""
        body = f'''<div class="w page"><p class="crumb"><a href="/sticks/">Sticks</a> / {e(b)}</p><p class="kicker">{e(b)}</p><h1>{e(m)}</h1>
<p class="lede">Tracking {len(vl)} variants at {", ".join(stores)}. New sticks and pro stock are kept separate, and lowest-ever counts new sticks only. {fxnote}</p>
<dl class="figs">{figs}</dl><h2 class="h2">Price history</h2>{chart(series)}<h2 class="h2">Every variant: senior first, cheapest in stock first</h2>
<div class="tw"><table><thead><tr><th>Store</th><th>Size</th><th>Curve</th><th class="num">Flex</th><th>Hand</th><th class="num">Price</th><th class="num">Low</th><th>Stock</th><th></th></tr></thead><tbody>{tr}</tbody></table></div></div>'''
        write(f"/sticks/{s}/", page(f"{b} {m} price tracker: lowest price by curve & flex | {SITE}", body, f"Current and lowest-ever prices for the {b} {m} hockey stick by curve, flex and hand."))

    links = []
    for (c, f, sz), vl in sorted(combos.items()):
        path = f"/curves/{slug(c)}-{f}-flex-{slug(sz)}/"; links.append((path, f"{c} {f} flex {sz}"))
        inst = sorted([v for v in vl if v["available"]], key=lambda v: v["price"])
        body = f'''<div class="w page"><p class="crumb"><a href="/curves/">Curve + flex</a></p><h1>{e(c)} {e(f)} flex {e(sz.lower())} hockey sticks: best prices</h1>
<p class="sub">{len(inst)} in-stock options across {len({v["model_slug"] for v in inst})} models, cheapest first. Prices in original currency.</p><ol class="deals">{"".join(card(v) for v in inst[:30]) or "<li>Nothing in stock right now.</li>"}</ol></div>'''
        write(path, page(f"{c} {f} flex {sz} hockey stick deals | {SITE}", body))
    write("/curves/", page(f"Hockey stick deals by curve and flex | {SITE}", "<div class='w page'><p class='kicker'>Shop your spec</p><h1>Curve + flex</h1><p class='lede'>Every curve, flex and size combo with at least four live listings.</p><div class='chips'>" + "".join(f'<a href="{p}">{e(t)}</a>' for p, t in links) + "</div></div>"))

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
    (OUT / "robots.txt").write_text("User-agent: *\nAllow: /\nSitemap: https://twigdeals.com/sitemap.xml\n")
    urls = [str(p.parent.relative_to(OUT)) for p in OUT.rglob("index.html")]
    (OUT / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' +
        "".join(f"<url><loc>https://twigdeals.com/{'' if u=='.' else u+'/'}</loc></url>" for u in urls) + "</urlset>")
    print(f"built {len(urls)} pages: {len(models)} models, {len(combos)} curve pages, {len(live)} live variants")

if __name__ == "__main__":
    main()
