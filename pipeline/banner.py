"""Read the round-result banner Valorant shows at each round end: WON / LOST, or a special win
(CLUTCH, FLAWLESS, ACE, THRIFTY). It is shown from the side of the player on screen, so it
says whether that player's team won. Comparing it with which HUD score went up, over all rounds,
tells which side of the HUD the team being watched is on. (A spectator recording sometimes shows
an enemy player, so single rounds can disagree; the majority decides.)

    python -m pipeline.banner <video> <workdir>     (adds results to <workdir>/segments.json)
"""
import json, re, shutil, subprocess, sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import numpy as np
import static_ffmpeg

static_ffmpeg.add_paths()

from pipeline import read_hud  # noqa: E402

BOX = (820, 145, 280, 120)                 # x, y, w, h of the banner word at 1080p
WIN = ("WON", "CLUTCH", "FLAWLESS", "ACE", "THRIFTY")
LOSS = ("LOST",)
WINDOW = (-6, 8)                           # seconds around the round end to look for the banner


def classify(text):
    t = re.sub(r"[^A-Z]", "", (text or "").upper())
    if any(w in t for w in LOSS):
        return "loss"
    if any(w in t for w in WIN):
        return "win"
    return None


def has_word(crop):
    """Cheap check before OCR: at least two white letter-sized blobs (banner letters are ~55-75 px).
    Takes an RGB crop or a grey one (the per-pixel minimum over RGB, as the scan stores it)."""
    if crop.shape[0] < 85:
        return False
    m = ((crop.min(axis=2) if crop.ndim == 3 else crop) > 215).astype(np.uint8)
    n, _, st, _ = cv2.connectedComponentsWithStats(m)
    return sum(1 for x in st[1:] if 45 <= x[3] <= 85 and 10 <= x[2] <= 60 and x[4] >= 300) >= 2


def read(crop):
    """Recognition-only OCR on the banner word (no text detector needed: it is always here)."""
    if not has_word(crop):
        return None
    if crop.ndim == 2:
        crop = cv2.cvtColor(crop, cv2.COLOR_GRAY2RGB)
    for v in read_hud.variants(crop):
        r, _ = read_hud.ocr()(v, use_det=False, use_cls=False)
        txt = "".join(x[0] for x in r or [])
        if classify(txt):
            return classify(txt)
    return None


