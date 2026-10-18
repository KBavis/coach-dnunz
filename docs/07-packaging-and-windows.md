# 7. Packaging and Windows

Code: `start.bat`, `start.ps1`, `start.sh`, `launch.py`, `pyproject.toml`, `uv.lock`.

The goal: a non-technical person on Windows downloads a ZIP, double-clicks one file, and gets a
working app and a desktop icon, with nothing installed beforehand. This chapter covers how, and
the bugs that only a real fresh Windows run revealed.

## uv does the heavy lifting

[uv](https://docs.astral.sh/uv/) installs a pinned Python and every dependency from `uv.lock` in
seconds, with no admin rights and no pre-installed Python. The start scripts only have to get uv:

```
start.bat  ->  start.ps1  ->  (install uv if missing)  ->  uv run --extra engine python launch.py --prepare
start.sh   ->              (install uv if missing)  ->  uv run --extra engine python launch.py
```

Choices that mattered:

- **Python pinned to 3.12** (`.python-version`, `requires-python = ">=3.12,<3.13"`): the OCR package
  has no 3.13 build. Without the pin, a Windows machine would pick a newer Python and fail to install.
- **Dependencies split**: a small core (FastAPI, uvicorn, psutil, static-ffmpeg; on Windows also
  pystray and Pillow) and an `engine` extra (NumPy, OpenCV, RapidOCR/ONNX Runtime, yt-dlp, deno).
- **Everything as Python packages**: ffmpeg comes from `static-ffmpeg` (downloads the right build
  on first use), the JavaScript runtime yt-dlp needs for YouTube from the `deno` package. Nothing
  else to install.
- **`.venv-windows`** for the Windows environment, so one checkout can be run from both Windows and
  WSL without the two fighting over `.venv`.
- **`.gitattributes`** forces CRLF for `.bat`/`.ps1` and LF for `.sh`; batch files with Unix line
  endings misbehave in `cmd.exe`, and GitHub's ZIP download respects these attributes.

## The launcher's three modes

`launch.py`:

- **default** (terminal): preflight (ONNX Runtime loads, ffmpeg present), pick a free port from
  8000, write it to `data/coach.port`, start uvicorn, open the browser once the API answers.
- **`--prepare`** (what `start.bat` runs): preflight, create the shortcuts, start the tray app as a
  detached process, wait until it answers, then exit so the console closes. If it does not come up,
  print the end of its log and stay open.
- **`--tray`** (what the shortcuts run): under `pythonw.exe`, so there is no console. Output goes to
  `data/coach.log`; a fatal error shows a Windows message box; a pystray icon offers Open, Show log,
  Quit.

Starting a second time finds the running instance through `data/coach.port` and just opens the
browser, so clicking the desktop icon twice is harmless.

### Shortcuts

Created with PowerShell's `WScript.Shell` COM object (no extra dependency): "Coach Dnunz.lnk" on the
Desktop (`[Environment]::GetFolderPath('Desktop')`, which follows OneDrive-redirected desktops) and
in the Start menu, targeting `.venv-windows\Scripts\pythonw.exe "launch.py" --tray` with the app
icon. Recreated on every run of the start file, so after moving the folder or updating, running the
start file once fixes the icon.

### No console windows

A process without a console (`pythonw.exe`) that starts a console program (ffmpeg, yt-dlp,
`python.exe`) makes Windows open a **new visible console window** for it, on every chunk and every
download. The fix:

- Start child processes with `CREATE_NO_WINDOW`. The child gets a hidden console, and **everything it
  starts inherits that hidden console**, so grandchildren (ffmpeg under the pipeline, deno under
  yt-dlp) need no special handling.
- Start Python children with `python.exe`, not `pythonw.exe`, so they have that console to pass on.

Verified by listing every process with a visible window before and during processing a file and a
YouTube VOD from the tray app: no new windows.

### Quitting

Quit stops uvicorn, kills the process tree of running jobs (with psutil) and removes the port file.
Interrupted jobs resume on the next start. Idle, the app uses ~90 MB and ~0.1% of one core.

## Testing a "fresh machine" without one

The developer's Windows machine already had uv installed. To test the real first-run path, the test
ran the GitHub-style ZIP in a temporary folder with:

- `USERPROFILE`, `UV_INSTALL_DIR`, `UV_CACHE_DIR`, `UV_PYTHON_INSTALL_DIR` pointing inside it, so uv,
  Python and every download start from empty;
- uv hidden from `PATH` and `UV_NO_MODIFY_PATH=1`, so the installer runs but does not touch the
  user's PATH;
- `COACH_SHORTCUT_DIR` (shortcuts into the test folder, not the real Desktop) and
  `COACH_TRAY_AUTOQUIT` (the tray app quits itself, exercising the Quit path).

Driven from WSL with `powershell.exe`, `cmd.exe`, `curl.exe` and `tasklist.exe`, then deleted.
First start on an empty machine: about 20-30 seconds on a fast connection (uv, Python, 65 packages,
ffmpeg); later starts about 5 seconds.

## Bugs that only Windows showed

| Bug | Symptom | Cause | Fix |
|---|---|---|---|
| Open file deleted | every VOD marked failed at the last step | the results step kept `hud.npz` open; Linux allows deleting open files, Windows does not | close every `np.load` (context managers) |
| Console windows | (would have) flashed a window per ffmpeg chunk | console programs started from `pythonw` get new consoles | `CREATE_NO_WINDOW` + `python.exe` |
| yt-dlp could not merge | YouTube downloads failed at 99% | the subprocess environment was captured before ffmpeg was added to `PATH` | build the environment per job |
| Garbled stage text | "A·" instead of "·" in test output | PowerShell 5.1 console encoding | test artefact only; the API is UTF-8 |
| PowerShell 5.1 arrays | test scripts printed jumbled fields | `Invoke-RestMethod` emits a JSON array as one object in a pipeline | read the database directly in tests |
| Port seen across OSes | Windows start "found" the WSL app | Windows reaches WSL's localhost through a relay | documented: stop one before starting the other |

> Lesson: "works on Linux" says little about Windows file handles, process consoles and line
> endings. Test the real first-run path on a clean environment, and simulate one with environment
> variables when a clean machine is not available.

## Why not an installer or a desktop window?

Considered and deferred: an installer (`CoachDnunzSetup.exe`) shows "unknown publisher" warnings
without a code-signing certificate (~$100-400/year) and needs a build per release; a bundled desktop
window (PyInstaller, pywebview, Electron) adds ~300 MB builds and frequent antivirus false positives.
The ZIP + start file + desktop shortcut + tray icon gives most of the experience with none of that.
