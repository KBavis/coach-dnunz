# Coach Dnunz

> **Setting it up to use it, not to work on it?** Follow **[SETUP.md](SETUP.md)**: plain-language
> steps for Windows, no technical knowledge needed.

A local-first Valorant VOD reviewer, built to help a friend who coaches. A match recording is
split into games, rounds and the phases inside each round (buy phase, live, post-plant, round
end), with timeouts, the score and each round's result, so a coach can jump straight to the
moment they want to review. Everything runs on one machine: no cloud, no accounts.

It is also a learning project: reading a game's HUD out of video (template matching, OCR, and
state machines over noisy readings), GPU-assisted decoding, and, next, local speech-to-text.

## Status

Works on the streams it has been tested on (player POV and custom-game spectator recordings with
Valorant's default HUD):

- Add video files and YouTube links; up to 3 downloads and 2 analyses run at once, in the order
  added, with per-step progress.
- Detects games, rounds and phases, timeouts, dead time and remade games; reads the score,
  each round's WON / LOST banner and the post-match screen, and works out which team is being
  watched, so rounds and games show won / lost.
- A searchable library and a round-centred viewer (round list with W/L, phase buttons, a round
  clock on the game's own timer, skip dead time).

Speed on the dev machine (Ryzen 7 7800X3D + RTX 5080, WSL): a 1h45m VOD takes about 2.5 minutes
end to end. A YouTube video also has to download first (about 7 GB for 3 hours at 1080p60).

Not done yet: transcription and speaker labels, notes per round, and testing on broadcast
overlays and non-1080p layouts (720p sources read noticeably worse).

## Running it

`start.bat` (Windows) and `start.sh` (WSL, Linux, macOS) install [uv](https://docs.astral.sh/uv/)
if missing, then `uv run --extra engine python launch.py`, which installs Python 3.12 and the
dependencies, fetches ffmpeg, picks a free port from 8000 and opens the browser. Both scripts
pass their arguments on (`--no-browser`).

Developer equivalent:

    uv run --extra engine python launch.py --no-browser
    uv run --extra engine uvicorn app.main:app --port 8000      # without the launcher

The Windows script keeps its own environment in `.venv-windows`, so one checkout can be run from
both Windows and WSL. Python is pinned to 3.12 (`.python-version`; `rapidocr-onnxruntime` has no
3.13 build). The heavy dependencies (OCR, OpenCV, yt-dlp, deno) are the `engine` extra.

### Settings (environment variables)

| Variable | Default | Effect |
|---|---|---|
| `COACH_PORT` | 8000 | First port the launcher tries |
| `COACH_DATA` | `./data` | Library location (database and per-VOD folders) |
| `COACH_DOWNLOADS` | 3 | YouTube downloads at once |
| `COACH_PARALLEL` | 2 | Analyses at once |
| `COACH_GPU` | 1 | `0` disables NVIDIA GPU decoding |
| `COACH_WORKERS` | set per job | OCR worker processes per analysis |
| `MIN_MB` | min(4000, 10% of RAM) | Free-memory floor; a job below it is killed |

## How it works

Processing one VOD (`python -m pipeline.run <video> <workdir>`, run by the app as its own
process so a crash or memory spike cannot take the server down):

1. **Scan** (`pipeline/extract_hud.py`): ffmpeg decodes the video at 1 fps, scaled to 1080p
   coordinates, cropping the HUD strip (timer, both scores) and the round-result banner area.
   The video is cut into 5-minute chunks pulled from a shared queue by a CPU decoder and, when
   one works, an NVIDIA GPU decoder; the GPU is slower than a fast CPU alone but uses ~10x less
   CPU, so together they finish sooner. Banner crops are kept only for frames with letter-sized
   white blobs.
2. **Read** (`pipeline/read_hud.py`, `pipeline/digits.py`): digits are read by matching white
   glyph blobs against averaged templates (`pipeline/digits.npz`, about 0.3 ms per frame). Frames
   near confident readings that still miss a field get recognition-only OCR on the digit box;
   gaps the neighbouring seconds settle (a countdown, an unchanged score) are filled in.
3. **Segment** (`pipeline/segment.py`): a state machine over the readings: the buy phase counts
   down from ~0:30, the round goes live at ~1:40, a spike icon replaces the timer after a plant,
   and a short countdown plus a score change ends the round. A timer frozen for 5+ s is a
   timeout. Score changes need several readings in a row. A game of at most 4 rounds followed by
   a fresh 0-0 game is a remake and becomes dead time.
4. **Results** (`pipeline/banner.py`): the WON / LOST / CLUTCH / FLAWLESS / ACE / THRIFTY banner
   at each round end is read by OCR, voting over the seconds around it. Per game, banners are
   matched against which score went up to find which HUD side is the watched team (a majority
   vote, since spectator recordings sometimes show an enemy player; a weak vote leaves the side
   unknown and no W/L is shown). Each round's W/L then comes from the score change, or from its
   banner where the score did not show it.
5. **Game results** (`pipeline/banner.py`): the post-match VICTORY / DEFEAT screen is read after
   each game; when its numbers match the final score it is the recording account's own result
   and decides the team (it beats the banner vote). A game goes to whoever had more rounds at the
   end, including one the host stopped early. A game the video cuts off before a winning score is
   `unfinished` and has no result.

Rebuilding the digit templates from an OCR-labelled VOD:
`python -m pipeline.digits <hud.npz> <readings.jsonl>`.

### The web app

- `launch.py`: port selection, first-run checks, opens the browser.
- `app/main.py`: FastAPI. `GET/POST /api/vods`, `POST /api/vods/from-url`,
  `GET/PATCH/DELETE /api/vods/{id}`, `POST /api/vods/{id}/reprocess`, `GET /api/vods/{id}/video`
  (range requests), `GET /api/vods/{id}/thumb.jpg`, `GET /api/config`. Static files are served
  with `Cache-Control: no-cache`.
- `app/jobs.py`: a download pool (yt-dlp) and an analysis pool (oldest first), each job a
  subprocess with a memory guard; deleting a VOD cancels its running job. VODs processed before
  round results existed get them in the background at startup.
- `app/db.py`: SQLite library (`data/library.db`).
- `app/static/`: plain HTML/CSS/JS frontend, no build step.

### Data

Each VOD's row in `data/library.db` also stores when the match was played (`recorded_at`,
`recorded_kind`): the stream start or publish date from YouTube, or for a file the recording time
in its metadata, else the file's date on the computer it came from.

Each VOD lives in `data/vods/<id>/`: `source.<ext>` (the video), `segments.json` (the
breakdown), `readings.jsonl` (per-second HUD readings), `run.log`, `progress.json` and
`thumb.jpg`. `data/` and `vods/` are git-ignored; never commit them.

`segments.json`: `duration`, `games` (`game`, `start`, `end`, `rounds`, `our_side`, `final` as
`[left, right]`, `status` = `finished` / `unfinished`, `result` = `win` / `loss`),
`segments` (`game`, `round`, `phase` = `PRE_ROUND` / `ROUND` / `POST_PLANT` / `ROUND_END` /
`NON_GAME`, `start`, `end`, `score` as `[left, right]`, `result` = `win` / `loss` / null),
and `pauses` (`start`, `end`, `timer`).

To register an already-processed VOD without copying it:
`python -m app.import_vod <video> <segments.json> "<name>"`.

## Layout

- `pipeline/`: scanning, HUD reading, segmentation, round results
- `app/`: FastAPI backend, job pools, SQLite library, static frontend
- `launch.py`, `start.sh`, `start.bat`, `start.ps1`: one-command start
- `SETUP.md`: non-technical setup guide

Recording tip: in OBS you can record the mic, Discord and game audio as separate tracks in one
file, which will make transcription and speaker separation far easier later.

## Credits

The idea of a phase state machine over HUD readings was informed by
[Valoscribe](https://github.com/SphinxNumberNine/valoscribe), an MIT-licensed tool that does
this for pro broadcast footage. Its note that generic OCR struggles on Valorant's font, and
that template matching works better, is why this project reads digits by template matching.
No code was copied from it.