def frames(video, t0, t1):
    """Banner crops once a second between t0 and t1."""
    x, y, w, h = BOX
    cmd = [shutil.which("ffmpeg"), "-v", "error", "-nostdin", "-ss", str(max(0, t0)), "-t", str(t1 - max(0, t0)),
           "-i", str(video), "-an", "-vf", f"fps=1,scale=1920:1080:flags=bicubic,crop={w}:{h}:{x}:{y}",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    raw = subprocess.run(cmd, capture_output=True, timeout=120).stdout
    n = len(raw) // (w * h * 3)
    return [np.frombuffer(raw, np.uint8, w * h * 3, i * w * h * 3).reshape(h, w, 3) for i in range(n)]


def round_result(video, end_at, saved=None):
    """saved: {second: crop} from the HUD scan, so nothing is decoded twice. Without it the
    window around the round end is decoded again (for VODs processed before banners were kept)."""
    if saved is not None:
        crops = [saved.get(int(end_at) + d) for d in range(WINDOW[0], WINDOW[1])]
        crops = [c if c is not None else np.zeros((1, 1, 3), np.uint8) for c in crops]
    else:
        crops = frames(video, end_at + WINDOW[0], end_at + WINDOW[1])
    mid = -WINDOW[0]                                          # start at the round end, work outwards
    order = sorted(range(len(crops)), key=lambda i: abs(i - mid))
    votes = Counter()
    for i in order:
        v = read(crops[i])
        if v:
            votes[v] += 1
            if votes[v] >= 2 and votes[v] > sum(votes.values()) - votes[v]:
                return v                                      # two agreeing reads is enough
    if not votes:
        return None
    best, n = votes.most_common(1)[0]
    return best if n > sum(votes.values()) - n else None     # a clear majority, or nothing


def add_results(video, result, workers=4, saved=None):
    """Set `result` ("win" / "loss" for the team being watched) on each round's segments, and
    `our_side` ("l" / "r", the HUD score that is theirs) on each game where it can be told."""
    rounds = {}
    for s in result["segments"]:
        if s["game"] is not None:
            rounds.setdefault((s["game"], s["round"]), []).append(s)
    keys = sorted(rounds, key=lambda k: rounds[k][0]["start"])
    # the banner appears when the round is decided: at the round end, or the last phase's end
    ends = [next((s["start"] for s in rounds[k] if s["phase"] == "ROUND_END"), rounds[k][-1]["end"]) for k in keys]
    with ThreadPoolExecutor(workers) as pool:
        outcome = dict(zip(keys, pool.map(lambda t: round_result(video, t, saved), ends)))
    for k in keys:
        for s in rounds[k]:
            s["result"] = outcome[k]
    # which HUD side is the watched team: the side whose score goes up in the rounds they win
    def score(k):                       # read once the round is live: the previous result has settled
        return next((x["score"] for x in rounds[k] if x["phase"] == "ROUND"), rounds[k][0].get("score"))
    for g in result["games"]:
        votes = Counter()
        ks = [k for k in keys if k[0] == g["game"]]
        for a, b in zip(ks, ks[1:]):
            sa, sb, res = score(a), score(b), outcome[a]
            if not res or not sa or not sb or None in sa or None in sb:
                continue
            dl, dr = sb[0] - sa[0], sb[1] - sa[1]
            if dl + dr != 1:
                continue
            winner = "l" if dl else "r"
            votes[winner if res == "win" else ("r" if winner == "l" else "l")] += 1
        g.pop("our_side", None)
        g["side_votes"] = dict(votes)
        if votes:
            side, n = votes.most_common(1)[0]
            g["banner_side"] = side           # whose view the round banners mostly showed
            if sum(votes.values()) >= SIDE_MIN_VOTES and n / sum(votes.values()) >= SIDE_MIN_SHARE:
                g["our_side"], g["side_from"] = side, "banners"
        game_outcome(video, result, g, [k for k in keys if k[0] == g["game"]], rounds, score, outcome)
    result["results_version"] = RESULTS_VERSION
    return result


# A side is only trusted when the banners agree clearly; otherwise wins and losses are not shown
SIDE_MIN_VOTES, SIDE_MIN_SHARE = 5, 0.75
RESULTS_VERSION = 2          # bump to have older breakdowns re-read in the background
SUMMARY_BOX = (480, 0, 960, 420)    # top centre of the 1080p frame: where the end screens put the word
SUMMARY_WINDOW = 45                 # seconds after a game ends to look for its VICTORY / DEFEAT screen


def summary_screen(video, game_end):
    """(word, [a, b]) from the post-match screen ("13 DEFEAT 11"), or None. Full OCR here: the
    screen's layout varies, and it is only a few frames per game."""
    x, y, w, h = SUMMARY_BOX
    cmd = [shutil.which("ffmpeg"), "-v", "error", "-nostdin", "-ss", str(game_end), "-t", str(SUMMARY_WINDOW),
           "-i", str(video), "-an", "-vf", f"fps=0.5,scale=1920:1080,crop={w}:{h}:{x}:{y},scale={w // 2}:{h // 2}",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    raw = subprocess.run(cmd, capture_output=True, timeout=180).stdout
    size = (w // 2) * (h // 2) * 3
    for i in range(len(raw) // size):
        frame = np.frombuffer(raw, np.uint8, size, i * size).reshape(h // 2, w // 2, 3)
        res, _ = read_hud.ocr()(frame)
        text = " ".join(t[1] for t in res or []).upper()
        m = re.search(r"(\d{1,2})\s*(VICTORY|DEFEAT)\s*(\d{1,2})", text)
        if m:
            return m.group(2), [int(m.group(1)), int(m.group(3))]
    return None


def game_outcome(video, result, g, ks, rounds, score, outcome):
    """Set on game `g`: `final` [left, right], `status` ("finished" / "unfinished"), and when the
    watched team's side is known, `result` ("win" / "loss": whoever had more rounds at the end).

    A VICTORY / DEFEAT screen whose numbers match the final score is the recording account's own
    result, so it decides the side (it beats the banner vote). A game the video cuts off has no
    result. A game the host stopped early goes to whoever was ahead."""
    if not ks:
        return
    going_in = score(ks[-1])
    if not going_in or None in going_in:
        return
    gl, gr = going_in
    # the last round's winner: the round-end score when it already shows it, else the one result
    # that ends a game (13+ with a 2-round lead), else the last round's banner once the side is known
    end_score = next((x.get("score") for x in rounds[ks[-1]] if x["phase"] == "ROUND_END"), None)
    over = lambda a, b: max(a, b) >= 13 and abs(a - b) >= 2
    # cut off: the video ends during the game before anyone reached a winning score
    cut_off = result.get("duration", 0) - g["end"] <= 20
    final = None
    if end_score and None not in end_score and sum(end_score) == gl + gr + 1:
        final = list(end_score)
    elif not cut_off:                     # the game really ended, so only a game-ending result fits
        ends_game = [c for c in ([gl + 1, gr], [gl, gr + 1]) if over(*c)]
        if len(ends_game) == 1:
            final = ends_game[0]
    g["status"] = "finished" if not cut_off or (final and over(*final)) else "unfinished"
    if g["status"] == "finished":
        seen = summary_screen(video, g["end"])
        candidates = [final] if final else [[gl + 1, gr], [gl, gr + 1], [gl, gr]]
        match = seen and next((c for c in candidates if _same_score(seen[1], c)), None)
        if match:
            final = match
            word = seen[0]
            higher = "l" if final[0] > final[1] else "r"
            g["our_side"] = higher if word == "VICTORY" else ("r" if higher == "l" else "l")
            g["side_from"] = "summary"
    if final is None:                                   # host stopped it, or the last round is unknown
        res, side = outcome.get(ks[-1]), g.get("our_side")
        if res and side:
            won_by_l = (res == "win") == (side == "l")
            final = [gl + 1, gr] if won_by_l else [gl, gr + 1]
        else:
            final = [gl, gr]
    if g["status"] == "unfinished" and over(*final):
        g["status"] = "finished"                        # the last round's banner shows it did end
    g["final"] = final
    g.pop("result", None)
    side = g.get("our_side")
    if g["status"] == "finished" and side and final[0] != final[1]:
        ours, theirs = (final[0], final[1]) if side == "l" else (final[1], final[0])
        g["result"] = "win" if ours > theirs else "loss"


def _same_score(read, final):
    """The screen's two numbers match the final score (in either order), allowing OCR to drop a
    repeated digit (11 read as 1)."""
    def close(a, b):
        return a == b or (b >= 10 and str(a) in str(b))
    a, b = read
    return (close(a, final[0]) and close(b, final[1])) or (close(a, final[1]) and close(b, final[0]))


def main(video, work):
    path = Path(work) / "segments.json"
    result = add_results(video, json.loads(path.read_text()))
    path.write_text(json.dumps(result))
    found = Counter(s.get("result") for s in result["segments"] if s["game"] is not None and s["phase"] == "ROUND_END")
    print("results:", dict(found), "| our side per game:", {g["game"]: g.get("our_side") for g in result["games"]})


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
