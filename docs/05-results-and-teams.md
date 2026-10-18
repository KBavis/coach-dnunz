# 5. Results and "our team"

Code: `pipeline/banner.py`. Adds `result` to each round's segments and `our_side`, `final`,
`status` and `result` to each game.

Knowing the phases is half the job. A coach also wants to know which rounds and games were **won or
lost**, and that requires knowing **which team is "ours"**. The HUD shows only a left score and a
right score. This chapter is a good example of a signal that looks simple, turned out not to be, and
was only understood by looking at frames.

## Round results: the round-end banner

At each round end, Valorant shows a banner just below the HUD: **WON** on a green panel, **LOST** on
a red one, or a special win (**CLUTCH**, **FLAWLESS**, ACE, THRIFTY). It is drawn from the point of
view of the player on screen.

Reading it:

- **Where**: the word always sits in a box below the HUD (x 820, y 145, 280 x 120 at 1080p). Found
  by measuring the letters' bounding boxes on several real banners.
- **When**: from 6 s before to 8 s after the detected round end; the banner's timing relative to
  the HUD countdown varies by a second or two.
- **How**: recognition-only OCR on the box (no detector needed: the position is fixed). A cheap
  pre-check (two or more white blobs 45 to 85 px tall) skips OCR on frames without a banner.
- **Voting**: frames are read starting at the round end and working outwards; two agreeing reads
  settle it. Otherwise a clear majority wins, or the result stays unknown.
- **No extra decoding**: the HUD scan (chapter 2) already decodes every second of video; it crops
  the banner area too and keeps it only when the pre-check passes. VODs processed before that use a
  slower path that re-decodes the windows around each round end.

On the sample, banners were read for 38 to 39 of 46 rounds. Some round ends show no banner in the
window (spectator camera transitions, the HUD hidden).

## Which side is ours? The spectator problem

In a recording made from a player's own screen, the banner is always that player's team, so the
team side is easy: compare each banner with which score went up next round. A **WON** followed by
the left score rising means "our" team is on the left.

But the coach's recordings are **custom-game spectator recordings** ("SWITCH PLAYER" on screen):
the coach can switch to any player on either team, and the banner follows whoever is on screen.

What the data showed:

- Per game, the vote is usually lopsided toward the coach's own team: **15-2, 16-3, 17-1** banners.
- The 4 disagreeing banners in the first test were exactly the **CLUTCH / FLAWLESS** rounds the
  *enemy* won, seen from the enemy's view.
- In one game the coach mostly watched the enemy: only 8 banners were read, 6 for the wrong side.
  The vote picked the wrong team, and **every round W/L in that game was flipped**.

So the vote alone is not trustworthy. The final rules:

1. **Vote** over rounds (banner + which score rose), counting each round where both are known.
2. **Trust the vote only if it is clear**: at least 5 votes and a 75% majority. Otherwise the side
   is unknown and **no wins or losses are shown** for that game. Wrong colours are worse than none.
3. **The post-match screen overrides the vote** (next section).
4. **Round W/L** then comes from the score change and the known side. Where the score change is
   missing (often a game's last round), the round's banner is used, read relative to the team the
   banners mostly followed (`banner_side`), not assumed to be ours.

## Game results: the post-match screen

After a match, Valorant often shows a summary from the **recording account's** side: "13 DEFEAT 11"
or "13 VICTORY 5". That is exactly the missing information: whose team the recording is.

Reading it: full OCR (detector + recogniser; the layout varies) on the top centre of frames taken
every 2 s for 45 s after the game ends, looking for `<number> VICTORY|DEFEAT <number>`.

What went wrong first, and what that taught:

- **Custom games stopped by the host show "DRAW 0-0".** It carries no side information, so it is
  ignored. It turned out this coach view shows DRAW even after a real 5-13 finish.
- **A summary was misjudged as stale.** One game's summary said "13 VICTORY 5" while the computed
  final was 6-12. That looked like an old match left on screen. Looking at the HUD's last frames
  showed the game really ended **5-13** with a FLAWLESS banner for the right team; the 6-12 had come
  from trusting a banner seen from the enemy's view. The summary was right and the inference wrong.
- So a summary is accepted only if **its two numbers match the game's final score** (either order,
  tolerating OCR dropping a repeated digit: "11" read as "1"). Then VICTORY means our side is the
  higher score, DEFEAT the lower.

It appeared in 3 of the 7 games tested (others skipped straight to the next map, ended with someone
leaving, or the video ended). Where it appeared, it decided the side, and it corrected the game the
vote had flipped.

## The final score and unfinished games

The final score is the score going into the last round plus that round's winner, found in order of
reliability:

1. The round-end score already showing the bump.
2. If the game really ended (the video continues afterwards): the only result that **ends** a game
   (13+ with a 2-round lead). At 12-11, only "left wins" ends it, so the final is 13-11.
3. The last round's banner, interpreted with the known side.
4. Otherwise the score going into the last round.

Then:

- **Who wins**: whoever had more rounds at the end. That includes games the host stopped early
  (agreed rule: the team that was ahead).
- **Unfinished**: if the video ends within 20 s of the game's end **before anyone reached a winning
  score**, the result is unknown and shown without colour. Rule 2 deliberately does not apply here:
  when the video simply stops at 12-11, "a game-ending result" is no evidence of anything.

Checked against made-up cases (cut off at 7-5 and at 12-11 with and without a seen last round,
host-stopped ahead and behind, a normal finish) and the 7 real games, each confirmed against the HUD
and, where present, the summary screen.

> Lessons: (1) when a signal depends on a viewpoint (whose screen is this?), find a second signal
> with a fixed viewpoint (the account's own summary); (2) cross-validate signals against each other
> (summary numbers must match the HUD's final score); (3) prefer "unknown" to a confident wrong
> answer in anything a user will act on; (4) when a result looks wrong, look at the frames before
> deciding which signal to distrust. Here, the "stale" screen was right.
