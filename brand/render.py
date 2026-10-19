from pathlib import Path
from playwright.sync_api import sync_playwright
d=Path(__file__).parent
with sync_playwright() as p:
    b=p.chromium.launch()
    for n,w,h in [("logo",1024,1024),("thumb",1200,630)]:
        pg=b.new_page(viewport={"width":w,"height":h}); pg.goto((d/f"{n}.html").as_uri())
        pg.evaluate("document.fonts.ready"); pg.wait_for_timeout(300)
        print(n, pg.evaluate("[...document.fonts].map(f=>f.family+':'+f.status).join(',')"))
        pg.screenshot(path=str(d/("logo.png" if n=="logo" else "thumbnail.png")))
    b.close()
