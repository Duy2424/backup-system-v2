<#
.SYNOPSIS
    Khoi phuc CSDL SQL Server ve DUNG mot thoi diem (point-in-time) tu cac file cua sql_backup.ps1.

.DESCRIPTION
    Chon file theo TEN (khong can msdb -> dung duoc tren may moi, kich ban K2):
      1. ban FULL moi nhat co thoi gian <= StopAt
      2. ban DIFF moi nhat sau FULL do va <= StopAt (neu co)
      3. moi ban LOG sau moc (DIFF hoac FULL), den ban LOG dau tien co thoi gian >= StopAt
    Sinh lenh: RESTORE DATABASE ... NORECOVERY -> DIFF NORECOVERY -> LOG ... STOPAT NORECOVERY -> WITH RECOVERY.
    Mac dinh khoi phuc ra CSDL MOI (<DB>_khoiphuc) de doi chieu, khong de len CSDL dang chay;
    -TargetDatabase <DB> -Replace de ghi de CSDL goc.
    -PrintOnly: chi in ke hoach + lenh (khong can SQL Server) - dung cho test.

    TOI PHAI TU CHAY tren PC co SQL Server (dien tap K3: xoa nham du lieu roi quay ve truoc luc xoa).
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\sql\restore_pitr.ps1 -Database ShopDB -StopAt "2026-10-14 10:15:00"
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Database,
    [Parameter(Mandatory = $true)][string]$StopAt,
    [string]$BackupDir = 'D:\SQLBackup',
    [string]$Instance = 'localhost\SQLEXPRESS',
    [string]$TargetDatabase = '',
    [switch]$Replace,
    [switch]$PrintOnly
)

$ErrorActionPreference = 'Stop'
foreach ($n in @($Database, $TargetDatabase)) {
    if ($n -and $n -notmatch '^[A-Za-z0-9_\-]+$') { Write-Host "Ten CSDL khong hop le: $n"; exit 1 }
}
if (-not $TargetDatabase) { $TargetDatabase = "${Database}_khoiphuc" }
$stop = [datetime]$StopAt
$stopIso = $stop.ToString('yyyy-MM-ddTHH:mm:ss')

# ---------- 1. Liet ke file sao luu ----------
$dir = Join-Path $BackupDir $Database
$rx = '^' + [regex]::Escape($Database) + '_(FULL|DIFF|LOG)_(\d{8}_\d{6})\.(bak|trn)$'
$sets = @(Get-ChildItem -LiteralPath $dir -File -ErrorAction SilentlyContinue | ForEach-Object {
        if ($_.Name -match $rx) {
            [pscustomobject]@{ Kind = $Matches[1]; Time = [datetime]::ParseExact($Matches[2], 'yyyyMMdd_HHmmss', $null); Path = $_.FullName }
        } } | Sort-Object Time)

$full = $sets | Where-Object { $_.Kind -eq 'FULL' -and $_.Time -le $stop } | Select-Object -Last 1
if (-not $full) { Write-Host "Khong co ban FULL nao truoc $stopIso trong $dir"; exit 1 }
$diff = $sets | Where-Object { $_.Kind -eq 'DIFF' -and $_.Time -gt $full.Time -and $_.Time -le $stop } | Select-Object -Last 1
$base = if ($diff) { $diff.Time } else { $full.Time }
$logs = @()
foreach ($l in ($sets | Where-Object { $_.Kind -eq 'LOG' -and $_.Time -gt $base })) {
    $logs += $l
    if ($l.Time -ge $stop) { break }
}
if (-not $logs -or $logs[-1].Time -lt $stop) {
    Write-Host "CANH BAO: chua co ban LOG nao sau $stopIso - chi khoi phuc duoc toi $(if ($logs) { $logs[-1].Time } else { $base })"
}

Write-Host "KE HOACH khoi phuc $Database -> $TargetDatabase toi $stopIso"
Write-Host "  FULL $($full.Time.ToString('s'))  $($full.Path)"
if ($diff) { Write-Host "  DIFF $($diff.Time.ToString('s'))  $($diff.Path)" }
foreach ($l in $logs) { Write-Host "  LOG  $($l.Time.ToString('s'))  $($l.Path)" }

# ---------- 2. Sinh T-SQL ----------
$move = ''
if ($TargetDatabase -ne $Database) {
    if ($PrintOnly) {
        $move = ", MOVE N'<ten logic data>' TO N'<thu muc data>\${TargetDatabase}.mdf', MOVE N'<ten logic log>' TO N'<thu muc data>\${TargetDatabase}_log.ldf'"
    } else {
        $q = "SET NOCOUNT ON; SELECT CAST(SERVERPROPERTY('InstanceDefaultDataPath') AS nvarchar(400))"
        $dataDir = ((& sqlcmd -S $Instance -E -b -h -1 -W -Q $q) | Where-Object { $_ } | Select-Object -First 1).TrimEnd('\')
        $fl = & sqlcmd -S $Instance -E -b -h -1 -W -s '|' -Q "SET NOCOUNT ON; RESTORE FILELISTONLY FROM DISK = N'$($full.Path)'"
        $i = 0
        foreach ($row in $fl) {
            $c = $row -split '\|'
            if ($c.Count -lt 3 -or -not $c[0]) { continue }
            $ext = if ($c[2] -eq 'L') { 'ldf' } else { 'mdf' }
            $move += ", MOVE N'$($c[0])' TO N'$dataDir\${TargetDatabase}_$i.$ext'"
            $i++
        }
    }
}
$rep = if ($Replace -or $TargetDatabase -ne $Database) { ', REPLACE' } else { '' }
$sql = @("RESTORE DATABASE [$TargetDatabase] FROM DISK = N'$($full.Path)' WITH NORECOVERY, CHECKSUM$rep$move, STATS = 10;")
if ($diff) { $sql += "RESTORE DATABASE [$TargetDatabase] FROM DISK = N'$($diff.Path)' WITH NORECOVERY, CHECKSUM, STATS = 10;" }
foreach ($l in $logs) { $sql += "RESTORE LOG [$TargetDatabase] FROM DISK = N'$($l.Path)' WITH NORECOVERY, CHECKSUM, STOPAT = N'$stopIso';" }
$sql += "RESTORE DATABASE [$TargetDatabase] WITH RECOVERY;"

if ($PrintOnly) { $sql | ForEach-Object { Write-Host "SQL $_" }; exit 0 }

$tmp = Join-Path $env:TEMP ("restore_pitr_{0}.sql" -f (Get-Date -Format 'yyyyMMddHHmmss'))
Set-Content -LiteralPath $tmp -Value $sql -Encoding Unicode
& sqlcmd -S $Instance -E -b -i $tmp
$rc = $LASTEXITCODE
Remove-Item -LiteralPath $tmp
if ($rc -ne 0) { Write-Host "LOI: khoi phuc that bai (ma $rc)"; exit 1 }
Write-Host "XONG: $TargetDatabase da ve trang thai luc $stopIso"
exit 0
