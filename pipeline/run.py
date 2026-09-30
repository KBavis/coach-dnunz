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

FPS = 2


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

    # stage 1: decode + crop the HUD strip (0-25%)
    npz = work / "hud.npz"
    if not npz.exists():
        progress(work, "Scanning video", 0)
        extract_hud.main(str(video), str(npz), FPS,
                         on_progress=lambda t: progress(work, "Scanning video", 25 * min(t / duration, 1)))

    # stage 2: read timer / scores (25-95%)
    readings = work / "readings.jsonl"
    progress(work, "Reading the HUD", 25)
    read_hud.main(str(npz), str(readings), int(os.environ.get("COACH_WORKERS", "6")),
                  on_progress=lambda n, total: progress(work, "Reading the HUD", 25 + 70 * n / max(total, 1)))

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
