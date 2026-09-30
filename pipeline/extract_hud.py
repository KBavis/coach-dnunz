"""Scan a VOD at a fixed fps and cache small crops of the top-center HUD.

Crops (1080p coordinates): round timer / spike icon, attacker score, defender score.
Output: <out>.npz with arrays timer, left, right (uint8 RGB) and fps.
"""
import subprocess, sys, shutil
import numpy as np
import static_ffmpeg

static_ffmpeg.add_paths()

# HUD strip: x 560..1360, y 0..110 (1080p). Sub-crops are relative to the strip.
STRIP_X, STRIP_Y, STRIP_W, STRIP_H = 560, 0, 800, 110
TIMER = (330, 8, 140, 87)   # x, y, w, h within strip
LEFT = (230, 25, 70, 50)
RIGHT = (505, 25, 70, 50)


def sub(a, box):
    x, y, w, h = box
    return a[y:y + h, x:x + w]


def main(video, out, fps=2, on_progress=None):
    cmd = [shutil.which("ffmpeg"), "-v", "error", "-i", video,
           "-vf", f"fps={fps},scale=1920:1080:flags=bicubic,crop={STRIP_W}:{STRIP_H}:{STRIP_X}:{STRIP_Y}",   # any resolution -> 1080p coordinates
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    size = STRIP_W * STRIP_H * 3
    timer, left, right = [], [], []
    while True:
        buf = p.stdout.read(size)
        if len(buf) < size:
            break
        a = np.frombuffer(buf, np.uint8).reshape(STRIP_H, STRIP_W, 3)
        timer.append(sub(a, TIMER).copy())
        left.append(sub(a, LEFT).copy())
        right.append(sub(a, RIGHT).copy())
        if len(timer) % 200 == 0:
            print(len(timer) / fps, "s", flush=True)
            if on_progress:
                on_progress(len(timer) / fps)
    p.wait()
    if not timer:
        raise SystemExit("No video frames could be read from this file")
    np.savez_compressed(out, timer=np.stack(timer), left=np.stack(left),
                        right=np.stack(right), fps=fps)
    print("frames:", len(timer))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
