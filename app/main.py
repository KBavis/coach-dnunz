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

app = FastAPI(title="Coach dnunz")
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
    readings = db.VODS / vod_id / "readings.jsonl"
    if readings.exists() and any(s.get("game") is not None and "score" not in s for s in res["segments"]):
        from pipeline import segment
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
                                          timeouts=len(res.get("pauses", [])), game_time=round(played)))
    return _summaries[vod_id][1]


@app.get("/api/vods")
def list_vods():
    con = db.connect()
    rows = [dict(r) for r in con.execute("SELECT * FROM vods ORDER BY created_at DESC")]
    con.close()
    for r in rows:
        r["summary"] = _summary(r["id"]) if r["status"] == "ready" else None
    return rows


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
        at = live[0] + 20 if live else 60
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
    vod = _row(con, vod_id)
    if vod["status"] == "processing":
        raise HTTPException(409, "wait for processing to finish first")
    with con:
        con.execute("DELETE FROM vods WHERE id=?", (vod_id,))
    con.close()
    shutil.rmtree(db.VODS / vod_id, ignore_errors=True)   # symlinked sources are unlinked, not deleted
    return {"ok": True}


@app.get("/api/vods/{vod_id}/video")
def video(vod_id: str):
    path = jobs.video_path(vod_id)
    if path is None:
        raise HTTPException(404, "video missing")
    return FileResponse(path)          # Starlette serves HTTP Range requests, so seeking works


app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
