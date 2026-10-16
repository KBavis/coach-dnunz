"""Background processing: one VOD at a time, each in an isolated, memory-guarded subprocess."""
import json, os, queue, re, subprocess, sys, threading, time

import psutil
import static_ffmpeg

from . import db

static_ffmpeg.add_paths()   # puts ffmpeg/ffprobe on PATH for yt-dlp and the pipeline

ROOT = db.ROOT
# subprocesses see the venv's tools (deno, which yt-dlp needs for YouTube) and speak UTF-8 on Windows too
ENV = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONUTF8="1",
           PATH=os.pathsep.join([os.path.dirname(sys.executable), os.environ.get("PATH", "")]))
_q: "queue.Queue[str]" = queue.Queue()
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
    return next((p for p in sorted(d.iterdir()) if p.name.startswith("source.") and p.suffix.lower() in VIDEO_EXT), None)


def _download(vod_id, url):
    """Fetch a YouTube video with yt-dlp into the VOD's folder. Returns an error string or None."""
    work = work_dir(vod_id)
    yt = [sys.executable, "-m", "yt_dlp", "--no-playlist"]
    text = dict(text=True, encoding="utf-8", errors="replace", env=ENV)
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
    proc = subprocess.Popen(
        yt + ["--newline", "--progress-template", "download:%(progress._percent_str)s", "-f", FORMAT,
              "--merge-output-format", "mp4", "-o", str(work / "source.%(ext)s"), url],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, **text)
    tail = []
    for line in proc.stdout:
        tail = (tail + [line.strip()])[-4:]
        m = re.search(r"download:\s*([\d.]+)%", line)
        if m:
            _update(vod_id, stage="Downloading from YouTube", pct=float(m.group(1)))
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


def _run(vod_id):
    work = work_dir(vod_id)
    _update(vod_id, status="processing", stage="Starting", pct=0, error="")
    if video_path(vod_id) is None:
        con = db.connect()
        url = con.execute("SELECT source_url FROM vods WHERE id=?", (vod_id,)).fetchone()["source_url"]
        con.close()
        if not url:
            return _update(vod_id, status="failed", error="video file is missing")
        err = _download(vod_id, url)
        if err:
            return _update(vod_id, status="failed", error=err)
    video = video_path(vod_id)
    _update(vod_id, stage="Starting", pct=0)
    log = open(work / "run.log", "ab")
    proc = subprocess.Popen(
        [sys.executable, "-m", "pipeline.run", str(video), str(work)],
        cwd=ROOT, env=ENV, stdout=log, stderr=log, stdin=subprocess.DEVNULL)
    min_mb, oom, tick = _min_free_mb(), False, 0
    while proc.poll() is None:
        # memory guard: a runaway job gets killed (with its OCR workers) before it can freeze the machine
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


def _worker():
    while True:
        vod_id = _q.get()
        try:
            _run(vod_id)
        except Exception as e:                      # never let the worker die
            _update(vod_id, status="failed", error=repr(e))


def enqueue(vod_id):
    _update(vod_id, status="queued", stage="Waiting", pct=0, error="")
    _q.put(vod_id)


def start():
    """Start the worker thread and resume anything interrupted by a restart."""
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_worker, daemon=True).start()
    con = db.connect()
    stuck = [r["id"] for r in con.execute("SELECT id FROM vods WHERE status IN ('queued','processing')")]
    con.close()
    for vod_id in stuck:
        enqueue(vod_id)
