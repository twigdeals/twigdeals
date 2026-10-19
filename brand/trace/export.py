import re
from pathlib import Path
import numpy as np
from PIL import Image
from trace import layers, C, D, INK
B = D.parent; S = B.parent/"static"
def bbox(src):
    (W,H), L = layers(src); m = L["white"] | L["red"]
    ys, xs = np.where(m); u = 4
    return xs.min()/u, ys.min()/u, xs.max()/u, ys.max()/u
def reframe(svgfile, vb, bg=True):
    s = Path(svgfile).read_text()
    x,y,w,h = vb
    s = re.sub(r'viewBox="[^"]+"', f'viewBox="{x:.1f} {y:.1f} {w:.1f} {h:.1f}"', s, 1)
    s = re.sub(r'<rect width="\d+" height="\d+" fill="[^"]+"/>', f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="{INK}"/>' if bg else "", s, 1)
    return s
x0,y0,x1,y1 = bbox(C/"icon_concept.jpg"); cx,cy=(x0+x1)/2,(y0+y1)/2; side=max(x1-x0,y1-y0)/0.76
icon_vb=(cx-side/2, cy-side/2, side, side)
(B/"icon.svg").write_text(reframe(D/"icon_full.svg", icon_vb))
(B/"icon-small.svg").write_text(reframe(D/"icon_full_nochannel.svg", icon_vb))
x0,y0,x1,y1 = bbox(C/"wordmark_concept.jpg"); p=0.06*(x1-x0)
wm_vb=(x0-p, y0-p, x1-x0+2*p, y1-y0+2*p)
(B/"wordmark.svg").write_text(reframe(D/"wordmark_full.svg", wm_vb))
(B/"wordmark-transparent.svg").write_text(reframe(D/"wordmark_full_transparent.svg", wm_vb, bg=False))
print("icon vb", icon_vb, "wm vb", wm_vb)
