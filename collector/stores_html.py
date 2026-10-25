"""Collectors for non-Shopify stores. Each turns store HTML into Shopify-shaped product dicts
(title, vendor, handle, options, variants, images) so collect.save_product handles matching, specs and sizes."""
import html, json, re, time, urllib.request
from collect import UA, load_models, match

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")

# ---------- Ice Warehouse: brand stick category pages list products; each product page lists every in-stock SKU.
IW = "https://www.icewarehouse.com"
IW_CATS = ["Bauer_Composite_Hockey_Sticks/catpage-BAUERSTICKS", "CCM_Composite_Hockey_Sticks/catpage-CCMSTICKS",
           "Warrior_Composite_Hockey_Sticks/catpage-WARRSTICKS", "True_Composite_Hockey_Sticks/catpage-TRUESTICKS",
           "Sherwood_Composite_Hockey_Sticks/catpage-SHERSTICKS",
           "Bauer_Composite_Hockey_Sticks_-_Youth/catpage-JRCSBAUER", "CCM_Composite_Hockey_Sticks_-_Youth/catpage-JRCSCCM",
           "Warrior_Composite_Hockey_Sticks_-_Youth/catpage-JRCSWAR", "True_Composite_Hockey_Sticks_-_Youth/catpage-JRCTRUE",
           "Sherwood_Composite_Hockey_Sticks_-_Youth/catpage-JRCSSHER"]
IW_DELAY = 3.0
CELL = re.compile(r'data-gtm_impression_code="([^"]+)"\s*data-gtm_impression_name="([^"]+)"\s*data-gtm_impression_price="[^"]*"\s*data-gtm_impression_brand="([^"]*)"')
ROW = re.compile(r'<tr\s+class="js-ordering-subproduct[^"]*"[^>]*data-code="([^"]+)"(.*?)</tr>', re.S)

def iw_rows(page, url):
    variants = []
    for code, body in ROW.findall(page):
        price = re.search(r'js-ordering-price price">\s*([\d.,]+)', body)
        if not price: continue
        stock = re.search(r'js-ordering-available available">\s*(\d+)', body)
        st = {html.unescape(k).strip(): html.unescape(v).strip() for k, v in
              re.findall(r'js-ordering-style-name style">([^<]+)</strong>\s*:\s*<span class="js-ordering-style-item-name styleitem">([^<]+)<', body)}
        variants.append(dict(id=code, price=price.group(1).replace(",", ""), compare_at_price=None,
                             available=bool(stock and int(stock.group(1)) > 0), url=url,
                             option1=st.get("Hand"), option2=st.get("Flex"), option3=st.get("Curve") or st.get("Pattern"),
                             size_hint=st.get("Age Range") or st.get("Size") or ""))
    return variants

def iw_pages(store):
    models = load_models(); seen = set()
    for cat in IW_CATS:
        try: page = fetch(f"{IW}/{cat}.html")
        except Exception as e: print(f"  Ice Warehouse {cat}: {e}"); continue  # a retired category must not stop the rest
        finally: time.sleep(IW_DELAY)
        prods = []
        for code, name, brand in CELL.findall(page):
            if code in seen: continue
            seen.add(code); name = html.unescape(name)
            href = re.search(r'href="(https://www\.icewarehouse\.com/[^"]*descpage-' + re.escape(code) + r'\.html)"', page)
            img = re.search(r'<img[^>]*src="([^"]*path=' + re.escape(code) + r'-1\.jpg[^"]*)"', page)
            p = dict(title=name, product_type="Hockey Stick", vendor=brand.split(" (")[0], handle=code, tags="",
                     options=[{"name": "Hand"}, {"name": "Flex"}, {"name": "Curve"}], variants=[],
                     images=[{"src": html.unescape(img.group(1))}] if img else [])
            if not href or not match(p, store, models): continue  # only fetch product pages for tracked models
            try:
                p["variants"] = iw_rows(fetch(href.group(1)), href.group(1))
            except Exception as e:
                print(f"  Ice Warehouse {code}: {e}")
            time.sleep(IW_DELAY)
            prods.append(p)
        yield prods

# ---------- Hockey Monkey (Magento): category grid has a select_item JSON per product and a swatch jsonConfig
# with every salable child SKU (hand / flex / pattern) and its price. robots.txt asks for Crawl-delay: 10.
HM = "https://www.hockeymonkey.com"
HM_CATS = ["ice-hockey/sticks/composite/senior", "ice-hockey/sticks/composite/intermediate", "ice-hockey/sticks/composite/junior"]
HM_DELAY = 10.0
HM_MAX_PAGES = 15

def hm_parse(page):
    configs = {}
    for pid, cfg in re.findall(r'"\[data-role=swatch-option-(\d+)\]":\{"Magento_Swatches/js/swatch-renderer":\{.*?"jsonConfig":(\{.*?\}),"jsonSwatchConfig"', page, re.S):
        try: configs[pid] = json.loads(cfg)
        except Exception: pass
    prods = []
    for block in re.split(r'<li\s+class="item product product-item">', page)[1:]:
        m = re.search(r'select_item&quot;,&quot;ecommerce&quot;:(.*?)\);\s*\}"', block)
        href = re.search(r'href="(https://www\.hockeymonkey\.com/[^"]+\.html)"', block)
        if not m or not href: continue
        try: item = json.loads(html.unescape(m.group(1))[:-1])["items"][0]
        except Exception: continue
        pid = str(item["item_id"]); url = href.group(1)
        img = re.search(r'data-src="([^"]+)"', block)
        variants = []
        cfg = configs.get(pid)
        if cfg:
            specs = {}
            for a in cfg.get("attributes", {}).values():
                key = {"hockeystickhand": "option1", "hockeystickflex": "option2", "hockeystickpattern": "option3"}.get(a.get("code"))
                for o in a.get("options", []):
                    for child in o.get("products", []):
                        if key: specs.setdefault(child, {})[key] = o["label"]
            for child, sp in specs.items():
                pr = cfg.get("optionPrices", {}).get(child, {})
                price = (pr.get("finalPrice") or {}).get("amount")
                old = (pr.get("oldPrice") or {}).get("amount")
                if not price: continue
                variants.append(dict(id=child, price=str(price), compare_at_price=str(old) if old and old > price else None,
                                     available=True, url=url, **sp))
        if not variants:
            variants = [dict(id=pid, price=str(item["price"]), compare_at_price=None, url=url,
                             available=item.get("item_stock_status", "").lower() == "in stock")]
        prods.append(dict(title=html.unescape(item["item_name"]), product_type="Hockey Stick", vendor=item.get("item_brand", ""),
                          handle=pid, tags="", options=[{"name": "Hand"}, {"name": "Flex"}, {"name": "Curve"}],
                          variants=variants, images=[{"src": img.group(1)}] if img else []))
    return prods

def hm_pages(store):
    seen = set()
    for cat in HM_CATS:
        for n in range(1, HM_MAX_PAGES + 1):
            prods = hm_parse(fetch(f"{HM}/{cat}.html?p={n}")); time.sleep(HM_DELAY)
            new = [p for p in prods if p["handle"] not in seen]
            if not new: break
            seen.update(p["handle"] for p in new)
            yield new

STORES = [
    dict(id="icewarehouse", name="Ice Warehouse", base=IW, currency="USD", pages=iw_pages, probe="/" + IW_CATS[0] + ".html"),
    dict(id="hockeymonkey", name="Hockey Monkey", base=HM, currency="USD", pages=hm_pages, probe="/" + HM_CATS[0] + ".html"),
]
