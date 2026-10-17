"""Start Coach Dnunz and open it in the browser.

    uv run python launch.py [--no-browser]       (start.sh / start.bat do this for you)

Picks a free port, finishes any first-run downloads, starts the web app and opens the page.
"""
import os, platform, shutil, socket, subprocess, sys, threading, time, urllib.request, webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HOST, PREFERRED_PORT = "127.0.0.1", int(os.environ.get("COACH_PORT", 8000))


def say(msg):
    print(f"[coach] {msg}", flush=True)


def is_ours(port):
    """True if the app is already running on this port."""
    try:
        with urllib.request.urlopen(f"http://{HOST}:{port}/api/vods", timeout=1) as r:
            return r.status == 200
    except OSError:
        return False


def free_port():
    for port in range(PREFERRED_PORT, PREFERRED_PORT + 50):
        with socket.socket() as s:
            if s.connect_ex((HOST, port)) != 0:
                return port
    raise SystemExit(f"No free port found between {PREFERRED_PORT} and {PREFERRED_PORT + 49}")


def open_browser(url):
    if "microsoft" in platform.release().lower():          # WSL: open the Windows browser
        if shutil.which("wslview"):
            subprocess.Popen(["wslview", url])
            return
        if shutil.which("cmd.exe"):
            subprocess.Popen(["cmd.exe", "/c", "start", "", url], cwd="/mnt/c" if os.path.isdir("/mnt/c") else None,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
    if not webbrowser.open(url):
        say(f"Could not open a browser automatically. Open {url} yourself.")


def open_when_ready(url, port):
    for _ in range(120):
        if is_ours(port):
            open_browser(url)
            return
        time.sleep(0.5)
    say(f"The app is taking a while to start. Try opening {url} yourself.")


def preflight():
    try:
        import onnxruntime  # noqa: F401
    except ImportError as e:
        if os.name == "nt":
            raise SystemExit(
                "The OCR engine could not load. Install the Microsoft Visual C++ Redistributable from\n"
                "  https://aka.ms/vs/17/release/vc_redist.x64.exe\n"
                f"then run start.bat again. (details: {e})")
        raise
    say("Checking ffmpeg (the first run downloads it, this can take a minute)...")
    import static_ffmpeg
    static_ffmpeg.add_paths()


def main():
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    if is_ours(PREFERRED_PORT):
        url = f"http://localhost:{PREFERRED_PORT}"
        say(f"Coach Dnunz is already running at {url}")
        if "--no-browser" not in sys.argv:
            open_browser(url)
        return
    preflight()
    port = free_port()
    url = f"http://localhost:{port}"
    import uvicorn
    if "--no-browser" not in sys.argv:
        threading.Thread(target=open_when_ready, args=(url, port), daemon=True).start()
    say(f"Starting Coach Dnunz at {url}")
    say("Keep this window open while you use the app. Close it (or press Ctrl+C) to stop.")
    uvicorn.run("app.main:app", host=HOST, port=port, log_level="warning")


if __name__ == "__main__":
    main()
