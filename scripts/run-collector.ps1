param([ValidateSet("collect","update")][string]$Mode = "collect", [switch]$WaitForLock, [switch]$Refresh, [ValidateRange(1,3600)][int]$ProgressInterval = 10)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $projectRoot 'venv\Scripts\python.exe'
$entry = Join-Path $projectRoot 'main.py'
$env:PYTHONIOENCODING = 'utf-8'
$env:TEMP = Join-Path $projectRoot '.runtime\tmp'
$env:TMP = $env:TEMP
$env:TMPDIR = $env:TEMP
$env:PIP_CACHE_DIR = Join-Path $projectRoot '.cache\pip'
New-Item -ItemType Directory -Path $env:TEMP,$env:PIP_CACHE_DIR -Force | Out-Null
Set-Location -LiteralPath $projectRoot
if (-not (Test-Path -LiteralPath $pythonExe)) { throw 'Nema venv-a. Pokrenite scripts\setup.ps1.' }
$logDirectory = Join-Path $projectRoot 'logs'
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
$taskLog = Join-Path $logDirectory ("task-{0}-{1}-{2}.log" -f $Mode,(Get-Date -Format 'yyyyMMdd-HHmmss'),$PID)
Start-Transcript -Path $taskLog -Force | Out-Null
try {
$collectArgs = @($Mode)
if ($Mode -eq 'collect') { $collectArgs += @('--progress-interval', $ProgressInterval) }
if ($Refresh -and $Mode -eq "collect") { $collectArgs += '--refresh' }
$waitDeadline = (Get-Date).AddHours(12)
do {
    & $pythonExe $entry @collectArgs
    $collectExit = $LASTEXITCODE
    if ($collectExit -eq 3 -and $WaitForLock) {
        if ((Get-Date) -ge $waitDeadline) { throw 'Baza zauzeta duze od 12 sati.' }
        Write-Output 'Baza zauzeta; sledeca provera za 60 sekundi.'
        Start-Sleep -Seconds 60
    }
} while ($collectExit -eq 3 -and $WaitForLock)
if ($collectExit -eq 130) { exit 130 }
if ($collectExit -notin @(0, 2)) { exit $collectExit }
do {
    & $pythonExe $entry publish
    $publishExit = $LASTEXITCODE
    if ($publishExit -eq 3 -and $WaitForLock) {
        if ((Get-Date) -ge $waitDeadline) { throw 'Izvoz ceka bazu duze od 12 sati.' }
        Start-Sleep -Seconds 60
    }
} while ($publishExit -eq 3 -and $WaitForLock)
if ($publishExit -ne 0) { exit $publishExit }
exit $collectExit

} finally { Stop-Transcript | Out-Null }
