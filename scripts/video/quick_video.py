"""Fast demo video: real screenshots of each scene from the running app, timed to the voice-over, under 50 MB.
    python scripts/video/quick_video.py <audio> <out.mp4>
"""
import subprocess
import sys
from pathlib import Path

import imageio_ffmpeg
from playwright.sync_api import sync_playwright

AUDIO, OUTF = sys.argv[1], sys.argv[2]
URL = "http://127.0.0.1:8000"
D = Path(__file__).parent / "out" / "shots"
D.mkdir(parents=True, exist_ok=True)
FF = imageio_ffmpeg.get_ffmpeg_exe()
WEIGHTS = [20, 25, 30, 30, 20, 20, 25, 10]  # scene lengths from the narration plan


def go_tab(p, name):
    p.locator("nav button", has_text=name).click()
    p.wait_for_timeout(600)
    p.evaluate("window.scrollTo(0,0)")


def to(p, text, off=110):
    p.evaluate("""([t,o]) => { const w=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
      while(w.nextNode()){ if(w.currentNode.textContent.includes(t)){ const e=w.currentNode.parentElement;
      window.scrollTo(0, e.getBoundingClientRect().top+window.scrollY-o); return; } } }""", [text, off])
    p.wait_for_timeout(500)


shots = []
with sync_playwright() as pw:
    b = pw.chromium.launch(channel="chrome")
    p = b.new_page(viewport={"width": 1280, "height": 720}, device_scale_factor=1.5)
    p.goto(URL + "/?v=vid", wait_until="networkidle")
    p.wait_for_selector("article", timeout=30000)
    p.wait_for_timeout(1200)

    def snap(name):
        f = D / f"{len(shots)}_{name}.png"
        p.screenshot(path=str(f))
        shots.append(f)

    snap("hero")
    to(p, "Reserve protection versus restoration deadline", 80)
    snap("plans")
    go_tab(p, "Incident console")
    p.get_by_role("button", name="Load incident").click()
    p.wait_for_timeout(1200)
    p.locator("select:has(option:text-is('A'))").first.select_option("A")
    p.get_by_role("button", name="Request execution").click()
    p.wait_for_timeout(900)
    p.get_by_role("button", name="Run decision cycle").click()
    p.wait_for_timeout(1500)
    to(p, "Counterexample", 260)
    snap("gate")
    p.get_by_role("button", name="Approve & execute").click()
    p.wait_for_timeout(1500)
    p.get_by_role("button", name="Inject fault").click()
    p.wait_for_timeout(1500)
    p.get_by_role("button", name="Approve & execute").click()
    p.wait_for_timeout(1500)
    to(p, "Outcome reporting", 90)
    snap("approval")
    go_tab(p, "Shadow twin")
    p.locator("main select").first.select_option("A")
    p.get_by_role("button", name="Run shadow twin").click()
    p.wait_for_selector("text=cells breach", timeout=30000)
    p.wait_for_timeout(600)
    to(p, "cells breach", 200)
    snap("shadow")
    go_tab(p, "Real data")
    p.get_by_role("button", name="Load bundled real NPP file").click()
    p.wait_for_selector("text=REAL HISTORICAL DATA", timeout=30000)
    p.wait_for_timeout(800)
    to(p, "REAL HISTORICAL DATA", 90)
    snap("realdata")
    go_tab(p, "Benchmark")
    p.get_by_role("button", name="Run benchmark").click()
    try:
        p.wait_for_selector("text=Energy & Utilities business view", timeout=120000)
        p.wait_for_timeout(800)
        to(p, "Energy & Utilities business view", 90)
    except Exception:
        go_tab(p, "Proof record")
    snap("proof")
    go_tab(p, "Campus profile")
    p.wait_for_timeout(1200)
    snap("close")
    b.close()

r = subprocess.run([FF, "-i", AUDIO], capture_output=True, text=True).stderr
h, m, s = r.split("Duration: ")[1].split(",")[0].split(":")
total = int(h) * 3600 + int(m) * 60 + float(s)
durs = [w / sum(WEIGHTS) * total for w in WEIGHTS]
args, filt = [], []
for i, (f, d) in enumerate(zip(shots, durs)):
    args += ["-loop", "1", "-t", f"{d:.2f}", "-i", str(f)]
    # gentle Ken Burns zoom + fade in/out per scene
    frames = int(d * 30)
    filt.append(f"[{i}:v]scale=1920:1080,zoompan=z='min(zoom+0.0004,1.06)':d={frames}:s=1280x720:fps=30,"
                f"fade=t=in:st=0:d=0.4,fade=t=out:st={max(0, d - 0.4):.2f}:d=0.4,setsar=1[v{i}]")
filt.append("".join(f"[v{i}]" for i in range(len(shots))) + f"concat=n={len(shots)}:v=1:a=0[v]")
cmd = [FF, "-y", "-loglevel", "error", *args, "-i", AUDIO, "-filter_complex", ";".join(filt), "-map", "[v]",
       "-map", f"{len(shots)}:a", "-c:v", "libx264", "-preset", "veryfast", "-crf", "24", "-pix_fmt", "yuv420p",
       "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart", OUTF]
subprocess.run(cmd, check=True)
print(f"DONE {OUTF} {Path(OUTF).stat().st_size / 1e6:.1f} MB, {total:.1f}s, {len(shots)} scenes")
