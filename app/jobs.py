"""Background processing: downloads and analyses run in parallel, each analysis in an isolated,
memory-guarded subprocess.

Two pools: up to DOWNLOADS YouTube downloads at once (network-bound), and up to ANALYSES
analyses at once (CPU/GPU-bound; each also decodes on the GPU when there is one, see
pipeline/extract_hud.py). A finished download goes straight into the analysis queue."""
import json, os, queue, re, subprocess, sys, threading, time

import psutil

from . import db, setup

ROOT = db.ROOT


def _env(**extra):
    """Environment for subprocesses: ffmpeg and the venv's tools (deno, which yt-dlp needs for
    YouTube) on PATH, UTF-8 output on Windows too. Built per job: PATH only has ffmpeg once
    setup.add_tool_paths() has run."""
    setup.add_tool_paths()
    return dict(os.environ, PYTHONPATH=str(ROOT), PYTHONUTF8="1",
                PATH=os.pathsep.join([os.path.dirname(sys.executable), os.environ.get("PATH", "")]), **extra)
DOWNLOADS = int(os.environ.get("COACH_DOWNLOADS", 3))
ANALYSES = int(os.environ.get("COACH_PARALLEL", 2))
_downloads: "queue.Queue[str]" = queue.Queue()
_analyses: "queue.Queue[str]" = queue.Queue()
_pending: set = set()             # ids waiting in or running through either pool
_lock = threading.Lock()
_started = False


def _update(vod_id, **fields):
    con = db.connect()
    with con:
        cols = ", ".join(f"{k}=?" for k in fields)
        con.execute(f"UPDATE vods SET {cols} WHERE id=?", (*fields.values(), vod_id))
    con.close()


def work_dir(vod_id):
    return db.VODS / vod_id


VIDEO_EXT = {".mp4", ".mkv", ".mov", ".webm"}
FORMAT = "bv*[height<=1080]+ba/b[height<=1080]"


def video_path(vod_id):
    d = work_dir(vod_id)
    if not d.exists():
        return None
    # skip yt-dlp's per-stream intermediates (source.f299.mp4) until they are merged into source.mp4
    return next((p for p in sorted(d.iterdir()) if p.name.startswith("source.") and p.suffix.lower() in VIDEO_EXT
                 and not re.match(r"source\.f\d+\.", p.name)), None)


def _download(vod_id, url):
    """Fetch a YouTube video with yt-dlp into the VOD's folder. Returns an error string or None."""
    work = work_dir(vod_id)
    yt = [sys.executable, "-m", "yt_dlp", "--no-playlist"]
    text = dict(text=True, encoding="utf-8", errors="replace", env=_env())
    _update(vod_id, stage="Contacting YouTube", pct=0)
    try:
        t = subprocess.run(yt + ["--print", "title", url], capture_output=True, timeout=120, **text)
    except subprocess.TimeoutExpired:
        return "YouTube did not respond in time"
    if t.returncode != 0:
        return "yt-dlp could not read that link: " + " | ".join(t.stderr.strip().splitlines()[-2:])
    title = t.stdout.strip().splitlines()[0] if t.stdout.strip() else ""
    con = db.connect()
    with con:
        con.execute("UPDATE vods SET name=?, filename=? WHERE id=? AND name=?", (title or url, title or url, vod_id, url))
    con.close()
    # "download:" in a progress template only selects the line type, yt-dlp does not print it,
    # so the lines carry their own PCT marker to match on
    proc = subprocess.Popen(
        yt + ["--newline", "--progress-template", "download:PCT %(progress._percent_str)s", "-f", FORMAT,
              "--concurrent-fragments", "4",
              "--merge-output-format", "mp4", "-o", str(work / "source.%(ext)s"), url],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, **text)
    tail, streams, last = [], 0, -1.0
    for line in proc.stdout:
        tail = (tail + [line.strip()])[-4:]
        if "[download] Destination:" in line:
            streams += 1                  # video first, then audio: two downloads, one bar
        elif line.startswith("[Merger]"):
            _update(vod_id, stage="Joining video and audio", pct=99)
        elif m := re.search(r"PCT\s*([\d.]+)%", line):
            p = float(m.group(1))
            pct = p * 0.9 if streams <= 1 else 90 + p * 0.09
            if abs(pct - last) >= 0.1:
                last = pct
                _update(vod_id, stage="Downloading from YouTube" if streams <= 1 else "Downloading audio",
                        pct=round(pct, 1))
    proc.wait()
    if proc.returncode != 0 or video_path(vod_id) is None:
        return "download failed: " + " | ".join(x for x in tail if x)
    return None


