"""Scan a VOD at a fixed fps and cache small crops of the top-center HUD.

Crops (1080p coordinates): round timer / spike icon, attacker score, defender score, plus the
round-result banner area below them, kept only for frames that look like they show a banner.
Output: <out>.npz with arrays timer, left, right (uint8 RGB), banner + banner_idx, and fps.

Decoding is most of the work, so the video is cut into chunks that a CPU decoder and, when
there is an NVIDIA GPU, a GPU decoder pull from a shared queue. Each keeps busy at its own speed:
on the dev machine the GPU decodes about half as fast as the CPU while using ~10x less CPU, so
together they finish sooner than either alone.
"""
import queue, subprocess, sys, shutil, threading
import numpy as np
import static_ffmpeg

from pipeline import banner as banner_mod

static_ffmpeg.add_paths()

# HUD strip: x 560..1360, y 0..265 (1080p), tall enough to include the round-result banner.
# Sub-crops are relative to the strip.
STRIP_X, STRIP_Y, STRIP_W, STRIP_H = 560, 0, 800, 265
TIMER = (330, 8, 140, 87)   # x, y, w, h within strip
LEFT = (230, 25, 70, 50)
RIGHT = (505, 25, 70, 50)
BANNER = (260, 145, 280, 120)   # the WON / LOST / CLUTCH word (see pipeline/banner.py)
TO_1080 = "scale=1920:1080:flags=bicubic"           # any resolution -> 1080p coordinates
CROP = f"crop={STRIP_W}:{STRIP_H}:{STRIP_X}:{STRIP_Y}"


def sub(a, box):
    x, y, w, h = box
    return a[y:y + h, x:x + w]


CHUNK = 300            # seconds of video per work unit


def command(video, fps, decoder="cpu", seconds=None, start=0):
    ff = [shutil.which("ffmpeg"), "-v", "error", "-nostdin"]
    if start:
        ff += ["-ss", str(start)]
    if decoder == "cuda":
        # decode on the GPU, but only copy the frames fps= keeps (a few a second) back to memory
        ff += ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"]
        vf = f"fps={fps},hwdownload,format=nv12,{TO_1080},{CROP}"
    else:
        vf = f"fps={fps},{TO_1080},{CROP}"
    if seconds:
        ff += ["-t", str(seconds)]
    return ff + ["-i", str(video), "-an", "-vf", vf, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]


def gpu_decode_works(video):
    """True if this machine can decode this video on an NVIDIA GPU (checked on its first 2 s)."""
    try:
        p = subprocess.run(command(video, 1, "cuda", seconds=2), capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return p.returncode == 0 and len(p.stdout) >= STRIP_W * STRIP_H * 3


def main(video, out, fps=1, on_progress=None, gpu=True, duration=None):
    """Decode `video` into HUD crops, chunk by chunk, on the CPU plus the GPU when it works."""
    if duration is None:
        raise ValueError("duration is needed to plan the chunks")
    decoders = ["cpu"] + (["cuda"] if gpu and gpu_decode_works(video) else [])
    print("decoders:", ", ".join(decoders), flush=True)
    total = int(duration * fps) + 2
    shapes = {k: (b[3], b[2], 3) for k, b in (("timer", TIMER), ("left", LEFT), ("right", RIGHT))}
    arrs = {k: np.zeros((total, *s), np.uint8) for k, s in shapes.items()}   # chunks fill their own rows
    chunks = queue.Queue()
    for c0 in range(0, int(duration) + 1, CHUNK):
        chunks.put(c0)
    filled = [0] * total
    done_s = [0.0]
    lock = threading.Lock()
    banners = {}                  # row -> banner crop, only for frames with banner-sized letters

    def decode(decoder):
        size = STRIP_W * STRIP_H * 3
        while True:
            try:
                c0 = chunks.get_nowait()
            except queue.Empty:
                return
            row0, rows = int(c0 * fps), int(CHUNK * fps)
            p = subprocess.Popen(command(video, fps, decoder, seconds=CHUNK, start=c0), stdout=subprocess.PIPE)
            n = 0
            while n < rows and row0 + n < total:
                buf = p.stdout.read(size)
                if len(buf) < size:
                    break
                a = np.frombuffer(buf, np.uint8).reshape(STRIP_H, STRIP_W, 3)
                r = row0 + n
                arrs["timer"][r], arrs["left"][r], arrs["right"][r] = sub(a, TIMER), sub(a, LEFT), sub(a, RIGHT)
                b = sub(a, BANNER)
                if banner_mod.has_word(b):
                    banners[r] = b.min(axis=2)          # grey is enough to read the word, 1/3 the memory
                filled[r] = 1
                n += 1
                if n % 30 == 0:
                    report(30)
            p.stdout.close()
            p.wait()
            if p.returncode not in (0, None) and n == 0 and decoder == "cuda":
                chunks.put(c0)                  # the GPU choked on this chunk: leave it to the CPU
                print("GPU decoder stopped, CPU continues", flush=True)
                return
            report(n % 30)

    def report(frames):
        with lock:
            done_s[0] += frames / fps
            if on_progress:
                on_progress(min(done_s[0], duration))

    threads = [threading.Thread(target=decode, args=(d,), daemon=True) for d in decoders]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    n = max((i + 1 for i, f in enumerate(filled) if f), default=0)
    if not n:
        raise SystemExit("No video frames could be read from this file")
    idx = sorted(i for i in banners if i < n)
    bw, bh = BANNER[2], BANNER[3]
    np.savez(out, timer=arrs["timer"][:n], left=arrs["left"][:n], right=arrs["right"][:n], fps=fps,
             banner_idx=np.array(idx, np.int32),
             banner=np.stack([banners[i] for i in idx]) if idx else np.zeros((0, bh, bw), np.uint8))
    print("banner candidates:", len(idx), flush=True)
    print("frames:", n, "missing:", n - sum(filled[:n]), flush=True)


if __name__ == "__main__":
    from pipeline.run import probe_duration
    main(sys.argv[1], sys.argv[2], duration=probe_duration(sys.argv[1]))
