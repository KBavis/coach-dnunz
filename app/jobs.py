"""Background processing: downloads and analyses run in parallel, each analysis in an isolated,
memory-guarded subprocess.

Two pools: up to DOWNLOADS YouTube downloads at once (network-bound), and up to ANALYSES
analyses at once (CPU/GPU-bound; each also decodes on the GPU when there is one, see
pipeline/extract_hud.py). A finished download joins the analysis queue, which runs VODs in the order they were added."""
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
_analyses: "queue.PriorityQueue[tuple]" = queue.PriorityQueue()   # (added at, id): oldest first
_pending: set = set()             # ids waiting in or running through either pool
_procs: dict = {}                 # id -> the yt-dlp or pipeline process running for it
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
    # so the lines carry their own PCT marker to match on, then bytes done / total / speed / eta
    template = ("download:PCT %(progress._percent_str)s|%(progress.downloaded_bytes)s|%(progress.total_bytes)s"
                "|%(progress.total_bytes_estimate)s|%(progress.speed)s|%(progress.eta)s")
    proc = subprocess.Popen(
        yt + ["--newline", "--progress-template", template, "-f", FORMAT,
              "--concurrent-fragments", "4",
              "--merge-output-format", "mp4", "-o", str(work / "source.%(ext)s"), url],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, **text)
    _procs[vod_id] = proc
    tail, streams, last = [], 0, 0.0
    for line in proc.stdout:
        tail = (tail + [line.strip()])[-4:]
        if "[download] Destination:" in line:
            streams += 1                  # video first, then audio: two downloads, one bar
        elif line.startswith("[Merger]"):
            _update(vod_id, stage="Joining video and audio", pct=99)
        elif m := re.search(r"PCT\s*([\d.]+)%(.*)", line):
            p = float(m.group(1))
            pct = p * 0.9 if streams <= 1 else 90 + p * 0.09
            if time.time() - last >= 1:   # the numbers change constantly; once a second is plenty
                last = time.time()
                what = "Downloading from YouTube" if streams <= 1 else "Downloading audio"
                _update(vod_id, stage=" · ".join([what, *_download_details(m.group(2))]), pct=round(pct, 1))
    proc.wait()
    _procs.pop(vod_id, None)
    if proc.returncode != 0 or video_path(vod_id) is None:
        return "download failed: " + " | ".join(x for x in tail if x)
    return None


def _download_details(rest):
    """'|done|total|estimate|speed|eta' from the progress line -> ['2.1 of 6.8 GB', '13 MB/s', '6 min left']."""
    def num(x):
        try:
            return float(x)
        except ValueError:
            return None
    parts = [num(x) for x in rest.strip().lstrip("|").split("|")] + [None] * 5
    done, total, estimate, speed, eta = parts[:5]
    total = total or estimate
    out = []
    if done is not None and total:
        out.append(f"{done / 1e9:.1f} of {total / 1e9:.1f} GB" if total >= 1e9 else f"{done / 1e6:.0f} of {total / 1e6:.0f} MB")
    if speed:
        out.append(f"{speed / 1e6:.0f} MB/s" if speed >= 1e6 else f"{speed / 1e3:.0f} kB/s")
    if eta is not None:
        out.append("under a minute left" if eta < 60 else f"{round(eta / 60)} min left")
    return out


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
    _analyses.put((_added_at(vod_id), vod_id))


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
    _procs[vod_id] = proc
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
    _procs.pop(vod_id, None)
    if _exists(vod_id) is None:                     # cancelled: deleted while it ran
        return
    seg = work / "segments.json"
    if proc.returncode == 0 and seg.exists():
        _update(vod_id, status="ready", stage="Done", pct=100,
                duration=json.loads(seg.read_text()).get("duration", 0))
    else:
        tail = (work / "run.log").read_text(errors="replace").strip().splitlines()[-3:]
        why = "stopped by the memory guard" if oom else f"exit code {proc.returncode}"
        _update(vod_id, status="failed", error=f"{why}: " + " | ".join(tail))


def _added_at(vod_id):
    con = db.connect()
    row = con.execute("SELECT created_at FROM vods WHERE id=?", (vod_id,)).fetchone()
    con.close()
    return row["created_at"] if row else 0


def _done(vod_id):
    with _lock:
        _pending.discard(vod_id)


def cancel(vod_id, wait=15):
    """Stop whatever is running for a VOD (download or analysis) and wait until its worker has
    let go of the folder, so it can be deleted. Call after removing its database row: a VOD that
    is only waiting in a queue is then skipped by the worker that picks it up."""
    proc = _procs.get(vod_id)
    if proc is None:
        return
    _kill_tree(proc.pid)
    deadline = time.time() + wait
    while vod_id in _procs and time.time() < deadline:   # the worker pops it once its log is closed
        time.sleep(0.1)


def _worker(q, step):
    setup.READY.wait()          # nothing can be processed until setup has finished
    while True:
        vod_id = q.get()
        if isinstance(vod_id, tuple):               # the analysis queue is ordered by when VODs were added
            vod_id = vod_id[1]
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
        _analyses.put((_added_at(vod_id), vod_id))


RESULTS_VERSION = 2   # pipeline.banner.RESULTS_VERSION (not imported: it pulls in OpenCV and OCR)


def _add_results():
    """VODs whose round / game results are missing or older than RESULTS_VERSION get them now, one
    at a time in the background (re-reading the banners and end screens, ~20-60 s per VOD)."""
    setup.READY.wait()
    con = db.connect()
    ids = [r["id"] for r in con.execute("SELECT id FROM vods WHERE status='ready' ORDER BY created_at DESC")]
    con.close()
    for vod_id in ids:
        seg, video = work_dir(vod_id) / "segments.json", video_path(vod_id)
        try:
            res = json.loads(seg.read_text())
        except (FileNotFoundError, ValueError):
            continue
        ends = [x for x in res["segments"] if x["phase"] == "ROUND_END"]
        if video is None or not ends or res.get("results_version", 1) >= RESULTS_VERSION:
            continue
        subprocess.run([sys.executable, "-m", "pipeline.banner", str(video), str(work_dir(vod_id))],
                       cwd=ROOT, env=_env(), capture_output=True, timeout=1800)


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
    threading.Thread(target=_add_results, daemon=True).start()
    con = db.connect()
    stuck = [r["id"] for r in con.execute("SELECT id FROM vods WHERE status IN ('queued','processing') ORDER BY created_at")]
    con.close()
    for vod_id in stuck:
        enqueue(vod_id)
