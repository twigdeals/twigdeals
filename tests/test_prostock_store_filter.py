#!/usr/bin/env python3
"""Pro Stock store filter must hide the other listings.

Selecting a store sets the hidden attribute and updates the count, but
.pslist .pscard { display:grid } overrides the user-agent [hidden] rule, so
every card stays visible. Region filtering is separate (display:none !important
on the other currency) and must keep working. Outbound store links must still
open in a new tab (target=_blank, rel keeps its existing tokens plus noopener).

Run: python3 tests/test_prostock_store_filter.py
Needs Chrome and Node. Browser cases are skipped when Chrome is not on PATH.
"""
import atexit
import re
import shutil
import subprocess
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHROME = shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chromium-browser")


def extract_js(name):
    src = (ROOT / "build.py").read_text()
    m = re.search(rf"{name} = r\"\"\"(.*?)\"\"\"", src, re.S)
    if not m:
        raise AssertionError(f"{name} not found in build.py")
    return m.group(1)


def load_newtab():
    src = (ROOT / "build.py").read_text()
    start = src.index("def newtab(")
    end = src.index("\ndef page(")
    ns = {"re": re}
    exec(src[start:end], ns)
    return ns["newtab"]


CARDS = """
<li class="pscard" data-id="hm-new" data-r="us" data-store="hockeymonkey" data-cond="New" data-hand="Left" data-flex="87" data-curve="P92" data-size="Senior" data-model="bauer-vapor">Hockey Monkey New</li>
<li class="pscard" data-id="hm-used" data-r="us" data-store="hockeymonkey" data-cond="Used" data-hand="Right" data-flex="77" data-curve="P28" data-size="Senior" data-model="bauer-vapor">Hockey Monkey Used</li>
<li class="pscard" data-id="psh-new" data-r="us" data-store="prostockhockey" data-cond="New" data-hand="Left" data-flex="87" data-curve="P92" data-size="Senior" data-model="bauer-vapor">Pro Stock Hockey New</li>
<li class="pscard" data-id="psna-new" data-r="ca" data-store="psna" data-cond="New" data-hand="Left" data-flex="87" data-curve="P92" data-size="Senior" data-model="bauer-vapor">PSNA New</li>
<li class="pscard" data-id="psna-pr" data-r="ca" data-store="psna" data-cond="Pro Return" data-hand="Right" data-flex="102" data-curve="P28" data-size="Intermediate" data-model="bauer-ag5nt">PSNA Pro Return</li>
"""

FORM = """
<div class="rgn" role="radiogroup" aria-label="Show stores in">
<button type="button" data-set="all">All</button>
<button type="button" data-set="ca">Canada</button>
<button type="button" data-set="us">US</button>
</div>
<form id="psf">
<select name="hand"><option value="">Any</option><option value="Left">Left</option><option value="Right">Right</option></select>
<select name="flex"><option value="">Any</option><option value="lt75">Under 75</option><option value="75-85">75-85</option><option value="87-95">87-95</option><option value="100+">100+</option></select>
<select name="curve"><option value="">Any</option><option value="P92">P92</option><option value="P28">P28</option></select>
<select name="size"><option value="">Any</option><option value="Senior">Senior</option><option value="Intermediate">Intermediate</option></select>
<select name="cond"><option value="">All</option><option value="New">New</option><option value="Used">Used</option><option value="Pro Return">Pro Return</option></select>
<select name="store"><option value="">All</option><option value="hockeymonkey">Hockey Monkey (USD)</option><option value="prostockhockey">Pro Stock Hockey (USD)</option><option value="psna">Pro Stock North America (CAD)</option></select>
<select name="model"><option value="">Any</option><option value="bauer-vapor">Bauer Vapor</option></select>
<button type="reset">Clear</button>
<b id="psn">0</b>
</form>
<ol class="deals pslist" id="psl">
""" + CARDS + """
</ol>
"""

