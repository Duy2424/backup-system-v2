<#
.SYNOPSIS
    Tuan 5 (B) - thu XOA HAN mot file dang bi Object Lock tren cloud: phai bi TU CHOI (dien tap K5 tren cloud).

.DESCRIPTION
    1. Lay mot pack bat ky tren remote (rclone lsf <remote>/packs -R --files-only), hoac -File chi dinh.
    2. Xoa han file do:
         B2 : rclone deletefile ... --b2-hard-delete   (xoa phien ban that, khong chi "an" file)
         S3 : rclone deletefile ... --s3-versions
       Mong doi: rclone bao loi (B2: "file is locked" / S3: AccessDenied), ma thoat khac 0.
    3. Liet ke lai: file van con -> ket luan TU CHOI (dung). Ghi JSON (-Report) de dua vao bao cao + chup man hinh.
    Luu y S3: xoa KHONG kem version id chi tao "delete marker" (file nhin nhu mat nhung phien ban van con, khoi phuc duoc) -
    khong phai lo hong; xoa phien ban cu the moi bi tu choi. B2 cung vay: "an" file (hide) khac "xoa phien ban".
    -PrintOnly: chi in lenh (khong can rclone / mang) - dung cho test.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File deploy\cloud\thu_xoa_bi_tu_choi.ps1 -Remote b2kho:ten-bucket/kho
    powershell -ExecutionPolicy Bypass -File deploy\cloud\thu_xoa_bi_tu_choi.ps1 -Remote s3kho:ten-bucket/kho -Backend S3
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Remote,
    [ValidateSet('B2', 'S3')][string]$Backend = 'B2',
    [string]$RcloneExe = 'rclone.exe',
    [string]$RcloneConfig = '',
    [string]$File = '',
    [string]$Report = '',
    [switch]$PrintOnly
)

$ErrorActionPreference = 'Stop'
if ($Remote -notmatch '^[A-Za-z0-9_.-]+:[A-Za-z0-9_./-]*$') { Write-Host "Remote khong hop le: $Remote"; exit 1 }
$common = @()
if ($RcloneConfig) { $common += @('--config', $RcloneConfig) }
$hard = @('--b2-hard-delete')
if ($Backend -eq 'S3') { $hard = @('--s3-versions') }

if (-not $File) {
    if ($PrintOnly) { $File = 'packs/ab/<pack-id>' }
    else {
        $File = (& $RcloneExe lsf "$Remote/packs" -R --files-only @common | Select-Object -First 1)
        if (-not $File) { Write-Host "Remote $Remote chua co pack nao - chay day_len_cloud.ps1 truoc"; exit 2 }
        $File = "packs/$File"
    }
}
$target = "$Remote/$File"
$del = @('deletefile', $target) + $hard + $common
Write-Host "== Thu xoa han file dang bi khoa: $target"
if ($PrintOnly) {
    Write-Host ("RCLONE " + ($del -join ' '))
    Write-Host "RCLONE lsf $target"
    Write-Host 'KET QUA MONG DOI: TU CHOI (ma thoat khac 0, "file is locked" / AccessDenied), file van con'
    exit 0
}
$ErrorActionPreference = 'Continue'
$out = (& $RcloneExe @del 2>&1 | Out-String).Trim()
$rc = $LASTEXITCODE
$still = ((& $RcloneExe lsf $target @common 2>$null | Measure-Object).Count -gt 0)
$ErrorActionPreference = 'Stop'

if ($rc -ne 0 -and $still) { $verdict = 'TU CHOI'; $ok = $true }
elseif ($still) { $verdict = 'FILE VAN CON nhung rclone khong bao loi (chi an / delete marker?) - kiem tra lai che do Object Lock'; $ok = $false }
else { $verdict = 'DA XOA DUOC !!! - bucket CHUA bat Object Lock hoac khoa da het han'; $ok = $false }
$rep = [ordered]@{
    type = 'cloud_k5'; title = "Thu xoa file bi khoa tren cloud: $verdict"; level = $(if ($ok) { 'ok' } else { 'err' })
    message = "$target ; rclone ma $rc ; con tren cloud: $still ; $out"
    remote = $Remote; file = $File; backend = $Backend; rclone_exit = $rc; still_exists = $still; verdict = $verdict
    at = (Get-Date -Format 's')
}
$json = $rep | ConvertTo-Json
Write-Host "rclone noi: $out"
Write-Host "File con tren cloud: $still"
Write-Host "KET LUAN: $verdict"
if ($Report) { Set-Content -LiteralPath $Report -Value $json -Encoding UTF8; Write-Host "Da ghi $Report" }
if ($ok) { exit 0 } else { exit 1 }
