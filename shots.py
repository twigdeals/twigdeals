from playwright.sync_api import sync_playwright
pages={"home":"/","stick":"/sticks/ccm-jetspeed-ft8-pro/"}
with sync_playwright() as p:
    b=p.chromium.launch()
    for dev,vp,full in [("desktop",{"width":1440,"height":900},True),("mobile",{"width":390,"height":844},True)]:
        ctx=b.new_context(viewport=vp,device_scale_factor=2 if dev=="mobile" else 1)
        pg=ctx.new_page()
        for n,u in pages.items():
            pg.goto("http://localhost:8765"+u); pg.wait_for_timeout(400)
            pg.screenshot(path=f"screens/{n}-{dev}.png",full_page=full); pg.screenshot(path=f"screens/{n}-{dev}-fold.png")
    b.close()
