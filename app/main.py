"""Local web app: drag-and-drop a VOD, watch it get processed, browse it by round.

    uv run uvicorn app.main:app --port 8000     (then open http://localhost:8000)
"""
import json, re, shutil, subprocess
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db, jobs, setup

app = FastAPI(title="Coach Dnunz")


@app.middleware("http")
async def _revalidate(request, call_next):
    """Make browsers check for a newer page/script/stylesheet on every load (an unchanged file is
    a quick 304), so an update never runs new HTML against a cached old app.js or style.css."""
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-cache"
    return response
STATIC = Path(__file__).parent / "static"
ALLOWED = {".mp4", ".mkv", ".mov", ".webm"}
YOUTUBE = re.compile(r"^https?://((www|m|music)\.)?(youtube\.com|youtu\.be)/", re.I)


@app.on_event("startup")
def _startup():
    db.connect().close()
    jobs.start()


def _row(con, vod_id):
    row = con.execute("SELECT * FROM vods WHERE id=?", (vod_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "no such VOD")
    return dict(row)


_summaries: dict = {}     # vod id -> (segments.json mtime, summary)


def _result(vod_id):
    """segments.json, upgraded in place if it predates per-segment scores and readings exist."""
    seg = db.VODS / vod_id / "segments.json"
    if not seg.exists():
        return None
    res = json.loads(seg.read_text())
    from pipeline import segment
    before = len(res["games"])
    if len(segment.drop_restarts(res)["games"]) != before:      # remakes in an older breakdown
        seg.write_text(json.dumps(res))
    readings = db.VODS / vod_id / "readings.jsonl"
    if readings.exists() and any(s.get("game") is not None and "score" not in s for s in res["segments"]):
        new = segment.analyze(str(readings))
        new["duration"] = max(new["duration"], res.get("duration", 0))
        seg.write_text(json.dumps(new))
        res = new
    return res


def _summary(vod_id):
    """Games / rounds / timeouts for a library card, cached until segments.json changes."""
    seg = db.VODS / vod_id / "segments.json"
    try:
        mtime = seg.stat().st_mtime
    except FileNotFoundError:
        return None
    if vod_id not in _summaries or _summaries[vod_id][0] != mtime:
        res = json.loads(seg.read_text())
        rounds = {(s["game"], s["round"]) for s in res["segments"] if s["game"] is not None}
        played = sum(s["end"] - s["start"] for s in res["segments"] if s["game"] is not None)
        _summaries[vod_id] = (mtime, dict(games=len(res["games"]), rounds=len(rounds),
                                          timeouts=len(res.get("pauses", [])), game_time=round(played),
                                          results=[g.get("result") for g in res["games"]]))
    return _summaries[vod_id][1]


@app.get("/api/config")
def config():
    return {"parallel": jobs.ANALYSES, "downloads": jobs.DOWNLOADS}


@app.get("/api/vods")
def list_vods():
    con = db.connect()
    rows = [dict(r) for r in con.execute("SELECT * FROM vods ORDER BY created_at DESC")]
    con.close()
    for r in rows:
        r["summary"] = _summary(r["id"]) if r["status"] == "ready" else None
        r["updated"] = _updated(r["id"])
    return rows


def _updated(vod_id):
    """When the breakdown last changed, so an open viewer notices background updates."""
    try:
        return (db.VODS / vod_id / "segments.json").stat().st_mtime
    except FileNotFoundError:
        return None


@app.get("/api/vods/{vod_id}/thumb.jpg")
def thumb(vod_id: str):
    """A frame from the first live round (or a minute in), made once and cached."""
    out = db.VODS / vod_id / "thumb.jpg"
    if not out.exists():
        video = jobs.video_path(vod_id)
        if video is None:
            raise HTTPException(404, "no video yet")
        res = _result(vod_id)
        live = [s["start"] for s in (res or {}).get("segments", []) if s["phase"] == "ROUND"]
        con = db.connect()
        length = con.execute("SELECT duration FROM vods WHERE id=?", (vod_id,)).fetchone()
        con.close()
        at = live[0] + 20 if live else min(60, (length["duration"] if length else 0) * 0.3 or 60)
        setup.add_tool_paths()
        subprocess.run([shutil.which("ffmpeg"), "-v", "error", "-y", "-ss", str(at), "-i", str(video),
                        "-frames:v", "1", "-vf", "scale=480:-2", "-q:v", "4", str(out)],
                       capture_output=True, timeout=60)
        if not out.exists():
            raise HTTPException(404, "could not make a thumbnail")
    return FileResponse(out, headers={"Cache-Control": "max-age=86400"})


@app.post("/api/vods")
async def upload(file: UploadFile):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED:
        raise HTTPException(400, f"unsupported file type {ext or '(none)'}; use {', '.join(sorted(ALLOWED))}")
    vod_id = db.new_id()
    d = db.VODS / vod_id
    d.mkdir(parents=True)
    with open(d / f"source{ext}", "wb") as out:
        while chunk := await file.read(4 * 1024 * 1024):
            out.write(chunk)
    con = db.connect()
    with con:
        con.execute("INSERT INTO vods (id, name, filename, status, created_at) VALUES (?,?,?,?,?)",
                    (vod_id, Path(file.filename).stem, file.filename, "queued", db.now()))
    con.close()
    jobs.enqueue(vod_id)
    return {"id": vod_id}


class FromUrl(BaseModel):
    url: str


@app.post("/api/vods/from-url")
def from_url(body: FromUrl):
    url = body.url.strip()
    if not YOUTUBE.match(url):
        raise HTTPException(400, "Paste a youtube.com or youtu.be link")
    vod_id = db.new_id()
    (db.VODS / vod_id).mkdir(parents=True)
    con = db.connect()
    with con:
        con.execute("INSERT INTO vods (id, name, filename, status, created_at, source_url) VALUES (?,?,?,?,?,?)",
                    (vod_id, url, url, "queued", db.now(), url))
    con.close()
    jobs.enqueue(vod_id)
    return {"id": vod_id}


@app.get("/api/vods/{vod_id}")
def detail(vod_id: str):
    con = db.connect()
    vod = _row(con, vod_id)
    con.close()
    vod["result"] = _result(vod_id)
    vod["updated"] = _updated(vod_id)
    return vod


class Rename(BaseModel):
    name: str


@app.patch("/api/vods/{vod_id}")
def rename(vod_id: str, body: Rename):
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "name cannot be empty")
    con = db.connect()
    _row(con, vod_id)
    with con:
        con.execute("UPDATE vods SET name=? WHERE id=?", (name, vod_id))
    con.close()
    return {"ok": True}


@app.post("/api/vods/{vod_id}/reprocess")
def reprocess(vod_id: str):
    con = db.connect()
    _row(con, vod_id)
    con.close()
    d = db.VODS / vod_id
    for f in ("segments.json", "readings.jsonl", "progress.json", "hud.npz", "thumb.jpg"):
        (d / f).unlink(missing_ok=True)
    jobs.enqueue(vod_id)
    return {"ok": True}


@app.delete("/api/vods/{vod_id}")
def delete(vod_id: str):
    con = db.connect()
    _row(con, vod_id)
    with con:
        con.execute("DELETE FROM vods WHERE id=?", (vod_id,))   # first, so a running job sees it is gone
    con.close()
    jobs.cancel(vod_id)                     # stops a download or analysis that is still running
    shutil.rmtree(db.VODS / vod_id, ignore_errors=True)   # symlinked sources are unlinked, not deleted
    return {"ok": True}


@app.get("/api/vods/{vod_id}/video")
def video(vod_id: str):
    path = jobs.video_path(vod_id)
    if path is None:
        raise HTTPException(404, "video missing")
    return FileResponse(path)          # Starlette serves HTTP Range requests, so seeking works


app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
