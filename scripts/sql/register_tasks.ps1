<#
.SYNOPSIS
    Tao 3 Scheduled Task sao luu SQL Server (chay bang tai khoan SYSTEM):
      \BackupSystem\BackupSQL-Full   Chu Nhat 01:00
      \BackupSystem\BackupSQL-Diff   Thu Hai..Thu Bay 01:30
      \BackupSQL-Log                 moi 15 phut
.DESCRIPTION
    Truoc khi tao task (chay bang tai khoan admin dang cai SQL Server):
      1. ensure_full_recovery.sql: dat recovery model FULL
      2. grant_system.sql: cap quyen TOI THIEU cho NT AUTHORITY\SYSTEM (khong phai sysadmin)
      3. sau khi tao task: chay ngay BackupSQL-Full mot lan de bat dau chuoi log
    -PrintOnly: chi in ke hoach (khong can quyen admin, khong can SQL Server) - dung cho test.

    TOI PHAI TU CHAY tren PC, PowerShell quyen Administrator.
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\sql\register_tasks.ps1 -Database ShopDB -OutDir D:\SQLBackup
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string[]]$Database,
    [string]$Instance = 'localhost\SQLEXPRESS',
    [string]$OutDir = 'D:\SQLBackup',
    [switch]$PrintOnly,
    [switch]$SkipGrant
)

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$script = Join-Path $here 'sql_backup.ps1'
$Database = @($Database | ForEach-Object { $_ -split ',' } | Where-Object { $_ })
foreach ($db in $Database) { if ($db -notmatch '^[A-Za-z0-9_\-]+$') { throw "Ten CSDL khong hop le: $db" } }
$dbArg = $Database -join ','

if (-not $PrintOnly) {
    $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $isAdmin) { throw 'Can PowerShell quyen Administrator.' }
}

$tasks = @(
    @{ Name = 'BackupSQL-Full'; Mode = 'Full'; When = 'Chu Nhat 01:00' },
    @{ Name = 'BackupSQL-Diff'; Mode = 'Diff'; When = 'Thu Hai-Thu Bay 01:30' },
    @{ Name = 'BackupSQL-Log';  Mode = 'Log';  When = 'moi 15 phut' }
)

function New-Trigger([string]$mode) {
    switch ($mode) {
        'Full' { return New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At '01:00' }
        'Diff' { return New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday, Saturday -At '01:30' }
        'Log'  { return New-ScheduledTaskTrigger -Once -At ((Get-Date).Date.AddMinutes(5)) `
                     -RepetitionInterval (New-TimeSpan -Minutes 15) -RepetitionDuration (New-TimeSpan -Days 3650) }
    }
}

# ---------- 1-2. Recovery FULL + quyen cho SYSTEM ----------
if (-not $SkipGrant) {
    foreach ($db in $Database) {
        foreach ($f in 'ensure_full_recovery.sql', 'grant_system.sql') {
            $a = @('-S', $Instance, '-E', '-b', '-i', (Join-Path $here $f), '-v', "DB=$db")
            if ($PrintOnly) { Write-Host ('SQLCMD ' + ($a -join ' ')); continue }
            & sqlcmd @a
            if ($LASTEXITCODE -ne 0) { throw "sqlcmd $f cho $db that bai (ma $LASTEXITCODE)" }
        }
    }
}

# ---------- 3. Tao task ----------
foreach ($t in $tasks) {
    $arg = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$script`" -Mode $($t.Mode) " +
           "-Database $dbArg -Instance `"$Instance`" -OutDir `"$OutDir`""
    if ($PrintOnly) {
        Write-Host "TASK \BackupSystem\$($t.Name) [$($t.When)] SYSTEM: powershell.exe $arg"
        continue
    }
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arg
    $principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
        -ExecutionTimeLimit (New-TimeSpan -Hours 4)
    Register-ScheduledTask -TaskPath '\BackupSystem\' -TaskName $t.Name -Action $action -Trigger (New-Trigger $t.Mode) `
        -Principal $principal -Settings $settings -Description "Sao luu SQL $($t.Mode) - $($t.When)" -Force | Out-Null
    Write-Host "Da tao \BackupSystem\$($t.Name) ($($t.When))"
}

if ($PrintOnly) {
    Write-Host 'RUN \BackupSystem\BackupSQL-Full (ban Full dau tien)'
} else {
    Start-ScheduledTask -TaskPath '\BackupSystem\' -TaskName 'BackupSQL-Full'
    Write-Host "Da chay BackupSQL-Full lan dau. Xem log: $OutDir\sql_backup.log"
}
