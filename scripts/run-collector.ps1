param([switch]$Refresh, [ValidateRange(1,3600)][int]$ProgressInterval = 10)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $projectRoot 'venv\Scripts\python.exe'
$entry = Join-Path $projectRoot 'main.py'
$env:PYTHONIOENCODING = 'utf-8'
$collectArgs = @('collect', '--progress-interval', $ProgressInterval)
if ($Refresh) { $collectArgs += '--refresh' }
& $pythonExe $entry @collectArgs
$collectExit = $LASTEXITCODE
if ($collectExit -eq 130) { exit 130 }
if ($collectExit -notin @(0, 2)) { exit $collectExit }
& $pythonExe $entry export
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $pythonExe $entry export --format csv
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $pythonExe $entry candidates
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $pythonExe $entry report
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
exit $collectExit
