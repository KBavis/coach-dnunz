@echo off
rem Double-click to start Coach dnunz on Windows.
pushd "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"
if errorlevel 1 (
  echo.
  echo Something went wrong. Read the message above, then press any key to close.
  pause >nul
)
popd
