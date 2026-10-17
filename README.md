# Coach Dnunz

A fun hobby project, built to help a friend who coaches Valorant.

His coaching sessions are long recordings, and the useful parts (a specific round, the moment
after a spike plant, a timeout where the team talked strategy) are buried in them. This tool
chops a VOD into rounds and phases so he can jump straight to the part he wants to review.

It is also a **learning project**. The goal is as much to understand how the pieces work as to
ship something polished:

- **OCR and reading a video**: pulling the round timer and scores out of the game's HUD, and
  learning why generic OCR struggles on a game font and what to do about it (template matching,
  cleaning up noisy readings, state machines over time).
- **Transcription** *(next)*: speech-to-text with local, free models, and working out who is
  speaking when (speaker diarization), including game audio bleeding into voice chat.
- **Building it local-first**: no cloud, no accounts. Everything runs on one machine.

## Status

Works today, on one sample stream:

- Add several videos and YouTube links at once; they download and process side by side.
- Detects games, rounds, and the phases inside each round: **Buy phase**, **Live**,
  **Post-plant**, **Round end**, plus **Timeouts**, dead time between games, and the score.
- A searchable library with thumbnails, and a viewer built around rounds: pick a game and round
  on the right (with the score and which side took it), then jump between its buy phase, live
  round, post-plant and round end under the video.

Not done yet:

- **Transcription and speaker labels.** The panel in the viewer is a placeholder.
- **Speed.** A 1h45m VOD takes about 2.5 minutes end to end on the dev machine (Ryzen 7800X3D +
  NVIDIA GPU), down from about 30. Decoding the video is now most of it: the CPU and, when there
  is one, an NVIDIA GPU decode chunks side by side. Digits are read by template matching, with a
  fast recognition-only OCR fallback. Up to 3 YouTube downloads and 2 analyses run at once
  (`COACH_DOWNLOADS`, `COACH_PARALLEL`; `COACH_GPU=0` turns the GPU off).
- **Wider testing.** It has only been checked against one stream. It expects Valorant's default
  observer/spectator HUD at the top centre, and other layouts or resolutions may misread.

## Run

One step, no setup. The first start downloads everything it needs (Python, libraries, ffmpeg),
which takes a few minutes. Later starts take seconds.

- **Windows:** double-click `start.bat`.
- **WSL, Linux or macOS:** run `./start.sh` in a terminal.

Your browser opens on the app. Keep the window that opened alongside it running while you use
the app, and close it to stop. Nothing needs to be installed beforehand: the script installs
[uv](https://docs.astral.sh/uv/), which brings the right Python version and every dependency
with it. If port 8000 is busy, the app picks the next free port.

If Windows says the OCR engine could not load, install the
[Microsoft Visual C++ Redistributable](https://aka.ms/vs/17/release/vc_redist.x64.exe) and
start it again.

For developers: `uv run python launch.py --no-browser`, or `uv run uvicorn app.main:app --port 8000`.

Click **Add VODs** (or drop video files anywhere on the page) and paste YouTube links one per
line. Progress shows under "In progress", and each VOD joins the library when it is ready.
Press `/` to search, `[` and `]` to step through rounds, `1`-`4` to jump to a round's phases, and
click a VOD's name to rename it.

Recording tip for future sessions: in OBS you can record the mic, Discord, and game audio as
separate tracks inside one file. That will make transcription and speaker separation far
easier than one mixed track.

## How it works

1. `ffmpeg` decodes the video and crops the small HUD strip at the top centre.
2. The round timer and both scores are read about once a second, by matching the white digit
   shapes against templates (`pipeline/digits.py`). OCR only runs on in-game frames the
   templates could not read, and gaps the neighbouring seconds make obvious are filled in.
3. A state machine turns those readings into segments. The timer counts down in the buy phase,
   restarts at about 1:40 when the round goes live, gets replaced by a spike icon after a
   plant, and a short countdown plus a score change marks the round end. A timer that stays
   frozen for several seconds is a timeout.
4. Noisy readings are cleaned up along the way, for example by requiring a score change to be
   seen several times in a row before believing it.
5. Round results come from the WON / LOST banner shown at each round end (`pipeline/banner.py`),
   read from the same scan. Matching banners against which score went up tells which side of the
   HUD is the team being watched, so wins and losses need no setup.

The detection code runs as a separate process, so a crash or a runaway memory spike can't take
the web app down.

## Layout

- `pipeline/`: frame extraction, HUD reading (OCR), and the segmentation state machine
  (`python -m pipeline.run <video> <workdir>`)
- `app/`: FastAPI backend, SQLite library, and the static frontend
- `data/` and `vods/`: your videos and results (git-ignored, never commit these)

To add an already-processed VOD without copying it:
`python -m app.import_vod <video> <segments.json> "<name>"`.

## Credits

The idea of a phase state machine over HUD readings was informed by
[Valoscribe](https://github.com/SphinxNumberNine/valoscribe), an MIT-licensed tool that does
this for pro broadcast footage. Its note that generic OCR struggles on Valorant's font, and
that template matching works better, is why this project reads digits by template matching.
No code was copied from it.
