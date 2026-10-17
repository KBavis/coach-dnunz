"""Start Coach Dnunz and open it in the browser.

    uv run python launch.py [--no-browser]     run in this terminal (start.sh does this)
    ... launch.py --prepare [--no-browser]     Windows start file: finish setup, create the
                                               "Coach Dnunz" shortcuts, start the tray app, exit
    ... launch.py --tray [--no-browser]        run in the background with an icon by the clock
                                               (what the shortcuts start, under pythonw.exe)

Picks a free port, finishes any first-run downloads, starts the web app and opens the page. If it
is already running, it just opens the page.
"""
import os, platform, shutil, socket, subprocess, sys, threading, time, urllib.request, webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get("COACH_DATA", ROOT / "data"))
LOG = DATA / "coach.log"               # the tray app's output (it has no window to print to)
PORT_FILE = DATA / "coach.port"        # where the running app listens, so a second start finds it
ICON = ROOT / "app" / "static" / "icon.ico"
HOST, PREFERRED_PORT = "127.0.0.1", int(os.environ.get("COACH_PORT", 8000))
WINDOWS = os.name == "nt"
NO_BROWSER = "--no-browser" in sys.argv


def say(msg):
    print(f"[coach] {msg}", flush=True)


def is_ours(port):
    """True if the app is already running on this port."""
    try:
        with urllib.request.urlopen(f"http://{HOST}:{port}/api/vods", timeout=1) as r:
            return r.status == 200
    except OSError:
        return False


def running_port():
    """The port of an instance that is already running, if any."""
    try:
        port = int(PORT_FILE.read_text())
        if is_ours(port):
            return port
    except (OSError, ValueError):
        pass
    return PREFERRED_PORT if is_ours(PREFERRED_PORT) else None


def free_port():
    for port in range(PREFERRED_PORT, PREFERRED_PORT + 50):
        with socket.socket() as s:
            if s.connect_ex((HOST, port)) != 0:
                return port
    raise SystemExit(f"No free port found between {PREFERRED_PORT} and {PREFERRED_PORT + 49}")


def url_for(port):
    return f"http://localhost:{port}"


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


def wait_until_up(port, seconds=60):
    for _ in range(seconds * 2):
        if is_ours(port):
            return True
        time.sleep(0.5)
    return False


def preflight():
    try:
        import onnxruntime  # noqa: F401
    except ImportError as e:
        if WINDOWS:
            raise SystemExit(
                "The OCR engine could not load. Install the Microsoft Visual C++ Redistributable from\n"
                "  https://aka.ms/vs/17/release/vc_redist.x64.exe\n"
                f"then double-click the start file again. (details: {e})")
        raise
    say("Checking ffmpeg (the first run downloads it, this can take a minute)...")
    import static_ffmpeg
    static_ffmpeg.add_paths()


def serve(port):
    """The web app on `port`, blocking until it stops. Returns the uvicorn server (for --tray)."""
    import uvicorn
    PORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    PORT_FILE.write_text(str(port))
    return uvicorn.Server(uvicorn.Config("app.main:app", host=HOST, port=port, log_level="warning"))


# ---------- run in this terminal ----------

def console():
    if (port := running_port()) is not None:
        say(f"Coach Dnunz is already running at {url_for(port)}")
        if not NO_BROWSER:
            open_browser(url_for(port))
        return
    preflight()
    port = free_port()
    if not NO_BROWSER:
        threading.Thread(target=lambda: wait_until_up(port) and open_browser(url_for(port)), daemon=True).start()
    say(f"Starting Coach Dnunz at {url_for(port)}")
    say("Keep this window open while you use the app. Close it (or press Ctrl+C) to stop.")
    serve(port).run()


# ---------- Windows: set up, then hand over to the tray app ----------

def pythonw():
    exe = Path(sys.executable)
    w = exe.with_name("pythonw.exe")
    return w if w.exists() else exe


def make_shortcuts():
    """"Coach Dnunz" on the Desktop and in the Start menu, starting the tray app. Recreated on
    every run of the start file, so they always point at this copy of the app."""
    ps = r"""
$ErrorActionPreference = 'Stop'
$shell = New-Object -ComObject WScript.Shell
$dirs = if ($env:COACH_SHORTCUT_DIR) { @($env:COACH_SHORTCUT_DIR) } else { @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs')) }
foreach ($dir in $dirs) {
  $link = $shell.CreateShortcut((Join-Path $dir 'Coach Dnunz.lnk'))
  $link.TargetPath = $env:COACH_TARGET
  $link.Arguments = '"' + $env:COACH_LAUNCH + '" --tray'
  $link.WorkingDirectory = $env:COACH_ROOT
  $link.IconLocation = $env:COACH_ICON
  $link.Description = 'Coach Dnunz: review Valorant VODs by round'
  $link.Save()
  Write-Output (Join-Path $dir 'Coach Dnunz.lnk')
}
"""
    env = dict(os.environ, COACH_TARGET=str(pythonw()), COACH_LAUNCH=str(ROOT / "launch.py"),
               COACH_ROOT=str(ROOT), COACH_ICON=str(ICON))
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                       capture_output=True, text=True, env=env, timeout=60)
    if r.returncode != 0:
        detail = r.stderr.strip().splitlines()[-1] if r.stderr.strip() else ""
        say(f"Could not create the desktop shortcut (the app still works). {detail}")
        return []
    return [line for line in r.stdout.splitlines() if line.strip()]