def _min_free_mb():
    """Kill the job below this much free memory: MIN_MB if set, else 4 GB (less on small machines)."""
    if "MIN_MB" in os.environ:
        return int(os.environ["MIN_MB"])
    return min(4000, psutil.virtual_memory().total // 2**20 // 10)


def _kill_tree(pid):
    try:
        parent = psutil.Process(pid)
        procs = parent.children(recursive=True) + [parent]
    except psutil.NoSuchProcess:
        return
    for p in procs:
        try:
            p.kill()
        except psutil.NoSuchProcess:
            pass


def _exists(vod_id):
    con = db.connect()
    row = con.execute("SELECT source_url FROM vods WHERE id=?", (vod_id,)).fetchone()
    con.close()
    return row


def _fetch(vod_id):
    """Download pool: get the video, then hand it to the analysis pool."""
    row = _exists(vod_id)
    if row is None:                                  # deleted while waiting
        return _done(vod_id)
    if video_path(vod_id) is None:
        if not row["source_url"]:
            _update(vod_id, status="failed", error="video file is missing")
            return _done(vod_id)
        _update(vod_id, status="processing", error="")
        err = _download(vod_id, row["source_url"])
        if err:
            _update(vod_id, status="failed", error=err)
            return _done(vod_id)
    _update(vod_id, status="queued", stage="Downloaded, waiting for a free analysis slot", pct=0)
    _analyses.put(vod_id)


def _analyse(vod_id):
    work = work_dir(vod_id)
    video = video_path(vod_id)
    if _exists(vod_id) is None or video is None:
        return
    _update(vod_id, status="processing", stage="Starting", pct=0, error="")
    log = open(work / "run.log", "ab")
    # share the CPU between analyses running side by side
    env = _env(COACH_WORKERS=str(max(1, ((os.cpu_count() or 2) - 1) // ANALYSES)))
    proc = subprocess.Popen(
        [sys.executable, "-m", "pipeline.run", str(video), str(work)],
        cwd=ROOT, env=env, stdout=log, stderr=log, stdin=subprocess.DEVNULL)
    min_mb, oom, tick = _min_free_mb(), False, 0
    while proc.poll() is None:
        # memory guard: a runaway job gets killed (with its workers) before it can freeze the machine
        free = psutil.virtual_memory().available // 2**20
        if free < min_mb:
            log.write(f"WATCHDOG: available memory {free}MB < {min_mb}MB, killing job\n".encode())
            log.flush()
            _kill_tree(proc.pid)
            oom = True
            proc.wait()
            break
        if tick % 2 == 0:
            try:
                p = json.loads((work / "progress.json").read_text())
                _update(vod_id, stage=p["stage"], pct=p["pct"])
            except (FileNotFoundError, ValueError):
                pass
        tick += 1
        time.sleep(0.5)
    log.close()
    seg = work / "segments.json"
    if proc.returncode == 0 and seg.exists():
        _update(vod_id, status="ready", stage="Done", pct=100,
                duration=json.loads(seg.read_text()).get("duration", 0))
    else:
        tail = (work / "run.log").read_text(errors="replace").strip().splitlines()[-3:]
        why = "stopped by the memory guard" if oom else f"exit code {proc.returncode}"
        _update(vod_id, status="failed", error=f"{why}: " + " | ".join(tail))


def _done(vod_id):
    with _lock:
        _pending.discard(vod_id)


def _worker(q, step):
    setup.READY.wait()          # nothing can be processed until setup has finished
    while True:
        vod_id = q.get()
        try:
            step(vod_id)
        except Exception as e:                      # never let a worker die
            _update(vod_id, status="failed", error=repr(e))
            _done(vod_id)
        else:
            if step is _analyse:
                _done(vod_id)


def enqueue(vod_id):
    """Queue a VOD: to the download pool if its video still has to be fetched, else to analysis."""
    with _lock:
        if vod_id in _pending:
            return
        _pending.add(vod_id)
    if video_path(vod_id) is None:
        _update(vod_id, status="queued", stage="Waiting to download", pct=0, error="")
        _downloads.put(vod_id)
    else:
        _update(vod_id, status="queued", stage="Waiting for a free analysis slot", pct=0, error="")
        _analyses.put(vod_id)


def start():
    """Start the worker pools and resume anything interrupted by a restart."""
    global _started
    if _started:
        return
    _started = True
    for _ in range(DOWNLOADS):
        threading.Thread(target=_worker, args=(_downloads, _fetch), daemon=True).start()
    for _ in range(ANALYSES):
        threading.Thread(target=_worker, args=(_analyses, _analyse), daemon=True).start()
    con = db.connect()
    stuck = [r["id"] for r in con.execute("SELECT id FROM vods WHERE status IN ('queued','processing')")]
    con.close()
    for vod_id in stuck:
        enqueue(vod_id)