# Each step runs, then the next step runs on a timeout so region clicks and
# form reset (both of which refilter on setTimeout 0) have applied.
INTERACT = r"""
(function(){
var out=[];
function vis(){return [].slice.call(document.querySelectorAll("#psl>li.pscard")).filter(function(li){return getComputedStyle(li).display!=="none"}).map(function(li){return li.getAttribute("data-id")})}
function eq(name,got,exp){var g=JSON.stringify(got),e=JSON.stringify(exp);out.push((g===e?"PASS ":"FAIL ")+name+" got="+g+" exp="+e)}
function setSelect(name,value){var el=document.getElementById("psf")[name];el.value=value;el.dispatchEvent(new Event("change",{bubbles:true}))}
function clickRegion(v){document.querySelector('.rgn button[data-set="'+v+'"]').click()}
var steps=[
function(){eq("initial-all-stores",vis(),["hm-new","hm-used","psh-new","psna-new","psna-pr"]);eq("initial-count",document.getElementById("psn").textContent,"5");eq("initial-grid",getComputedStyle(document.querySelector('[data-id="hm-new"]')).display,"grid");setSelect("store","hockeymonkey")},
function(){eq("store-only",vis(),["hm-new","hm-used"]);eq("store-count",document.getElementById("psn").textContent,"2");eq("other-store-hidden",getComputedStyle(document.querySelector('[data-id="psh-new"]')).display,"none");eq("same-store-shown",getComputedStyle(document.querySelector('[data-id="hm-new"]')).display,"grid");setSelect("cond","New")},
function(){eq("store-and-condition",vis(),["hm-new"]);eq("combined-count",document.getElementById("psn").textContent,"1");clickRegion("ca")},
function(){eq("us-store-while-canada",vis(),[]);eq("us-store-canada-count",document.getElementById("psn").textContent,"0");clickRegion("us")},
function(){eq("after-switch-back-to-us",vis(),["hm-new"]);setSelect("store","psna");clickRegion("ca")},
function(){eq("cad-store-and-condition-in-canada",vis(),["psna-new"]);clickRegion("all")},
function(){eq("store-and-condition-after-switch-to-all",vis(),["psna-new"]);document.querySelector('#psf button[type="reset"]').click()},
function(){eq("reset-all-stores",vis(),["hm-new","hm-used","psh-new","psna-new","psna-pr"]);eq("reset-count",document.getElementById("psn").textContent,"5");eq("store-select-cleared",document.getElementById("psf").store.value,"");clickRegion("us")},
function(){eq("region-us-after-reset",vis(),["hm-new","hm-used","psh-new"]);clickRegion("ca")},
function(){eq("region-ca-after-reset",vis(),["psna-new","psna-pr"]);setSelect("cond","Pro Return")},
function(){eq("condition-and-region",vis(),["psna-pr"]);out.push("WIDTH "+window.innerWidth)}
];
function finish(){var pre=document.createElement("pre");pre.id="testout";pre.textContent=out.join("\n");document.body.appendChild(pre)}
function run(i){if(i>=steps.length){finish();return}try{steps[i]()}catch(e){out.push("FAIL step "+i+" "+e.message);finish();return}setTimeout(function(){run(i+1)},0)}
run(0);
})();
"""

INITIAL = r"""
(function(){
var vis=[].slice.call(document.querySelectorAll("#psl>li.pscard")).filter(function(li){return getComputedStyle(li).display!=="none"}).map(function(li){return li.getAttribute("data-id")});
var pre=document.createElement("pre");pre.id="testout";
pre.textContent="VIS "+JSON.stringify(vis)+"\nCOUNT "+document.getElementById("psn").textContent+"\nSTORE "+document.getElementById("psf").store.value+"\nCOND "+document.getElementById("psf").cond.value;
document.body.appendChild(pre);
})();
"""


