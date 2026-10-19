from pathlib import Path
from playwright.sync_api import sync_playwright
from PIL import Image, ImageChops
import numpy as np
D=Path(__file__).parent; C=D.parent/"concepts"
def render(svg, out, w=1280, h=720, transparent=False):
    with sync_playwright() as p:
        b=p.chromium.launch(); pg=b.new_page(viewport={"width":w,"height":h})
        pg.goto(Path(svg).resolve().as_uri()); pg.wait_for_timeout(200); pg.screenshot(path=str(out), omit_background=transparent); b.close()
for name in ["icon","wordmark"]:
    render(D/f"{name}_full.svg", D/f"{name}_vec.png")
    o=Image.open(C/f"{name}_concept.jpg").convert("RGB"); v=Image.open(D/f"{name}_vec.png").convert("RGB")
    sbs=Image.new("RGB",(2560,720)); sbs.paste(o,(0,0)); sbs.paste(v,(1280,0)); sbs.save(D/f"{name}_side.png")
    # overlay: original luminance in red channel, vector in green -> mismatches show red/green, matches yellow
    lo=np.asarray(o.convert("L")); lv=np.asarray(v.convert("L"))
    ov=np.stack([lo,lv,np.zeros_like(lo)],-1).astype("uint8"); Image.fromarray(ov).save(D/f"{name}_overlay.png")
    mo=lo>100; mv=lv>100; x=(mo^mv).sum(); print(name,"mismatch px",int(x),"of shape px",int(mo.sum()), f"{100*x/max(mo.sum(),1):.2f}%")
