"""Read timer / scores / spike icon from cached HUD crops (see extract_hud.py).

Timer is parsed strictly as M:SS. Decimal-style readings (e.g. 10.33) are never
converted to a timer; they are flagged as `decimal` for review.
"""
import json, re, sys
from multiprocessing import Pool
import cv2
import numpy as np

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


DATA = {}  # loaded once in the parent before forking; workers share it copy-on-write


def to_int(s):
    digits = re.sub(r"\D", "", s or "")   # OCR sometimes adds stray dots, e.g. '.2'
    return int(digits) if digits else None


def work(i):
    timer, left, right = DATA["timer"][i], DATA["left"][i], DATA["right"][i]
    spike = is_spike(timer)
    raw = None if spike else read_text(timer, valid_timer)
    t, dec = parse_timer(raw)
    digit = lambda s: re.sub(r"\D", "", s) != "" and len(re.sub(r"\D", "", s)) <= 2
    l = read_text(left, digit)
    r = read_text(right, digit)
    return dict(i=i, spike=spike, timer_raw=raw, timer=t, decimal=dec,
                score_l=to_int(l), score_r=to_int(r))


def main(npz, out, workers=6, on_progress=None):
    """Results are appended to `out` (JSON lines) as they finish; reruns resume."""
    d = np.load(npz)
    fps = float(d["fps"])
    for k in ("timer", "left", "right"):
        DATA[k] = d[k]          # decompress each array exactly once
    done = set()
    try:
        done = {json.loads(l)["i"] for l in open(out)}
    except FileNotFoundError:
        pass
    idx = [i for i in range(0, len(DATA["timer"]), STEP) if i not in done]
    print("todo", len(idx), "already done", len(done), flush=True)
    with Pool(workers) as p, open(out, "a") as f:
        for n, r in enumerate(p.imap_unordered(work, idx, chunksize=8)):
            r["t"] = r["i"] / fps
            f.write(json.dumps(r) + "\n")
            if n % 50 == 0:
                f.flush()
                print(n, "/", len(idx), flush=True)
                if on_progress:
                    on_progress(n + len(done), n + len(done) + len(idx) - n)
    print("done", flush=True)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 6)
