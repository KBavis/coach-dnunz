"""Fast HUD digit reader: template matching instead of OCR (~0.3 ms vs ~700 ms per frame).

Valorant's HUD digits are white, a fixed size once the frame is scaled to 1080p, and sit on a
semi-transparent panel. So: keep near-white pixels, take connected blobs of digit height, and
compare each blob to an averaged template per digit. Anything unsure returns None, and the
caller falls back to OCR for just that field.

Templates come from OCR-labelled frames:  python -m pipeline.digits <hud.npz> <readings.jsonl>
"""
import json, re, sys
from pathlib import Path

import cv2
import numpy as np

GW, GH = 12, 20                                  # glyph size templates are compared at
SIZE = {"timer": (22, 29), "score": (16, 24)}    # digit height range in px (1080p crops)
THRESHOLDS = (200, 225, 245)                     # brighter backgrounds need a stricter "white"
MIN_SCORE, MIN_MARGIN = 0.80, 0.10               # correlation with the best digit, and lead over the 2nd
TEMPLATES = Path(__file__).with_name("digits.npz")
_tmpl = None


def templates():
    global _tmpl
    if _tmpl is None:
        with np.load(TEMPLATES) as d:
            _tmpl = {k: d[k] for k in d.files}
    return _tmpl


def glyphs(a, field, thr):
    hmin, hmax = SIZE[field]
    m = (a.min(axis=2) > thr).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    out = []
    for k in range(1, n):
        x, y, w, h, area = st[k]
        if hmin <= h <= hmax and w <= 20 and area >= 25:
            g = (lab[y:y + h, x:x + w] == k).astype(np.float32)
            out.append((x, cv2.resize(g, (GW, GH), interpolation=cv2.INTER_AREA).ravel()))
    out.sort(key=lambda t: t[0])
    return [g for _, g in out]


def _unit(v):
    v = v - v.mean()
    return v / (np.linalg.norm(v) + 1e-6)


def classify(gs, field):
    """Digits for the glyphs, or None if any of them is not a confident match."""
    s = templates()[field] @ np.stack([_unit(g) for g in gs]).T      # (10, n) correlations
    top = np.sort(s, axis=0)
    if top[-1].min() < MIN_SCORE or (top[-1] - top[-2]).min() < MIN_MARGIN:
        return None
    return "".join(str(int(d)) for d in s.argmax(axis=0))


def read(a, field, counts):
    """Read a crop. Returns (digits or None, saw_something) where saw_something means digit-sized
    white blobs were present, so an OCR fallback is worth trying."""
    saw = False
    for thr in THRESHOLDS:
        gs = glyphs(a, field, thr)
        saw = saw or bool(gs)
        if len(gs) in counts:
            txt = classify(gs, field)
            if txt is not None:
                return txt, True
    return None, saw


def timer(a):
    """'M:SS' for a normal timer, 'dec' for the 4-digit decimal pill (e.g. 31.67), else None."""
    txt, saw = read(a, "timer", (3, 4))
    if txt is None:
        return None, saw
    if len(txt) == 4:
        return "dec", True
    if int(txt[0]) > 2 or int(txt[1]) > 5:       # e.g. "1:67" when a blob of "31.67" was missed
        return None, True
    return f"{txt[0]}:{txt[1:]}", True


def score(a):
    txt, saw = read(a, "score", (1, 2))
    return (int(txt) if txt is not None else None), saw


def build(npz, readings, out=TEMPLATES):
    """Average glyphs from frames where OCR's reading has as many digits as blobs were found."""
    with np.load(npz) as f:
        d = {k: f[k] for k in ("timer", "left", "right")}  # decompress once, not per frame
    acc = {"timer": [[] for _ in range(10)], "score": [[] for _ in range(10)]}
    for line in open(readings):
        r = json.loads(line)
        for arr, key, field in (("timer", "timer", "timer"), ("left", "score_l", "score"), ("right", "score_r", "score")):
            if r[key] is None:
                continue
            ds = re.sub(r"\D", "", str(r[key]))
            gs = glyphs(d[arr][r["i"]], field, THRESHOLDS[0])
            if len(gs) == len(ds):
                for ch, g in zip(ds, gs):
                    acc[field][int(ch)].append(g)
    res = {}
    for field, per in acc.items():
        missing = [k for k in range(10) if not per[k]]
        if missing:
            raise SystemExit(f"no examples of digit(s) {missing} for {field}; use a longer VOD")
        res[field] = np.stack([_unit(np.mean(p, axis=0)) for p in per]).astype(np.float32)
        print(field, "examples per digit:", [len(p) for p in per])
    np.savez(out, **res)


if __name__ == "__main__":
    build(sys.argv[1], sys.argv[2])
