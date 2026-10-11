param([switch]$Unattended, [switch]$Remove, [switch]$Check)
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$requiredRoot = 'D:\PycharmProjects\nekretnine'
if ($projectRoot.TrimEnd('\') -ine $requiredRoot) { throw "Repo mora biti u $requiredRoot. Trenutno: $projectRoot" }
$taskNames = @('Nekretnine-Collect-0600', 'Nekretnine-Update-0730')
if ($Remove) {
    foreach ($taskName in $taskNames) {
        if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) { Unregister-ScheduledTask -TaskName $taskName -Confirm:$false }
    }
    exit 0
}
if ($Check) {
    foreach ($taskName in $taskNames) {
        $task = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
        $info = Get-ScheduledTaskInfo -TaskName $taskName
        [PSCustomObject]@{ Name=$taskName; State=$task.State; NextRun=$info.NextRunTime; LastRun=$info.LastRunTime; Result=$info.LastTaskResult; Logon=$task.Principal.LogonType; Script=$task.Actions.Arguments }
    }
    exit 0
}
if ((Get-TimeZone).Id -ne 'Central Europe Standard Time') { throw 'Podesite Windows vremensku zonu na Beograd (Central Europe Standard Time) pre instalacije rasporeda.' }
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot 'venv\Scripts\python.exe'))) { throw 'Prvo pokrenite scripts\setup.ps1.' }
$identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$logonType = 'Interactive'
if ($Unattended) { $logonType = 'S4U' }
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType $logonType -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 20) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$runner = Join-Path $projectRoot 'scripts\run-collector.ps1'
$definitions = @(@{Name=$taskNames[0]; Mode='collect'; Time='06:00'}, @{Name=$taskNames[1]; Mode='update'; Time='07:30'})
foreach ($definition in $definitions) {
    $arguments = '-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "{0}" -Mode {1} -WaitForLock' -f $runner,$definition.Mode
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arguments -WorkingDirectory $projectRoot
    $taskTime = [datetime]::Today.Add([TimeSpan]::Parse($definition.Time + ':00'))
    $trigger = New-ScheduledTaskTrigger -Daily -At $taskTime
    # No UTC offset: Windows keeps local Belgrade wall-clock time across DST.
    $trigger.StartBoundary = $taskTime.ToString("yyyy-MM-ddTHH:mm:ss")
    Register-ScheduledTask -TaskName $definition.Name -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description 'Nekretnine: samostalni Python; lokalni projekat na D disku; vreme Beograd.' -Force | Select-Object TaskName,State
}
Write-Output "Raspored instaliran. LogonType=$logonType; Codex i PyCharm nisu potrebni."
if (-not $Unattended) { Write-Output 'Korisnik mora biti prijavljen u Windows (zakljucan ekran je OK). Za rad odjavljenog korisnika pokrenite ovu skriptu kao administrator sa -Unattended.' }
