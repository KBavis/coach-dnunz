# Coach dnunz

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

- Drag and drop a video file, or paste a YouTube link.
- Detects games, rounds, and the phases inside each round: **Pre-round**, **Live round**,
  **Post-plant**, **Round end**, plus **Timeouts** and dead time between games.
- A viewer with a clickable timeline, per-round jump buttons, a "now viewing" bar, and a saved,
  renameable library.

Not done yet:

- **Transcription and speaker labels.** The panel in the viewer is a placeholder.
- **Speed.** Detection currently takes roughly 4x real time (about 30 minutes for a 1h45m VOD),
  because it runs OCR on the CPU several times per frame. A cheaper way of reading the digits is
  the obvious next fix.
- **Wider testing.** It has only been checked against one stream. It expects Valorant's default
  observer/spectator HUD at the top centre, and other layouts or resolutions may misread.

## Run

    uv venv && uv pip install -e .
    uv run uvicorn app.main:app --port 8000      # then open http://localhost:8000

Drag a recording onto the page, or paste a YouTube link. Detection runs in the background and
the VOD stays in your library afterwards; click a name's pencil to rename it.

Recording tip for future sessions: in OBS you can record the mic, Discord, and game audio as
separate tracks inside one file. That will make transcription and speaker separation far
easier than one mixed track.

## How it works

1. `ffmpeg` decodes the video and crops the small HUD strip at the top centre.
2. OCR reads the round timer and both scores about once a second.
3. A state machine turns those readings into segments. The timer counts down in the buy phase,
   restarts at about 1:40 when the round goes live, gets replaced by a spike icon after a
   plant, and a short countdown plus a score change marks the round end. A timer that stays
   frozen for several seconds is a timeout.
4. Noisy readings are cleaned up along the way, for example by requiring a score change to be
   seen several times in a row before believing it.

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
that template matching works better, is the reason that's the planned speed fix here (this
project currently uses general-purpose OCR). No code was copied from it.