def prepare():
    if (port := running_port()) is not None:
        say(f"Coach Dnunz is already running at {url_for(port)}. Opening it.")
        if not NO_BROWSER:
            open_browser(url_for(port))
        return
    preflight()
    for path in make_shortcuts():
        say(f"Shortcut: {path}")
    say("Starting Coach Dnunz in the background...")
    PORT_FILE.unlink(missing_ok=True)
    args = [str(pythonw()), str(ROOT / "launch.py"), "--tray"] + (["--no-browser"] if NO_BROWSER else [])
    subprocess.Popen(args, cwd=ROOT, creationflags=0x00000008 | 0x00000200,   # detached, own process group
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(180):                  # until the tray app is answering (it writes its port first)
        time.sleep(0.5)
        if (port := running_port()) is not None:
            say(f"Coach Dnunz is running at {url_for(port)}")
            say("It keeps running in the background: look for its icon by the clock (it may be under the ^ arrow).")
            say("From now on, open it with the Coach Dnunz icon on your desktop or in the Start menu.")
            say("This window closes in a few seconds.")
            time.sleep(6)
            return
    say("Coach Dnunz did not start. The end of its log:")
    try:
        print("\n".join(LOG.read_text(errors="replace").splitlines()[-25:]))
    except OSError:
        pass
    raise SystemExit(1)


# ---------- the tray app ----------

def message_box(text):
    if WINDOWS:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, text, "Coach Dnunz", 0x10)


def tray():
    LOG.parent.mkdir(parents=True, exist_ok=True)
    if LOG.exists() and LOG.stat().st_size > 2_000_000:          # keep the log small
        LOG.replace(LOG.with_suffix(".log.1"))
    sys.stdout = sys.stderr = open(LOG, "a", buffering=1, encoding="utf-8", errors="replace")
    say(f"--- starting {time.strftime('%Y-%m-%d %H:%M:%S')}")
    if (port := running_port()) is not None:                     # a second click: just show the app
        if not NO_BROWSER:
            open_browser(url_for(port))
        return
    try:
        preflight()
    except SystemExit as e:
        message_box(str(e))
        raise
    import psutil, pystray
    from PIL import Image

    port = free_port()
    server = serve(port)
    threading.Thread(target=server.run, daemon=True).start()
    if not wait_until_up(port):
        message_box(f"Coach Dnunz could not start. Details are in:\n{LOG}")
        os._exit(1)
    say(f"Running at {url_for(port)}")
    if not NO_BROWSER:
        open_browser(url_for(port))

    def quit_app(icon=None, _item=None):
        say("Quitting")
        server.should_exit = True
        for child in psutil.Process().children(recursive=True):  # downloads and analyses in progress
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass
        PORT_FILE.unlink(missing_ok=True)
        if icon is not None:
            icon.stop()
        time.sleep(1)
        os._exit(0)

    def show_log(_icon=None, _item=None):
        if WINDOWS:
            os.startfile(LOG)

    icon = pystray.Icon("coach-dnunz", Image.open(ICON), "Coach Dnunz", menu=pystray.Menu(
        pystray.MenuItem("Open Coach Dnunz", lambda *_: open_browser(url_for(port)), default=True),
        pystray.MenuItem("Show log", show_log),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", quit_app)))

    def ready(icon):
        icon.visible = True
        say("Tray icon ready")
        try:
            icon.notify("Coach Dnunz is running. Click this icon to open it, or right-click to quit.", "Coach Dnunz")
        except Exception:                                       # notifications are a nice-to-have
            pass
        if os.environ.get("COACH_TRAY_AUTOQUIT"):               # tests: quit by itself after N seconds
            threading.Timer(float(os.environ["COACH_TRAY_AUTOQUIT"]), quit_app, args=(icon,)).start()

    icon.run(setup=ready)


def main():
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    if "--tray" in sys.argv:
        tray()
    elif "--prepare" in sys.argv and WINDOWS:
        prepare()
    else:
        console()


if __name__ == "__main__":
    main()
