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
    for g in result["games"]:
        votes = Counter()
        ks = [k for k in keys if k[0] == g["game"]]
        for a, b in zip(ks, ks[1:]):
            sa, sb, res = rounds[a][0].get("score"), rounds[b][0].get("score"), outcome[a]
            if not res or not sa or not sb or None in sa or None in sb:
                continue
            dl, dr = sb[0] - sa[0], sb[1] - sa[1]
            if dl + dr != 1:
                continue
            winner = "l" if dl else "r"
            votes[winner if res == "win" else ("r" if winner == "l" else "l")] += 1
        if votes:
            side, n = votes.most_common(1)[0]
            g["our_side"] = side
            g["side_votes"] = dict(votes)
    return result


def main(video, work):
    path = Path(work) / "segments.json"
    result = add_results(video, json.loads(path.read_text()))
    path.write_text(json.dumps(result))
    found = Counter(s.get("result") for s in result["segments"] if s["game"] is not None and s["phase"] == "ROUND_END")
    print("results:", dict(found), "| our side per game:", {g["game"]: g.get("our_side") for g in result["games"]})


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
