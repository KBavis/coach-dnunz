# Coach Dnunz: technical docs

How Coach Dnunz turns a multi-hour Valorant recording into games, rounds and phases in a couple of
minutes, and why it is built the way it is. Written for developers, and as a reference for future
computer-vision-on-video projects: each chapter ends with the lessons that carry over.

> Just want to use the app? See **[SETUP.md](../SETUP.md)** (plain-language Windows guide). The
> top-level **[README](../README.md)** is the short technical summary.

## Chapters

1. **[Overview](01-overview.md)**: the problem, the architecture, and the life of one VOD.
2. **[Reading video fast](02-reading-video.md)**: ffmpeg, sampling, cropping, CPU + GPU decoding,
   and the measurements behind every choice.
3. **[Reading the HUD](03-reading-the-hud.md)**: why general OCR was too slow, template matching,
   the fallback design, and validating against ground truth (25 minutes to 16 seconds).
4. **[From readings to rounds](04-readings-to-rounds.md)**: cleaning noisy per-second readings and
   the state machine that turns them into games, rounds, phases and timeouts.
5. **[Results and "our team"](05-results-and-teams.md)**: round banners, the post-match screen,
   and working out which team is being watched in spectator recordings.
6. **[The app](06-the-app.md)**: FastAPI, the job pools, process isolation, progress, and the
   frontend.
7. **[Packaging and Windows](07-packaging-and-windows.md)**: uv, the launcher, the tray app, and the
   Windows-only bugs found by testing on a fresh machine.
8. **[Lessons and a playbook](08-lessons-and-playbook.md)**: what to do first on the next project,
   mistakes made here, and a checklist.

## Numbers used throughout

Measured on the development machine (AMD Ryzen 7 7800X3D, 8 cores / 16 threads, NVIDIA RTX 5080,
WSL2 on Windows 11) with one sample VOD: a 1h45m (6,370 s) 1080p60 H.264 custom-game recording.

| | Before | After |
|---|---|---|
| Reading the HUD (timer + scores, 6,370 frames) | ~25 min | **16 s** |
| Whole pipeline for the 1h45m VOD | ~30 min | **~2.5 min** |
| Peak memory per analysis | ~1 GB | **~0.5 GB** |
| Idle app (server running, nothing to do) | | ~90 MB, ~0.1% of one core |

"Same result" checks in these docs compare against the original OCR-only output on that VOD:
same games, same 46 rounds, same 161 segments, same 7 timeouts.
