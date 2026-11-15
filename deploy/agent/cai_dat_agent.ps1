<#
.SYNOPSIS
    Cai agent chay tu dong khi dang nhap Windows (Scheduled Task, quyen cao nhat) - bo cai tuan 8.

.DESCRIPTION
    Agent can quyen Administrator de khoi phuc IP / tuong lua / share, nen chay bang Scheduled Task
    \BackupSystem\BackupAgent voi RunLevel Highest, trigger luc dang nhap cua tai khoan hien tai.
    Truoc do: dien agent\agent_config.txt (SERVER_URL, AGENT_TOKEN, ENGINE=v2, V2_REPO, V2_PASSWORD_FILE ...).
    -Uninstall : go task.   -PrintOnly : chi in (khong can admin) - dung cho test.
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File deploy\agent\cai_dat_agent.ps1
#>
[CmdletBinding()]
param(
    [string]$RepoDir = '',
    [string]$PythonExe = '',
    [string]$TaskName = 'BackupAgent',
    [switch]$Uninstall,
    [switch]$PrintOnly
)
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $RepoDir) { $RepoDir = (Resolve-Path (Join-Path $here '..\..')).Path }
if (-not $PythonExe) {
    $venv = Join-Path $RepoDir '.venv\Scripts\python.exe'
    if (Test-Path $venv) { $PythonExe = $venv } else { $PythonExe = 'python.exe' }
}
$taskPath = '\BackupSystem\'
$user = [Security.Principal.WindowsIdentity]::GetCurrent().Name

if (-not $PrintOnly) {
    $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $isAdmin) { throw 'Can PowerShell quyen Administrator.' }
}
if ($Uninstall) {
    if ($PrintOnly) { Write-Host "TASK remove $taskPath$TaskName"; exit 0 }
    $t = Get-ScheduledTask -TaskPath $taskPath -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($t) { Stop-ScheduledTask -InputObject $t -ErrorAction SilentlyContinue; Unregister-ScheduledTask -InputObject $t -Confirm:$false; Write-Host "Da go $TaskName" }
    else { Write-Host "Khong co task $TaskName" }
    exit 0
}
$cfg = Join-Path $RepoDir 'agent\agent_config.txt'
if (-not $PrintOnly -and (Test-Path $cfg) -and ((Get-Content $cfg) -match '^AGENT_TOKEN=\s*$')) {
    Write-Host "CANH BAO: AGENT_TOKEN trong $cfg con trong - chep tu web (Cai dat > Ket noi agent) truoc."
}
$arg = '-B -m agent'
if ($PrintOnly) {
    Write-Host "TASK $taskPath$TaskName [AtLogOn $user, RunLevel Highest]: $PythonExe $arg  (cwd $RepoDir)"
    exit 0
}
$action = New-ScheduledTaskAction -Execute $PythonExe -Argument $arg -WorkingDirectory $RepoDir
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskPath $taskPath -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal `
    -Settings $settings -Description 'Backup agent (loi v2) - chay khi dang nhap, quyen cao nhat' -Force | Out-Null
Start-ScheduledTask -TaskPath $taskPath -TaskName $TaskName
Write-Host "Da cai task $taskPath$TaskName (chay ngay va moi lan $user dang nhap). Log: work\logs\agent.log"
