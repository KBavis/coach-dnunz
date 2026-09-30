"""Register an already-processed VOD without copying it.

    python -m app.import_vod <video> <segments.json> "<name>"

The video is symlinked into the library (deleting it from the app never deletes your original).
"""
import json, sys
from pathlib import Path

from . import db


def main(video, segments, name):
    video, segments = Path(video).resolve(), Path(segments).resolve()
    vod_id = db.new_id()
    d = db.VODS / vod_id
    d.mkdir(parents=True)
    (d / f"source{video.suffix.lower()}").symlink_to(video)
    (d / "segments.json").write_text(segments.read_text())
    duration = json.loads(segments.read_text()).get("duration", 0)
    con = db.connect()
    with con:
        con.execute("INSERT INTO vods (id, name, filename, status, stage, pct, duration, created_at) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (vod_id, name, video.name, "ready", "Done", 100, duration, db.now()))
    con.close()
    print("imported", vod_id)


if __name__ == "__main__":
    main(*sys.argv[1:4])
