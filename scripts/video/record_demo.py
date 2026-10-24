"""Record the AEGIS demo from the LIVE running app (no mock-ups), timed to docs/DEMO_VIDEO_SCRIPT.md.

    python scripts/video/record_demo.py --url http://127.0.0.1:8000 [--user U --password P]
Writes scripts/video/out/raw.webm and scripts/video/out/timeline.json. Needs: pip install playwright (uses installed Chrome).
Simulation only: it clicks through the normal UI exactly as a judge would.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

OUT = Path(__file__).parent / "out"
# scene end times in seconds (match the narration script)
ENDS = [18, 40, 68, 98, 123, 145, 170, 180]

CURSOR_JS = """
(() => {
  const d = document.createElement('div');
  d.id = '__cur';
  d.style.cssText = 'position:fixed;z-index:99999;width:18px;height:18px;border-radius:50%;background:rgba(74,67,217,.85);' +
    'border:2px solid #fff;box-shadow:0 2px 8px rgba(0,0,0,.35);pointer-events:none;left:-40px;top:-40px;transform:translate(-50%,-50%);' +
    'transition:transform .12s';
  const add = () => document.body && document.body.appendChild(d);
  document.body ? add() : document.addEventListener('DOMContentLoaded', add);
  window.addEventListener('mousemove', e => { d.style.left = e.clientX + 'px'; d.style.top = e.clientY + 'px'; }, true);
  window.addEventListener('mousedown', e => {
    d.style.transform = 'translate(-50%,-50%) scale(.7)';
    const r = document.createElement('div');
    r.style.cssText = 'position:fixed;z-index:99998;border-radius:50%;border:3px solid rgba(74,67,217,.7);pointer-events:none;' +
      'left:' + e.clientX + 'px;top:' + e.clientY + 'px;width:10px;height:10px;transform:translate(-50%,-50%);transition:all .5s ease-out;opacity:1';
    document.body.appendChild(r);
    requestAnimationFrame(() => { r.style.width = '56px'; r.style.height = '56px'; r.style.opacity = '0'; });
    setTimeout(() => r.remove(), 600);
  }, true);
  window.addEventListener('mouseup', () => { d.style.transform = 'translate(-50%,-50%) scale(1)'; }, true);
})();
"""


class Timeline:
    def __init__(self) -> None:
        self.t0 = time.monotonic()
        self.marks: list[dict] = []

    def now(self) -> float:
        return time.monotonic() - self.t0

    def until(self, page: Page, t: float) -> None:
        rem = t - self.now()
        if rem > 0:
            page.wait_for_timeout(int(rem * 1000))
        elif rem < -1.5:
            print(f"  WARN scene overran its slot by {-rem:.1f}s")

    def mark(self, name: str) -> None:
        self.marks.append({"scene": name, "start": round(self.now(), 2)})


def glide(page: Page, locator, steps: int = 28) -> None:
    locator.scroll_into_view_if_needed()
    b = locator.bounding_box()
    page.mouse.move(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2, steps=steps)
    page.wait_for_timeout(250)


def click(page: Page, locator) -> None:
    glide(page, locator)
    locator.click()
    page.wait_for_timeout(350)


def smooth_scroll(page: Page, y: int, ms: int = 1200) -> None:
    page.evaluate("y => window.scrollTo({top: y, behavior: 'smooth'})", y)
    page.wait_for_timeout(ms)


def scroll_to(page: Page, selector: str, offset: int = 120, ms: int = 1200) -> None:
    page.evaluate("""([s, o]) => { const e = document.querySelector(s); if (e) window.scrollTo({top: e.getBoundingClientRect().top + window.scrollY - o, behavior: 'smooth'}); }""", [selector, offset])
    page.wait_for_timeout(ms)


def nav(page: Page, name: str) -> None:
    click(page, page.locator("nav button", has_text=name))
    page.wait_for_timeout(500)
    page.evaluate("window.scrollTo(0, 0)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--user", default="")
    ap.add_argument("--password", default="")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    for f in OUT.glob("*.webm"):
        f.unlink()
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        ctx = browser.new_context(viewport={"width": 1280, "height": 720}, record_video_dir=str(OUT),
                                  record_video_size={"width": 1280, "height": 720},
                                  http_credentials={"username": a.user, "password": a.password} if a.user else None)
        ctx.add_init_script(CURSOR_JS)
        page = ctx.new_page()
        created = time.monotonic()
        page.goto(a.url + "/?demo=1", wait_until="networkidle")
        page.wait_for_selector("text=Know the risk")
        page.wait_for_selector("article", timeout=30000)  # plan cards loaded from the live Shadow Twin API
        tl = Timeline()
        lead = tl.t0 - created  # video seconds before the timeline starts

        # 1 — problem / hero
        tl.mark("1 hero")
        page.mouse.move(640, 360)
        page.wait_for_timeout(3000)
        glide(page, page.get_by_role("button", name="Run the incident"), steps=40)
        tl.until(page, ENDS[0])

        # 2 — three plans
        tl.mark("2 plans")
        page.mouse.move(900, 300, steps=10)
        scroll_to(page, '[aria-label="How AEGIS decides"]', 100, 1500)
        page.wait_for_timeout(3000)
        scroll_to(page, '#plans', 90, 1500)
        page.wait_for_timeout(2500)
        smooth_scroll(page, page.evaluate("window.scrollY") + 330, 1500)
        page.wait_for_timeout(2500)
        smooth_scroll(page, page.evaluate("window.scrollY") + 400, 1500)
        tl.until(page, ENDS[1])

        # 3 — incident: stale reading, forced Plan A blocked, counterexample
        tl.mark("3 gate")
        nav(page, "Incident console")
        click(page, page.get_by_role("button", name="Load incident"))
        page.wait_for_timeout(1500)
        smooth_scroll(page, 380, 1200)
        sel = page.locator("select:has(option:text-is('A'))").first
        glide(page, sel)
        sel.select_option("A")
        page.wait_for_timeout(300)
        click(page, page.get_by_role("button", name="Request execution"))
        page.evaluate("window.scrollTo({top: 0, behavior: 'smooth'})")
        page.wait_for_timeout(2800)
        click(page, page.get_by_role("button", name="Run decision cycle"))
        page.wait_for_timeout(2000)
        scroll_to(page, "text=Candidate plans", 90, 1500)
        page.wait_for_timeout(4000)
        smooth_scroll(page, page.evaluate("window.scrollY") + 520, 1500)
        tl.until(page, ENDS[2])

        # 4 — approval, restore, second fault, replan
        tl.mark("4 approval")
        scroll_to(page, "text=Human approval required", 100, 1500)
        page.wait_for_timeout(2500)
        click(page, page.get_by_role("button", name="Approve & execute"))
        page.wait_for_timeout(2500)
        smooth_scroll(page, 0, 900)
        click(page, page.get_by_role("button", name="Inject fault"))
        page.wait_for_timeout(2500)
        scroll_to(page, "text=Human approval required", 100, 1500)
        page.wait_for_timeout(1500)
        click(page, page.get_by_role("button", name="Approve & execute"))
        page.wait_for_timeout(2000)
        scroll_to(page, "text=Outcome reporting · business metrics", 100, 1500)
        tl.until(page, ENDS[3])

        # (benchmark runs in the background from here, so its results are ready for scene 7)
        nav(page, "Benchmark")
        click(page, page.get_by_role("button", name="Run benchmark"))
        page.wait_for_timeout(600)

        # 5 — Shadow Twin
        tl.mark("5 shadow")
        nav(page, "Shadow twin")
        sel = page.locator("main select").first
        glide(page, sel)
        sel.select_option("A")
        click(page, page.get_by_role("button", name="Run shadow twin"))
        page.wait_for_selector("text=cells breach", timeout=30000)
        scroll_to(page, '[role=group]', 140, 1500)
        page.wait_for_timeout(5000)
        smooth_scroll(page, 0, 800)
        glide(page, sel)
        sel.select_option("C")
        click(page, page.get_by_role("button", name="Run shadow twin"))
        page.wait_for_timeout(2000)
        scroll_to(page, "text=Recovery time", 140, 1500)
        tl.until(page, ENDS[4])

        # 6 — real data and simulated replay
        tl.mark("6 real data")
        nav(page, "Real data")
        click(page, page.get_by_role("button", name="Load bundled real NPP file"))
        page.wait_for_selector("text=REAL HISTORICAL DATA", timeout=30000)
        scroll_to(page, 'svg[aria-label="Real demand trend"]', 170, 1500)
        page.wait_for_timeout(3500)
        scroll_to(page, "text=Replay as simulated stress scenarios", 100, 1500)
        click(page, page.get_by_role("button", name="Run replay"))
        page.wait_for_selector("text=SIMULATED stress scenarios derived", timeout=60000)
        scroll_to(page, "text=SIMULATED stress scenarios derived", 130, 1200)
        tl.until(page, ENDS[5])

        # 7 — evidence: benchmark results and proof record
        tl.mark("7 evidence")
        nav(page, "Benchmark")
        page.wait_for_selector("text=Pre-registered hypotheses", timeout=90000)
        scroll_to(page, "text=Energy & Utilities business view", 100, 1500)
        page.wait_for_timeout(4000)
        smooth_scroll(page, page.evaluate("window.scrollY") + 420, 1500)
        page.wait_for_timeout(3500)
        nav(page, "Proof record")
        page.wait_for_timeout(2500)
        glide(page, page.get_by_role("button", name="Download JSON"))
        tl.until(page, ENDS[6])

        # 8 — close
        tl.mark("8 close")
        nav(page, "Campus profile")
        page.mouse.move(980, 420, steps=20)
        tl.until(page, ENDS[7])

        total = tl.now()
        ctx.close()
        vid = page.video.path()
        browser.close()
    (OUT / "raw.webm").unlink(missing_ok=True)
    Path(vid).rename(OUT / "raw.webm")
    (OUT / "timeline.json").write_text(json.dumps({"lead_seconds": round(lead, 2), "duration": round(total, 2),
                                                   "marks": tl.marks}, indent=1), encoding="utf-8")
    print(f"recorded {total:.1f}s of footage; lead {lead:.1f}s -> {OUT / 'raw.webm'}")


if __name__ == "__main__":
    main()
