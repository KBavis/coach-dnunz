"""Read timer / scores / spike icon from cached HUD crops (see extract_hud.py).

Timer is parsed strictly as M:SS. Decimal-style readings (e.g. 10.33) are never
converted to a timer; they are flagged as `decimal` for review.
"""
import json, re, sys
from multiprocessing import Pool
import cv2
import numpy as np

from pipeline import digits

STEP = 2  # use every 2nd cached frame (cache is 2 fps -> 1 fps readings)
_ocr = None


def ocr():
    global _ocr
    if _ocr is None:
        from rapidocr_onnxruntime import RapidOCR
        _ocr = RapidOCR(intra_op_num_threads=1, inter_op_num_threads=1)
    return _ocr


def variants(a):
    big = cv2.resize(a, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    yield big
    g = cv2.cvtColor(big, cv2.COLOR_RGB2GRAY)
    g = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(4, 4)).apply(g)
    yield cv2.cvtColor(g, cv2.COLOR_GRAY2RGB)
    # keep only near-white pixels (the digit fill), drop bright-but-coloured background
    mask = (big.min(axis=2) > 215).astype(np.uint8) * 255
    yield cv2.cvtColor(255 - mask, cv2.COLOR_GRAY2RGB)


def read_text(a, valid):
    for v in variants(a):
        r, _ = ocr()(v)
        if r:
            txt = "".join(x[1] for x in r).replace(" ", "")
            if valid(txt):
                return txt
    return None


TIMER_RE = re.compile(r"^\d:\d\d$")


def parse_timer(txt):
    if txt is None:
        return None, False
    if re.search(r"\d\.\d", txt):
        return None, True                       # decimal format: flag, never parse
    t = txt.replace(";", ":").replace(".", ":")
    if re.fullmatch(r"\d{3}", t):
        t = f"{t[0]}:{t[1:]}"
    return (t, False) if TIMER_RE.match(t) else (None, False)


def is_spike(timer_crop):
    r, g, b = (timer_crop[..., i].astype(int) for i in range(3))
    return int(((r > 170) & (g < 70) & (b < 70)).sum()) > 250


def valid_timer(t):
    return parse_timer(t)[0] is not None or re.search(r"\d\.\d", t) is not None


def to_int(s):
    ds = re.sub(r"\D", "", s or "")   # OCR sometimes adds stray dots, e.g. '.2'
    return int(ds) if ds else None


CONTEXT = 10   # frames (s): a frame this close to a confident HUD reading is inside a game


def fast(i, timer, left, right):
    """Pass 1: template matching only (pipeline/digits.py), well under a millisecond a frame."""
    spike = is_spike(timer)
    t, dec = None, False
    if not spike:
        t, _ = digits.timer(timer)
        if t == "dec":
            t, dec = None, True
    return dict(i=i, spike=spike, timer_raw=t, timer=t, decimal=dec,
                score_l=digits.score(left)[0], score_r=digits.score(right)[0], ocr=0)


def secs(m):
    return int(m[0]) * 60 + int(m[2:]) if m else None


def infer(rs, order):
    """Settle what the neighbours make obvious, so OCR is only spent where it adds information.

    Timer: one missing reading between a known one before and after that agree (counting down by
    one a second, or frozen in a timeout) is filled in. Score: a missing score between equal
    neighbours (within 30 s) takes that value, since scores only change at round end."""
    pos = {i: k for k, i in enumerate(order)}
    get = lambda k: rs.get(order[k]) if 0 <= k < len(order) else None
    for i in order:
        r = rs.get(i)
        if r is None:
            continue
        k = pos[i]
        a, b = get(k - 1), get(k + 1)
        if not r["spike"] and r["timer"] is None and not r["decimal"] and a and b and a["timer"] and b["timer"]:
            sa, sb = secs(a["timer"]), secs(b["timer"])
            if sa - sb in (0, 2):
                s_ = (sa + sb) // 2
                r["timer"] = r["timer_raw"] = f"{s_ // 60}:{s_ % 60:02d}"
                r["filled"] = True
        for side in ("score_l", "score_r"):
            if r[side] is None:
                before = next((x[side] for x in (get(j) for j in range(k - 1, k - 31, -1)) if x and x[side] is not None), None)
                after = next((x[side] for x in (get(j) for j in range(k + 1, k + 31)) if x and x[side] is not None), None)
                if before is not None and before == after:
                    r[side] = before
                    r["filled"] = True


def needs_ocr(r):
    return (not r["spike"] and r["timer"] is None and not r["decimal"]) or r["score_l"] is None or r["score_r"] is None


def work(item):
    """Pass 2: OCR just the fields templates could not read."""
    # crops travel with each task, so this works with both fork (Linux) and spawn (Windows) pools
    r, timer, left, right = item
    digit = lambda s: re.sub(r"\D", "", s) != "" and len(re.sub(r"\D", "", s)) <= 2
    if not r["spike"] and r["timer"] is None and not r["decimal"]:
        r["timer_raw"] = read_text(timer, valid_timer)
        r["timer"], r["decimal"] = parse_timer(r["timer_raw"])
        r["ocr"] += 1
    for side, crop in (("score_l", left), ("score_r", right)):
        if r[side] is None:
            r[side] = to_int(read_text(crop, digit))
            r["ocr"] += 1
    return r


def main(npz, out, workers=6, on_progress=None):
    """Results are appended to `out` (JSON lines) as they finish; reruns resume.

    Pass 1 reads every frame with templates. Pass 2 runs OCR only on frames near confident HUD
    readings that still miss a field, so dead time (menus, lobby, the stream intro) costs nothing."""
    d = np.load(npz)
    fps = float(d["fps"])
    timer, left, right = d["timer"], d["left"], d["right"]   # decompress each array exactly once
    done = set()
    try:
        done = {json.loads(l)["i"] for l in open(out)}
    except FileNotFoundError:
        pass
    every = list(range(0, len(timer), STEP))
    total = len(every)
    rs = {i: fast(i, timer[i], left[i], right[i]) for i in every if i not in done}
    seen = [i for i in every if i in rs and (rs[i]["spike"] or rs[i]["timer"] or rs[i]["decimal"]
                                            or rs[i]["score_l"] is not None or rs[i]["score_r"] is not None)]
    near = set()
    for i in seen:
        near.update(range(i - CONTEXT * STEP, i + CONTEXT * STEP + 1, STEP))
    infer(rs, every)
    todo = [i for i in rs if i in near and needs_ocr(rs[i])]
    pending = set(todo)
    print("frames", len(rs), "already done", len(done), "need OCR", len(todo), flush=True)
    with open(out, "a") as f:
        for i, r in rs.items():
            if i not in pending:
                r["t"] = i / fps
                f.write(json.dumps(r) + "\n")
        f.flush()
        if on_progress:
            on_progress(total - len(todo), total)
        if todo:
            with Pool(workers) as p:
                items = ((rs[i], timer[i], left[i], right[i]) for i in todo)
                for n, r in enumerate(p.imap_unordered(work, items, chunksize=4)):
                    r["t"] = r["i"] / fps
                    f.write(json.dumps(r) + "\n")
                    if n % 20 == 0:
                        f.flush()
                        if on_progress:
                            on_progress(total - len(todo) + n, total)
    print("done", flush=True)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 6)
