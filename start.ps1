# One-command start for Windows. Double-click start.bat, which runs this.
# Installs uv if needed (it brings Python and every dependency), then starts the app and opens it.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# Own environment folder, so the same checkout can also be run from WSL with start.sh
$env:UV_PROJECT_ENVIRONMENT = ".venv-windows"
$env:UV_LINK_MODE = "copy"

$uvBin = Join-Path $env:USERPROFILE ".local\bin"
$env:Path = "$uvBin;$env:Path"
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "[coach] Installing uv (one-time setup)..."
    powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Write-Host "[coach] uv did not install. Check your internet connection and try again."
        exit 1
    }
}

Write-Host "[coach] Getting everything ready (the first run downloads Python and libraries, a few minutes)..."
uv run --extra engine python launch.py @args
exit $LASTEXITCODE
