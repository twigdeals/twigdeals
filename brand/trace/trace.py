"""Faithful vectorization of the chosen concepts: upscale, split color layers by threshold, potrace each, recombine in palette."""
import subprocess, re, sys
from pathlib import Path
from PIL import Image, ImageFilter
import numpy as np
from scipy import ndimage
INK, ICE, RED = "#0E0F11", "#F6F7F5", "#E2231A"
D = Path(__file__).parent; C = D.parent/"concepts"
UP = 4

def layers(src):
    im = Image.open(src).convert("RGB")
    W, H = im.size
    big = im.resize((W*UP, H*UP), Image.LANCZOS).filter(ImageFilter.GaussianBlur(1.2))
    a = np.asarray(big).astype(int); r, g, b = a[...,0], a[...,1], a[...,2]
    red = (r > 110) & (r - g > 60) & (r - b > 50)
    white = ((r + g + b) / 3 > 128) & ~red
    white = ndimage.binary_opening(white, iterations=1)
    red = ndimage.binary_opening(red, iterations=1)
    filled = ndimage.binary_fill_holes(white)
    holes = filled & ~white          # dark areas enclosed by white: tape patch / inset channel
    return (W, H), {"white": filled, "red": red, "dark": holes}

def trace(mask, name):
    pbm = D/f"{name}.pbm"; svg = D/f"{name}.svg"
    Image.fromarray(((~mask) * 255).astype("uint8")).convert("1").save(pbm)
    subprocess.run(["potrace", str(pbm), "-s", "-o", str(svg), "-t", "40", "-a", "0.55", "-O", "0.4", "--flat"], check=True)
    s = svg.read_text()
    g = re.search(r"<g transform=\"([^\"]+)\"[^>]*>(.*?)</g>", s, re.S)
    return g.group(1), re.findall(r'd="([^"]+)"', g.group(2))

def build(src, out, bg=True, drop_dark=False):
    (W, H), L = layers(src)
    parts = []
    order = [("white", ICE), ("dark", INK), ("red", RED)]
    for name, col in order:
        if name == "dark" and drop_dark: continue
        if not L[name].any(): continue
        tf, ds = trace(L[name], f"{Path(src).stem}-{name}")
        parts.append(f'<g transform="{tf}" fill="{col}"><path d="{" ".join(ds)}"/></g>')
    inner = "".join(parts)
    # potrace coords are in upscaled pixels; scale back to concept size
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}">' + (f'<rect width="{W}" height="{H}" fill="{INK}"/>' if bg else "") +
           f'<g transform="scale({1/UP})">{inner}</g></svg>')
    Path(out).write_text(svg)
    return L

if __name__ == "__main__":
    build(C/"icon_concept.jpg", D/"icon_full.svg")
    build(C/"icon_concept.jpg", D/"icon_full_nochannel.svg", drop_dark=True)
    build(C/"wordmark_concept.jpg", D/"wordmark_full.svg")
    build(C/"wordmark_concept.jpg", D/"wordmark_full_transparent.svg", bg=False)
    print("ok")
