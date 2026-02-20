$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Workspace = (Resolve-Path "$Root\..").Path
$Manifest = Join-Path $Root "..\..\docs\installer-manifest.yaml" | Resolve-Path

python -m busy_installer.cli --manifest $Manifest --workspace $Workspace install $args

Start-Process "http://127.0.0.1:8080"