def page(script):
    css = (ROOT / "static" / "site.css").read_text().replace("</", "<\\/")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>{css}</style></head><body>
{FORM}
<script>{extract_js("REGION_JS")}</script>
<script>{extract_js("PS_JS")}</script>
<script>{script}</script>
</body></html>"""


NODE_DRIVER = r"""
const http = require('http');
const { pathToFileURL } = require('url');
const port = process.argv[2];
const htmlPath = process.argv[3];
const query = process.argv[4] || '';
const width = Number(process.argv[5] || 1280);
const height = Number(process.argv[6] || 900);
function get(p) {
  return new Promise((resolve, reject) => {
    http.get('http://127.0.0.1:' + port + p, res => {
      let d = '';
      res.on('data', c => d += c);
      res.on('end', () => resolve(JSON.parse(d)));
    }).on('error', reject);
  });
}
(async () => {
  const ver = await get('/json/version');
  const ws = new WebSocket(ver.webSocketDebuggerUrl);
  let id = 0;
  const pending = new Map();
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id); }
  };
  function send(method, params = {}, sessionId) {
    return new Promise((resolve, reject) => {
      const my = ++id;
      pending.set(my, (msg) => msg.error ? reject(new Error(JSON.stringify(msg.error))) : resolve(msg.result));
      const payload = { id: my, method, params };
      if (sessionId) payload.sessionId = sessionId;
      ws.send(JSON.stringify(payload));
    });
  }
  await new Promise(r => ws.onopen = r);
  const { targetId } = await send('Target.createTarget', { url: 'about:blank' });
  const { sessionId } = await send('Target.attachToTarget', { targetId, flatten: true });
  await send('Page.enable', {}, sessionId);
  await send('Runtime.enable', {}, sessionId);
  await send('Emulation.setDeviceMetricsOverride', {
    width, height, deviceScaleFactor: 1, mobile: width <= 720
  }, sessionId);
  const url = pathToFileURL(htmlPath).href + query;
  await send('Page.navigate', { url }, sessionId);
  let text = null, last = '';
  for (let i = 0; i < 40; i++) {
    const res = await send('Runtime.evaluate', {
      expression: 'document.getElementById("testout") && document.getElementById("testout").textContent',
      returnByValue: true
    }, sessionId);
    if (res.result && res.result.value) { text = res.result.value; break; }
    const body = await send('Runtime.evaluate', {
      expression: '(document.body && document.body.innerText || "").slice(0, 400)',
      returnByValue: true
    }, sessionId);
    last = (body.result && body.result.value) || '';
    await new Promise(r => setTimeout(r, 50));
  }
  if (!text) { console.error(last || 'no testout'); process.exit(2); }
  process.stdout.write(text);
  ws.close();
})().catch(e => { console.error(e); process.exit(1); });
"""


class Chrome:
    """One headless Chrome shared by the browser tests."""

    def __init__(self):
        if not CHROME:
            raise unittest.SkipTest("Chrome is not installed")
        self.td = tempfile.TemporaryDirectory()
        self.port = 9333
        self.proc = subprocess.Popen(
            [CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
             f"--remote-debugging-port={self.port}", f"--user-data-dir={self.td.name}/profile",
             "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(50):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/version", timeout=1).read()
                break
            except Exception:
                if self.proc.poll() is not None:
                    raise RuntimeError("Chrome exited before DevTools was ready")
                time.sleep(0.1)
        else:
            raise RuntimeError("Chrome DevTools did not come up")
        (Path(self.td.name) / "driver.js").write_text(NODE_DRIVER)

    def report(self, html, query="", window="1280,900"):
        path = Path(self.td.name) / "page.html"
        path.write_text(html)
        w, h = window.split(",")
        proc = subprocess.run(
            ["node", str(Path(self.td.name) / "driver.js"), str(self.port), str(path), query, w, h],
            capture_output=True, text=True, timeout=30)
        if proc.returncode != 0:
            raise AssertionError(f"browser driver failed ({proc.returncode})\n{proc.stderr[-2000:]}\n{proc.stdout[-1000:]}")
        return proc.stdout

    def close(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.td.cleanup()


_BROWSER = None


def browser():
    global _BROWSER
    if _BROWSER is None:
        _BROWSER = Chrome()
        atexit.register(_BROWSER.close)
    return _BROWSER


class ProStockStoreFilterTest(unittest.TestCase):
    def test_css_hides_filtered_cards(self):
        css = (ROOT / "static" / "site.css").read_text()
        self.assertRegex(css, r"\.pslist \.pscard\[hidden\]\{display:none !important\}|\.pslist \.pscard\[hidden\]\{display:none!important\}")

    def test_store_filter_interactions(self):
        report = browser().report(page(INTERACT), window="1280,900")
        fails = [line for line in report.splitlines() if line.startswith("FAIL")]
        self.assertFalse(fails, report)
        self.assertIn("WIDTH ", report)

    def test_store_filter_on_narrow_viewport(self):
        """The phone layout also sets display:grid on .pscard and must not bring hidden cards back."""
        report = browser().report(page(INTERACT), window="390,844")
        fails = [line for line in report.splitlines() if line.startswith("FAIL")]
        self.assertFalse(fails, report)
        width = int(re.search(r"WIDTH (\d+)", report).group(1))
        self.assertLessEqual(width, 720, report)

    def test_store_filter_on_initial_load(self):
        report = browser().report(page(INITIAL), query="?store=hockeymonkey")
        self.assertIn('VIS ["hm-new","hm-used"]', report)
        self.assertIn("COUNT 2", report)
        self.assertIn("STORE hockeymonkey", report)

    def test_store_and_condition_on_initial_load(self):
        report = browser().report(page(INITIAL), query="?store=psna&cond=Pro%20Return")
        self.assertIn('VIS ["psna-pr"]', report)
        self.assertIn("COUNT 1", report)
        self.assertIn("STORE psna", report)
        self.assertIn("COND Pro Return", report)

    def test_outbound_store_links_open_in_new_tab(self):
        newtab = load_newtab()
        html = (
            '<a class="go" rel="nofollow" href="https://www.prostockhockey.com/player-sticks/x">View →</a>'
            '<a class="go" rel="sponsored nofollow" href="https://www.hockeymonkey.com/p?x=1">View →</a>'
            '<a href="/sticks/bauer-vapor/">Bauer Vapor</a>'
            '<a class="nl-btn" href="https://twigdeals.beehiiv.com/subscribe" rel="noopener">Get the drop sheet</a>'
        )
        out = newtab(html)
        external = re.findall(r"<a\s[^>]*https?://[^>]*>", out)
        self.assertEqual(len(external), 3)
        for tag in external:
            self.assertIn('target="_blank"', tag)
            rel = re.search(r'rel="([^"]*)"', tag).group(1).split()
            self.assertIn("noopener", rel)
            self.assertEqual(rel.count("noopener"), 1)
        self.assertIn('rel="nofollow noopener"', out)
        self.assertIn('rel="sponsored nofollow noopener"', out)
        self.assertIn('<a href="/sticks/bauer-vapor/">Bauer Vapor</a>', out)
        self.assertNotIn('href="/sticks/bauer-vapor/" target', out)


if __name__ == "__main__":
    unittest.main()
