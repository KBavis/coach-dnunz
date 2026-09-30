"""Turn per-second HUD readings into game segments.

Labels: NON_GAME, PRE_ROUND_n (buy phase), ROUND_n (live), POST_PLANT_n (spike icon
shown), ROUND_END_n (short post-round countdown).

HUD behaviour this relies on (observed on the sample VOD):
  buy phase   timer counts 0:30 -> 0:00
  live round  timer starts ~1:39; last ~15 s (if no plant) is a RED pill with decimals
  planted     spike icon replaces the timer
  round end   score +1 and a 0:06 -> 0:00 countdown, then the next buy phase (~0:28)
Timers are only ever read as M:SS. Decimal pills are never parsed; red ones are treated
as "still live", grey ones are reported as anomalies.
"""
import json, sys
import numpy as np

NON_GAME_GAP = 12      # seconds with no HUD evidence before we call it non-game
LIVE_START_MIN = 60    # a confirmed timer >= this in BUY means the round went live
BUY_START_MIN = 9      # post-round countdown never exceeds ~0:08, so >= this in ROUND_END = next buy phase
ROUND_END_MAX = 8      # a confirmed timer <= this while LIVE means the round ended


def load(path):
    rs = sorted((json.loads(l) for l in open(path)), key=lambda r: r["t"])
    for r in rs:
        m = r["timer"]
        r["s"] = int(m[0]) * 60 + int(m[2:]) if m else None
    return rs


def drop_isolated_decimals(rs):
    """A lone decimal-looking reading between two normal timers is OCR noise."""
    for k in range(1, len(rs) - 1):
        if rs[k]["decimal"] and rs[k - 1]["s"] is not None and rs[k + 1]["s"] is not None:
            rs[k]["decimal"] = False


def drop_short_spikes(rs, min_len=3):
    """A real plant shows the spike icon for many seconds; 1-2 sample blips are noise."""
    k = 0
    while k < len(rs):
        if rs[k]["spike"]:
            j = k
            while j + 1 < len(rs) and rs[j + 1]["spike"]:
                j += 1
            if j - k + 1 < min_len:
                for x in rs[k:j + 1]:
                    x["spike"] = False
            k = j + 1
        else:
            k += 1


def kind(r):
    if r["spike"]:
        return "spike"
    if r["decimal"]:
        return "dec"          # ignored by the state machine, never parsed as a time
    return "num" if r["s"] is not None else "none"


def has_hud(r):
    any_score = r["score_l"] is not None or r["score_r"] is not None
    return (kind(r) != "none" and any_score) or (r["score_l"] is not None and r["score_r"] is not None)


def split_runs(rs):
    """Return (runs, gaps): runs of samples with HUD, separated by >= NON_GAME_GAP of none."""
    runs, cur, miss = [], [], 0
    for r in rs:
        if has_hud(r):
            cur.append(r)
            miss = 0
        else:
            miss += 1
            if miss == NON_GAME_GAP and cur:
                runs.append(cur)
                cur = []
    if cur:
        runs.append(cur)
    return [r for r in runs if len(r) >= 20]


def stable_scores(run):
    """Per-sample (left, right) score: changes only by +1 and only once confirmed."""
    out = {}
    for side in ("score_l", "score_r"):
        vals = [r[side] for r in run]
        valid = [(i, v) for i, v in enumerate(vals) if v is not None]
        cur, res = None, []
        for i, v in enumerate(vals):
            ahead = [x for _, x in valid if _ >= i][:7]
            if cur is None:
                if ahead and ahead.count(v) >= 4 and v is not None:
                    cur = v
            elif v is not None and v == cur + 1 and ahead[:4] == [v] * 4:   # 4 readings in a row
                cur = v
            res.append(cur)
        out[side] = res
    return list(zip(out["score_l"], out["score_r"]))


def confirmed(run, i, s):
    """A timer reading is trusted if the next valid reading agrees with the countdown."""
    for j in range(i + 1, min(i + 6, len(run))):
        if run[j]["s"] is not None:
            return abs(run[j]["s"] - (s - (run[j]["t"] - run[i]["t"]))) <= 3
    return True


