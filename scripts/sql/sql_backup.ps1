<#
.SYNOPSIS
    Sao luu SQL Server bang sqlcmd: Full (hang tuan) / Diff (hang ngay) / Log (moi 15 phut).

.DESCRIPTION
    - Kiem tra recovery model FULL (ensure_full_recovery.sql).
    - Diff/Log ma CSDL chua co ban Full nao -> tu sao luu Full truoc (chuoi log can 1 ban Full).
    - Moi ban sao luu: WITH CHECKSUM + RESTORE VERIFYONLY; ten file kem thoi gian:
        <OutDir>\<DB>\<DB>_FULL_20261014_010000.bak  /  _DIFF_ .bak  /  _LOG_ .trn
    - Thu muc OutDir la noi agent v2 sao luu tiep (dua len kho, khu trung lap, ma hoa).
    - Ghi log vao <OutDir>\sql_backup.log. Ma thoat 1 neu co CSDL loi.
    -PrintOnly: chi in lenh se chay (khong can SQL Server) - dung cho test.

    TOI PHAI TU CHAY tren PC co SQL Server - xem docs/tuan3-chay-that.md.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\sql\sql_backup.ps1 -Mode Full -Database ShopDB
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidateSet('Full', 'Diff', 'Log')][string]$Mode,
    [Parameter(Mandatory = $true)][string[]]$Database,
    [string]$Instance = 'localhost\SQLEXPRESS',
    [string]$OutDir = 'D:\SQLBackup',
    [switch]$PrintOnly,
    [string]$Now = ''
)

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$stamp = if ($Now) { ([datetime]$Now).ToString('yyyyMMdd_HHmmss') } else { (Get-Date).ToString('yyyyMMdd_HHmmss') }
$Database = @($Database | ForEach-Object { $_ -split ',' } | Where-Object { $_ })   # -File truyen "A,B" la 1 chuoi
$logFile = Join-Path $OutDir 'sql_backup.log'
$plan = @{
    Full = @{ Sql = 'backup_full.sql'; Ext = 'bak'; Tag = 'FULL' }
    Diff = @{ Sql = 'backup_diff.sql'; Ext = 'bak'; Tag = 'DIFF' }
    Log  = @{ Sql = 'backup_log.sql';  Ext = 'trn'; Tag = 'LOG' }
}

function Write-Log([string]$msg) {
    $line = '{0} [{1}] {2}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Mode, $msg
    Write-Host $line
    if (-not $PrintOnly) { Add-Content -Path $logFile -Value $line -Encoding UTF8 }
}

function Invoke-SqlFile([string]$file, [hashtable]$vars) {
    $a = @('-S', $Instance, '-E', '-b', '-i', (Join-Path $here $file))
    foreach ($k in ($vars.Keys | Sort-Object)) { $a += '-v'; $a += ('{0}={1}' -f $k, $vars[$k]) }
    if ($PrintOnly) {
        Write-Host ('SQLCMD ' + (($a | ForEach-Object { if ($_ -match '\s') { '"' + $_ + '"' } else { $_ } }) -join ' '))
        return 0
    }
    & sqlcmd @a 2>&1 | ForEach-Object { Write-Log "  $_" }
    return $LASTEXITCODE
}

function Get-FullCount([string]$db) {
    $q = "SET NOCOUNT ON; SELECT COUNT(*) FROM msdb.dbo.backupset WHERE database_name = N'$db' AND type = 'D'"
    $out = & sqlcmd -S $Instance -E -b -h -1 -W -Q $q 2>&1
    if ($LASTEXITCODE -ne 0) { Write-Log "  CANH BAO: khong doc duoc msdb ($out) - giu nguyen che do $Mode"; return 1 }
    return [int](($out | Where-Object { $_ -match '^\d+$' } | Select-Object -First 1))
}

if (-not $PrintOnly) { New-Item -ItemType Directory -Force -Path $OutDir | Out-Null }
$failed = $false
foreach ($db in $Database) {
    if ($db -notmatch '^[A-Za-z0-9_\-]+$') { Write-Log "Bo qua ten CSDL khong hop le: $db"; $failed = $true; continue }
    $dir = Join-Path $OutDir $db
    $effective = $Mode
    if ($Mode -ne 'Full') {
        if ($PrintOnly) {
            Write-Host "CHECK msdb: so ban FULL cua $db (0 -> chay FULL thay cho $Mode)"
        } elseif ((Get-FullCount $db) -eq 0) {
            Write-Log "$db chua co ban FULL -> sao luu FULL truoc (bat dau chuoi log)"
            $effective = 'Full'
        }
    }
    $p = $plan[$effective]
    $file = Join-Path $dir ('{0}_{1}_{2}.{3}' -f $db, $p.Tag, $stamp, $p.Ext)
    if (-not $PrintOnly) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }

    $rc = Invoke-SqlFile 'ensure_full_recovery.sql' @{ DB = $db }
    if ($rc -ne 0) { Write-Log "  CANH BAO: khong kiem tra/dat duoc recovery FULL cho $db (ma $rc)" }
    $rc = Invoke-SqlFile $p.Sql @{ DB = $db; FILE = $file }
    if ($rc -ne 0) {
        Write-Log "LOI: sao luu $effective $db that bai (ma $rc)"
        $failed = $true
    } else {
        $size = if ($PrintOnly) { 0 } else { (Get-Item -LiteralPath $file).Length }
        Write-Log ("OK {0} -> {1} ({2:N0} byte)" -f $effective, $file, $size)
    }
}
if ($failed) { exit 1 }
exit 0
