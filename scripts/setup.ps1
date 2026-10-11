param([string]$PythonExe = 'python', [switch]$InstallSchedule, [switch]$Unattended)
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
if ($projectRoot.TrimEnd('\') -ine 'D:\PycharmProjects\nekretnine') { throw 'Klonirajte repo u D:\PycharmProjects\nekretnine.' }
$env:TEMP = Join-Path $projectRoot '.runtime\tmp'
$env:TMP = $env:TEMP
$env:TMPDIR = $env:TEMP
$env:PIP_CACHE_DIR = Join-Path $projectRoot '.cache\pip'
$env:PYTHONIOENCODING = 'utf-8'
New-Item -ItemType Directory -Path $env:TEMP,$env:PIP_CACHE_DIR -Force | Out-Null
Set-Location -LiteralPath $projectRoot
$venvPython = Join-Path $projectRoot 'venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) {
    & $PythonExe -m venv (Join-Path $projectRoot 'venv')
    if ($LASTEXITCODE -ne 0) { throw 'Kreiranje venv-a nije uspelo. Potreban je Python 3.10 ili noviji.' }
}
& $venvPython -m pip install --no-cache-dir -r (Join-Path $projectRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Instalacija zavisnosti nije uspela.' }
& $venvPython (Join-Path $projectRoot 'main.py') --help
if ($LASTEXITCODE -ne 0) { throw 'Provera pokretanja nije uspela.' }
if ($InstallSchedule) {
    & (Join-Path $PSScriptRoot 'install-schedule.ps1') -Unattended:$Unattended
    if ($LASTEXITCODE -ne 0) { throw 'Instalacija rasporeda nije uspela.' }
}