def segment_run(run, game_no):
    scores = stable_scores(run)
    first = next((sc for sc in scores if sc[0] is not None and sc[1] is not None), (0, 0))
    rnd = first[0] + first[1] + 1
    segs, phase, start, seg_round = [], None, run[0]["t"], rnd

    def switch(new, t):
        nonlocal phase, start, seg_round
        if phase is not None and t > start:
            segs.append(dict(game=game_no, phase=phase, round=seg_round, start=start, end=t))
        phase, start, seg_round = new, t, rnd

    seen_sum = sum(first)   # last score sum seen on screen (scores only, never the timer)
    expected = 0            # round ends already detected via the timer whose score bump is still to come
    for i, r in enumerate(run):
        k, s, t = kind(r), r["s"], r["t"]
        sc = scores[i]
        bump = 0
        if sc[0] is not None and sc[1] is not None and sc[0] + sc[1] > seen_sum:
            bump, seen_sum = sc[0] + sc[1] - seen_sum, sc[0] + sc[1]
        trusted = k == "num" and confirmed(run, i, s)

        if phase is None:                                    # first sample of the game
            if k == "spike":
                switch("POST_PLANT", t)
            elif trusted and s <= 45:
                switch("PRE_ROUND", t)
            elif trusted or k == "dec":
                switch("ROUND", t)
            continue

        if phase == "PRE_ROUND":
            if trusted and s >= LIVE_START_MIN:
                switch("ROUND", t)
        elif phase in ("ROUND", "POST_PLANT"):
            recent_spike = any(kind(run[j]) == "spike" for j in range(max(0, i - 2), i + 1))
            by_score = bump > 0 and expected == 0 and not recent_spike
            by_timer = trusted and (s <= ROUND_END_MAX if phase == "ROUND" else s <= 45)
            by_dec = phase == "POST_PLANT" and k == "dec"      # frozen readout after a plant = round over
            if bump and expected:
                expected -= min(bump, expected)
            if by_score or by_timer or by_dec:
                if by_timer and not by_score:
                    expected += 1
                switch("ROUND_END", t)
            elif phase == "ROUND" and k == "spike":
                switch("POST_PLANT", t)
        if phase == "ROUND_END" and trusted and s >= BUY_START_MIN and t > start - 1:
            if start != t or True:
                rnd += 1
                switch("PRE_ROUND" if s <= 45 else "ROUND", t)
    switch(None, run[-1]["t"])
    # the HUD lingers briefly after the last round; a tiny trailing buy phase is not real
    if segs and segs[-1]["phase"] == "PRE_ROUND" and segs[-1]["end"] - segs[-1]["start"] < 15:
        segs.pop()
    return segs


def build(rs):
    runs = split_runs(rs)
    segs, games = [], []
    prev_end = rs[0]["t"] if rs else 0
    for g, run in enumerate(runs, 1):
        if run[0]["t"] - prev_end > 1:
            segs.append(dict(game=None, phase="NON_GAME", round=None, start=prev_end, end=run[0]["t"]))
        gs = segment_run(run, g)
        segs += gs
        games.append(dict(game=g, start=run[0]["t"], end=gs[-1]["end"] if gs else run[-1]["t"],
                          rounds=len({s["round"] for s in gs})))
        prev_end = gs[-1]["end"] if gs else run[-1]["t"]
    if rs and rs[-1]["t"] - prev_end > 1:
        segs.append(dict(game=None, phase="NON_GAME", round=None, start=prev_end, end=rs[-1]["t"]))
    for s in segs:
        s["label"] = s["phase"] if s["round"] is None else f'{s["phase"]}_{s["round"]}'
    return segs, games


PAUSE_MIN = 5   # identical timer readings in a row (at 1 Hz) that count as a pause


def find_pauses(rs):
    out, k = [], 0
    while k < len(rs):
        j = k
        while j + 1 < len(rs) and rs[k]["s"] is not None and rs[j + 1]["s"] == rs[k]["s"] \
                and not rs[j + 1]["spike"]:
            j += 1
        if rs[k]["s"] is not None and j - k + 1 >= PAUSE_MIN:
            p = dict(start=rs[k]["t"], end=rs[j]["t"], timer=rs[k]["timer"])
            if out and out[-1]["timer"] == p["timer"] and p["start"] - out[-1]["end"] <= 4:
                out[-1]["end"] = p["end"]         # one pause interrupted by an OCR miss
            else:
                out.append(p)
        k = j + 1
    return out


def hms(t):
    t = int(t)
    return f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}"


def analyze(readings_path):
    rs = load(readings_path)
    drop_isolated_decimals(rs)
    drop_short_spikes(rs)
    pauses = find_pauses(rs)
    segs, games = build(rs)
    return dict(duration=(rs[-1]["t"] + 1) if rs else 0, games=games, segments=segs, pauses=pauses)


if __name__ == "__main__":
    readings, out = sys.argv[1:3]
    res = analyze(readings)
    json.dump(res, open(out, "w"), indent=1)
    for s in res["segments"]:
        print(f'{hms(s["start"])} - {hms(s["end"])}  {s["label"]:<14} ({s["end"] - s["start"]:.0f}s)')
    print("pauses:", [(hms(p["start"]), hms(p["end"]), p["timer"]) for p in res["pauses"]])
    print("games:", res["games"])
