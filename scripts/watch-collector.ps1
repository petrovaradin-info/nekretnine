param([switch]$Once, [ValidateRange(1,3600)][int]$Interval = 5)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $projectRoot 'venv\Scripts\python.exe'
$entry = Join-Path $projectRoot 'main.py'
$env:PYTHONIOENCODING = 'utf-8'
$watchArgs = @('watch', '--interval', $Interval)
if ($Once) { $watchArgs += '--once' }
& $pythonExe $entry @watchArgs
exit $LASTEXITCODE
