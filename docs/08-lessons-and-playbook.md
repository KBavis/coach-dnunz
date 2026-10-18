# 8. Lessons and a playbook

What carries over from this project to the next "extract events from video" project, whether that
is another game, a sports broadcast, a lab camera, or screen recordings.

## The approach, in order

1. **Find the cheapest reliable signal.** Before any model, look for what the video already tells
   you in a fixed place: a HUD, scoreboard, clock, status text, colour cue. Here a few small crops of
   the HUD replaced "understanding Valorant".
2. **Get a correct, slow baseline first.** General OCR on every frame took ~25 minutes for a 1h45m
   video, but it was right often enough to produce the ground truth for everything after.
3. **Persist the intermediate representation.** Per-second readings (`readings.jsonl`) made the
   segmenter and results steps re-runnable in under a second, and made background upgrades of old
   data possible.
4. **Build the regression harness before optimising.** Here: re-segment and diff games, rounds,
   segments, boundaries and pauses against the baseline. Every speed-up was accepted only if that
   diff stayed clean.
5. **Profile, then attack the biggest cost.** OCR first (0.72 s per frame), then decoding once OCR
   was cheap. The bottleneck moves; re-measure after every change.
6. **Fast path that knows when it is unsure, plus a targeted fallback.** Template matching with a
   confidence and margin threshold, and OCR only for in-game frames it could not read.
7. **Encode domain invariants.** Scores rise by one, countdowns fall by one per second, a plant
   lasts many seconds, a game ends at 13 with a two-round lead. They remove most noise and resolve
   ambiguous cases.
8. **Cross-check independent signals.** Score changes vs round banners vs the post-match screen.
   Where they disagree, look at frames before deciding which one is wrong.
9. **Prefer "unknown" to a confident wrong answer** in anything the user acts on.

## Techniques worth reusing

| Technique | Where | Payoff |
|---|---|---|
| ffmpeg `fps` + `scale` + `crop` to a raw pipe | scan | only the needed pixels reach Python; one coordinate system for any resolution |
| Shared chunk queue across CPU and GPU decoders | scan | +23% on one VOD; adapts to any hardware |
| Template matching on connected components | digits | ~2,000x faster than OCR |
| Slow model labels data for the fast one | templates | no hand labelling |
| Confidence + margin thresholds, "unsure" output | digits | wrong reads become fallbacks, not errors |
| Context gating and neighbour inference before fallback | reader | OCR on 1,248 of 6,370 frames, none in dead time |
| Recognition-only OCR on a known box | fallback | 16x faster than detect + recognise |
| Majority vote with a confidence floor | team side | robust to spectator camera switching |
| Atomic progress files + polling | app | simple, crash-safe progress reporting |
| Subprocess per heavy job + memory guard | app | the server survives any job failure |
| Versioned derived data + background upgrades | app | new features apply to old VODs automatically |

## Mistakes made here (so you do not repeat them)

- **Assuming instead of looking.** A post-match screen was dismissed as stale because its numbers
  disagreed with a computed score; the frames showed the computation was wrong. Several bugs were
  only understood by rendering frames: the spectator banners, the remake games, a misread
  "1:67".
- **An optimisation that made things slower.** The first two-pass reader ran OCR on more frames
  than before (10.5 vs 4.5 minutes). Only measuring each step caught it.
- **Trusting a fallback without measuring its hit rate.** Full OCR as the last resort succeeded on
  0 of 109 frames it was tried on.
- **Speed tweaks that changed the input.** Skipping the deblocking filter was 30% faster and changed
  18% of readings. Always check output, not just time.
- **Platform assumptions.** Deleting an open file works on Linux, not on Windows; console programs
  started from a windowless process open windows. Found only by testing a fresh Windows setup.
- **UI states conflated.** "Could not reach the server yet" was rendered as "empty library".
- **Timing of derived data.** A score read at the start of a phase can lag the event that changed
  it; reading it once the phase was underway fixed missing results.

## A checklist for the next video project

Before writing code:

- [ ] What on screen already states the thing I want? Where exactly (in a fixed coordinate system)?
- [ ] How often does it change? (Sets the sampling rate.)
- [ ] What are the invariants (monotonic counters, durations, ordering)?
- [ ] What does a "golden" recording look like, and how will I diff against it?

First version:

- [ ] Slow but correct reader on sampled, cropped frames.
- [ ] Save the per-frame readings.
- [ ] A segmenter or state machine with explicit cleaning passes.
- [ ] A structural diff against a golden recording.

Then make it fast:

- [ ] Profile wall time **and** CPU time per stage.
- [ ] Specialised fast reader (templates, colour checks) that outputs "unsure".
- [ ] Gate the slow fallback by context; measure its hit rate.
- [ ] Decoding: crop early, check hardware decoding as an *additional* worker, chunk the work.

Then make it usable:

- [ ] Separate download and compute pools; subprocesses for heavy work.
- [ ] Per-step progress the user can understand.
- [ ] "Unknown" states instead of guesses.
- [ ] One-command setup, tested on a clean machine of the target OS.

## Where this project could go next

- **Transcription and speaker labels** (the original plan): local speech-to-text per round, with
  voice chat and game audio on separate tracks (OBS can record them separately).
- **Notes per round**: the viewer is laid out so a note can attach to "game 2, round 7,
  post-plant, 0:12".
- **More layouts**: broadcast overlays and non-1080p sources would need their own crop boxes and
  templates; the template builder (`python -m pipeline.digits`) makes adding a layout mostly a
  matter of one labelled recording.
- **Faster decoding**: keyframe-only decoding at 0.5 fps for the gaps between games, or reading only
  around detected events at full rate.
