$ErrorActionPreference = "Stop"

$ScriptPath = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Resolve-Path "$ScriptPath\..\..\.."

$python = (Get-Command python3 -ErrorAction SilentlyContinue).Source
if (-not $python) {
  $python = (Get-Command python -ErrorAction SilentlyContinue).Source
}

if (-not $python) {
  throw "Python 3 not found. Install Python 3.10+ and rerun."
}

$env:PYTHONPATH = "$($Root.Path)"
& $python -m busy_installer.platform.launcher @args
