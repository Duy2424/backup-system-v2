<#
.SYNOPSIS
    Day ban sao kho v2 len cloud co Object Lock bang rclone (Nguoi B, tuan 5). Chi THEM, khong bao gio xoa.

.DESCRIPTION
    rclone copy <kho> <remote> --immutable --checksum
      - copy (KHONG sync): chi chep file moi; khong xoa gi tren cloud.
      - --immutable: file da co tren cloud ma khac noi dung -> bao loi. Pack/snapshot dat ten theo SHA-256 nen
        khong bao gio doi noi dung; neu khac la co chuyen.
      - bo qua tmp\ logs\ locks\ (noi bo kho).
    Sau khi chep: rclone check --one-way (so hash) de chac moi file local da nam tren cloud.
    Bucket bat Object Lock che do Compliance, giu 30 ngay mac dinh: moi file day len tu khoa 30 ngay, het han thi
    lifecycle cua bucket tu xoa -> khong can viet logic gia han khoa / don dep (ke hoach tuan 5).

    -Register   : tao Scheduled Task \BackupSystem\DayLenCloud chay hang ngay luc -At (mac dinh 02:30), tai khoan SYSTEM.
    -NotifyUrl  : POST ket qua JSON toi web server (http://127.0.0.1:5000/api/notify?token=<AGENT_TOKEN>) -> Thong bao + Telegram.
    -PrintOnly  : chi in lenh (khong can rclone) - dung cho test.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File deploy\cloud\day_len_cloud.ps1 -KhoDir D:\kho-v2 -Remote b2kho:ten-bucket/kho
    powershell -ExecutionPolicy Bypass -File deploy\cloud\day_len_cloud.ps1 -KhoDir D:\kho-v2 -Remote b2kho:ten-bucket/kho -Register
#>
[CmdletBinding()]
param(
    [string]$KhoDir = 'D:\kho-v2',
    [Parameter(Mandatory = $true)][string]$Remote,
    [string]$RcloneExe = 'rclone.exe',
    [string]$RcloneConfig = '',
    [string]$LogDir = '',
    [int]$Transfers = 8,
    [string]$NotifyUrl = '',
    [switch]$Register,
    [string]$At = '02:30',
    [switch]$PrintOnly
)

$ErrorActionPreference = 'Stop'
if ($Remote -notmatch '^[A-Za-z0-9_.-]+:[A-Za-z0-9_./-]*$') { Write-Host "Remote khong hop le: $Remote (dang ten-remote:bucket/duong-dan)"; exit 1 }
if (-not $LogDir) { $LogDir = Join-Path $KhoDir 'logs' }
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$logFile = Join-Path $LogDir "cloud_$stamp.log"
$common = @()
if ($RcloneConfig) { $common += @('--config', $RcloneConfig) }
$excludes = @('--exclude', 'tmp/**', '--exclude', 'logs/**', '--exclude', 'locks/**')

function Invoke-Rclone([string[]]$argv) {
    if ($PrintOnly) { Write-Host ("RCLONE " + ($argv -join ' ')); return 0 }
    & $RcloneExe @argv
    return $LASTEXITCODE
}

# ------------------------------------------------------------------ dang ky lich hang ngay
if ($Register) {
    $self = $MyInvocation.MyCommand.Path
    $arg = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$self`" -KhoDir `"$KhoDir`" -Remote `"$Remote`" -RcloneExe `"$RcloneExe`""
    if ($RcloneConfig) { $arg += " -RcloneConfig `"$RcloneConfig`"" }
    if ($NotifyUrl) { $arg += " -NotifyUrl `"$NotifyUrl`"" }
    if ($PrintOnly) { Write-Host "TASK \BackupSystem\DayLenCloud [hang ngay $At] SYSTEM: powershell.exe $arg"; exit 0 }
    $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $isAdmin) { throw 'Can PowerShell quyen Administrator de tao Scheduled Task.' }
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arg
    $trigger = New-ScheduledTaskTrigger -Daily -At $At
    $principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 6)
    Register-ScheduledTask -TaskPath '\BackupSystem\' -TaskName 'DayLenCloud' -Action $action -Trigger $trigger -Principal $principal `
        -Settings $settings -Description "Day kho v2 len cloud Object Lock (rclone copy --immutable) - hang ngay $At" -Force | Out-Null
    Write-Host "Da tao task \BackupSystem\DayLenCloud (hang ngay $At). Chay thu ngay: Start-ScheduledTask -TaskPath '\BackupSystem\' -TaskName DayLenCloud"
    exit 0
}

# ------------------------------------------------------------------ chep + kiem tra
if (-not $PrintOnly) {
    if (-not (Test-Path (Join-Path $KhoDir 'config'))) { Write-Host "Khong thay kho tai $KhoDir (chua init?)"; exit 1 }
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
}
$sw = [Diagnostics.Stopwatch]::StartNew()
Write-Host "== 1. rclone copy $KhoDir -> $Remote (chi them, --immutable)"
$rcCopy = Invoke-Rclone (@('copy', $KhoDir, $Remote, '--immutable', '--checksum', '--transfers', "$Transfers", '--fast-list',
                           '--stats-one-line', '--stats', '30s', '--log-level', 'INFO', '--log-file', $logFile) + $excludes + $common)
Write-Host "== 2. rclone check --one-way: moi file local da co tren cloud (so hash)"
$rcCheck = Invoke-Rclone (@('check', $KhoDir, $Remote, '--one-way', '--log-level', 'NOTICE', '--log-file', $logFile) + $excludes + $common)
$ok = ($rcCopy -eq 0 -and $rcCheck -eq 0)
$secs = [math]::Round($sw.Elapsed.TotalSeconds, 1)
$title = 'Day kho len cloud: OK'
$level = 'ok'
if (-not $ok) { $title = 'Day kho len cloud: LOI'; $level = 'err' }
$rep = [ordered]@{
    type = 'cloud'; title = $title; level = $level
    message = "rclone copy ma $rcCopy, check ma $rcCheck; $Remote; $secs giay; log $logFile"
    remote = $Remote; copy_exit = $rcCopy; check_exit = $rcCheck; seconds = $secs; at = (Get-Date -Format 's')
}
$json = $rep | ConvertTo-Json -Compress
Write-Host $json
if ($NotifyUrl -and -not $PrintOnly) {
    try { Invoke-RestMethod -Method Post -Uri $NotifyUrl -Body ([Text.Encoding]::UTF8.GetBytes($json)) -ContentType 'application/json; charset=utf-8' -TimeoutSec 15 | Out-Null }
    catch { Write-Host "Khong gui duoc thong bao toi $NotifyUrl : $_" }
}
if ($ok) { exit 0 } else { exit 1 }
