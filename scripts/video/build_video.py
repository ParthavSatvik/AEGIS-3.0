"""Build the final demo MP4 from the recorded footage (+ your voice-over), capped under 50 MB.

    python scripts/video/build_video.py                       # silent preview
    python scripts/video/build_video.py --audio my_voice.m4a  # syncs footage to your audio and muxes it
Footage is retimed (within +/-15%) so its length matches your audio. Audio longer than 3:00 is refused.
Output: scripts/video/out/AEGIS_demo.mp4
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import imageio_ffmpeg

OUT = Path(__file__).parent / "out"
FF = imageio_ffmpeg.get_ffmpeg_exe()
MAX_MB = 48.0  # leave headroom under the 50 MB limit


def duration(path: Path) -> float:
    r = subprocess.run([FF, "-i", str(path)], capture_output=True, text=True)
    m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", r.stderr)
    if not m:
        raise SystemExit(f"cannot read duration of {path}")
    h, mi, s = m.groups()
    return int(h) * 3600 + int(mi) * 60 + float(s)


def encode(args: list[str], out: Path) -> None:
    r = subprocess.run([FF, "-y", "-loglevel", "error", *args, str(out)], capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(r.stderr)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio")
    ap.add_argument("--out", default=str(OUT / "AEGIS_demo.mp4"))
    a = ap.parse_args()
    raw = OUT / "raw.webm"
    tl = json.loads((OUT / "timeline.json").read_text())
    lead, planned = tl["lead_seconds"], tl["duration"]
    footage = duration(raw) - lead
    print(f"footage: {footage:.1f}s (timeline {planned:.1f}s, lead-in cut {lead:.1f}s)")

    factor, audio_len = 1.0, None
    if a.audio:
        audio_len = duration(Path(a.audio))
        if audio_len > 180.5:
            raise SystemExit(f"audio is {audio_len:.1f}s: the limit is 3:00 (180s). Please re-record a shorter take.")
        factor = audio_len / planned
        print(f"audio: {audio_len:.1f}s -> retime factor {factor:.3f}")
        if not 0.85 <= factor <= 1.15:
            print("WARNING: audio length differs from the 3:00 plan by more than 15%; scenes will drift from the narration. "
                  "Re-record closer to the timings, or tell me and I'll re-time the scenes.")
    vf = f"trim=start={lead},setpts=(PTS-STARTPTS)*{factor:.5f},fps=30,scale=1280:720:flags=lanczos,format=yuv420p"
    fade_start = max(0.0, (audio_len or planned) - 0.8)
    vf += f",fade=t=out:st={fade_start:.2f}:d=0.8"
    target = a.out
    for crf in (26, 28, 30, 33):
        cmd = ["-i", str(raw)]
        if a.audio:
            cmd += ["-i", a.audio]
        cmd += ["-vf", vf, "-c:v", "libx264", "-preset", "medium", "-crf", str(crf), "-maxrate", "1500k", "-bufsize", "3000k",
                "-movflags", "+faststart", "-pix_fmt", "yuv420p"]
        if a.audio:
            cmd += ["-map", "0:v:0", "-map", "1:a:0", "-c:a", "aac", "-b:a", "128k", "-af",
                    f"afade=t=out:st={fade_start:.2f}:d=0.8", "-shortest"]
        else:
            cmd += ["-an", "-t", f"{planned:.2f}"]
        encode(cmd, Path(target))
        size = Path(target).stat().st_size / 1e6
        print(f"crf {crf}: {size:.1f} MB")
        if size <= MAX_MB:
            break
    else:
        sys.exit("could not get under the size limit")
    print(f"DONE {target}  {duration(Path(target)):.1f}s  {Path(target).stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
