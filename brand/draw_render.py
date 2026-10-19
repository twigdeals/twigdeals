from pathlib import Path
from playwright.sync_api import sync_playwright
d=Path(__file__).parent
def shot(b, svg, size, out, transparent=False, vw=1024, vh=1024):
    ctx=b.new_context(viewport={"width":vw,"height":vh},device_scale_factor=size/vw); pg=ctx.new_page()
    pg.set_content(f"<html><body style='margin:0;background:{'transparent' if transparent else '#0E0F11'}'><img src='{(d/svg).as_uri()}' style='display:block;width:{vw}px;height:{vh}px'></body></html>")
    pg.goto((d/svg).as_uri()); pg.set_viewport_size({"width":vw,"height":vh}); pg.wait_for_timeout(300)
    pg.screenshot(path=str(d/out), omit_background=transparent); ctx.close()
with sync_playwright() as p:
    b=p.chromium.launch()
    for size,out in [(1024,"icon-1024.png"),(800,"logo-800.png"),(512,"icon-512.png"),(180,"apple-touch-icon.png")]: shot(b,"icon.svg",size,out)
    for size,out in [(48,"icon-48.png"),(32,"icon-32.png")]: shot(b,"icon-small.svg",size,out)
    shot(b,"wordmark-transparent.svg",1766,"wordmark.png",transparent=True,vw=883,vh=547)
    b.close()
