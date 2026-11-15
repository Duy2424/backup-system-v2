<#
.SYNOPSIS
    Khoi phuc thu CSDL hang tuan: khoi phuc ban moi nhat (Full + Diff + Log) ra CSDL tam <DB>_kiemtra,
    chay DBCC CHECKDB, ghi bao cao JSON, roi xoa CSDL tam. Ma thoat 1 neu loi.
    -PrintOnly: chi in cac buoc (khong can SQL Server) - dung cho test.
    TOI PHAI TU CHAY tren PC (hoac dat Scheduled Task hang tuan).
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\sql\verify_sql_restore.ps1 -Database ShopDB -Report D:\SQLBackup\kiemtra.json
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Database,
    [string]$BackupDir = 'D:\SQLBackup',
    [string]$Instance = 'localhost\SQLEXPRESS',
    [string]$Report = '',
    [string]$NotifyUrl = '',
    [switch]$PrintOnly
)
$ErrorActionPreference = 'Stop'
if ($Database -notmatch '^[A-Za-z0-9_\-]+$') { Write-Host "Ten CSDL khong hop le: $Database"; exit 1 }
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$target = "${Database}_kiemtra"
$now = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
$sw = [Diagnostics.Stopwatch]::StartNew()
$restoreArgs = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $here 'restore_pitr.ps1'),
    '-Database', $Database, '-StopAt', $now, '-BackupDir', $BackupDir, '-Instance', $Instance, '-TargetDatabase', $target)
$check = "DBCC CHECKDB ([$target]) WITH NO_INFOMSGS, ALL_ERRORMSGS;"
$drop = "ALTER DATABASE [$target] SET SINGLE_USER WITH ROLLBACK IMMEDIATE; DROP DATABASE [$target];"
if ($PrintOnly) {
    Write-Host ("STEP restore: powershell " + ($restoreArgs -join ' '))
    Write-Host "STEP check: $check"
    Write-Host "STEP drop: $drop"
    exit 0
}
& powershell.exe @restoreArgs
$rc1 = $LASTEXITCODE
$out = ''
$rc2 = -1
if ($rc1 -eq 0) {
    $out = (& sqlcmd -S $Instance -E -b -Q $check 2>&1) -join "`n"
    $rc2 = $LASTEXITCODE
    & sqlcmd -S $Instance -E -b -Q $drop | Out-Null
}
$ok = ($rc1 -eq 0 -and $rc2 -eq 0)
$rep = [ordered]@{ type = 'verify_sql'; result = $(if ($ok) { 'OK' } else { 'LOI' }); database = $Database
    restored_as = $target; at = $now; restore_exit = $rc1; checkdb_exit = $rc2; checkdb_output = $out
    seconds = [math]::Round($sw.Elapsed.TotalSeconds, 1) }
$json = $rep | ConvertTo-Json
if ($Report) { Set-Content -LiteralPath $Report -Value $json -Encoding UTF8 }
Write-Host $json
# tuan 6: bao ket qua len web (Thong bao + Telegram): -NotifyUrl "http://127.0.0.1:5000/api/notify?token=<AGENT_TOKEN>"
if ($NotifyUrl) {
    try { Invoke-RestMethod -Method Post -Uri $NotifyUrl -Body ([Text.Encoding]::UTF8.GetBytes($json)) -ContentType 'application/json; charset=utf-8' -TimeoutSec 15 | Out-Null }
    catch { Write-Host "Khong gui duoc thong bao toi $NotifyUrl : $_" }
}
if ($ok) { exit 0 } else { exit 1 }
