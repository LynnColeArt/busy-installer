$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Split-Path -Parent $MyInvocation.MyCommand.Path)
$VenvPython = Join-Path $Root.Path ".venv\Scripts\python.exe"
$Bootstrap = Join-Path $Root.Path "scripts\bootstrap_env.py"

if (Test-Path $VenvPython) {
  $python = $VenvPython
} else {
  $python = (Get-Command python3 -ErrorAction SilentlyContinue).Source
  if (-not $python) {
    $python = (Get-Command python -ErrorAction SilentlyContinue).Source
  }
}

if (-not $python) {
  throw "Python 3 not found and $VenvPython is missing. Install Python 3.10+ and rerun."
}

& $python $Bootstrap | Out-Null
if (-not (Test-Path $VenvPython)) {
  throw "bootstrap completed but $VenvPython is missing."
}
& $VenvPython -m busy_installer.app @args
