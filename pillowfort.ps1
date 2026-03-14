$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Split-Path -Parent $MyInvocation.MyCommand.Path)
$VenvPython = Join-Path $Root.Path ".venv\Scripts\python.exe"
$Bootstrap = Join-Path $Root.Path "scripts\bootstrap_env.py"

$python = (Get-Command python3 -ErrorAction SilentlyContinue).Source
if (-not $python) {
  $python = (Get-Command python -ErrorAction SilentlyContinue).Source
}

if (-not $python) {
  throw "Python 3 not found. Install Python 3.10+ and rerun."
}

& $python $Bootstrap
& $VenvPython -m busy_installer.app @args
