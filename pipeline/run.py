"""Run the whole segmentation pipeline for one video, as its own process.

    python -m pipeline.run <video> <workdir>

Writes <workdir>/progress.json while running and <workdir>/segments.json when done.
Running it as a separate process (see app/jobs.py) keeps a crash or an out-of-memory
kill from taking the web server down; readings are saved incrementally so a rerun resumes.
"""
import json, os, subprocess, sys, time
from pathlib import Path

import static_ffmpeg

static_ffmpeg.add_paths()

from pipeline import extract_hud, read_hud, segment  # noqa: E402

FPS = 1           # HUD readings per second


def progress(work, stage, pct, message=""):
    tmp = work / "progress.json.tmp"
    tmp.write_text(json.dumps(dict(stage=stage, pct=round(pct, 1), message=message, ts=time.time())))
    tmp.replace(work / "progress.json")


def probe_duration(video):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(video)],
        capture_output=True, text=True, check=True).stdout.strip()
    return float(out)


def main(video, work):
    video, work = Path(video), Path(work)
    work.mkdir(parents=True, exist_ok=True)
    duration = probe_duration(video)

    # stage 1: decode + crop the HUD strip (0-85%), by far the longest part
    npz = work / "hud.npz"
    if not npz.exists():
        progress(work, "Scanning video", 0)
        extract_hud.main(str(video), str(npz), FPS, gpu=os.environ.get("COACH_GPU", "1") != "0", duration=duration,
                         on_progress=lambda t: progress(work, "Scanning video", 85 * min(t / duration, 1)))

    # stage 2: read timer / scores (85-95%)
    readings = work / "readings.jsonl"
    progress(work, "Reading the HUD", 85)
    read_hud.main(str(npz), str(readings), int(os.environ.get("COACH_WORKERS", max(1, min(6, (os.cpu_count() or 2) - 1)))),
                  on_progress=lambda n, total: progress(work, "Reading the HUD", 85 + 10 * n / max(total, 1)))

    # stage 3: turn readings into segments
    progress(work, "Building timeline", 95)
    result = segment.analyze(str(readings))
    result["duration"] = max(result["duration"], duration)
    (work / "segments.json.tmp").write_text(json.dumps(result))
    (work / "segments.json.tmp").replace(work / "segments.json")
    npz.unlink(missing_ok=True)            # large, and only needed to re-read the HUD
    progress(work, "Done", 100)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
