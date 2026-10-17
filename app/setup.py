"""First-run setup state. For now everything is installed by the start scripts, so it is always ready."""
import threading

import static_ffmpeg

READY = threading.Event()
READY.set()


def add_tool_paths():
    static_ffmpeg.add_paths()      # downloads ffmpeg on first use, then just puts it on PATH
