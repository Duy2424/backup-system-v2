<#
.SYNOPSIS
    Gia lap ransomware len thu muc du lieu DEMO (kich ban K1, tuan 8) - CHI dung voi du lieu mau!

.DESCRIPTION
    Ghi noi dung ngau nhien (entropy cao) + doi ten .locked cho -Ratio (mac dinh 70%) file van ban / van phong,
    sua file moi ~bks_canary*, de lai HUONG_DAN_CHUOC.txt. Sau do bam "Sao luu" tren web: agent phai DUNG
    (cong chan bat thuong), job that bai "BAT THUONG", Thong bao do (+ Telegram). Roi khoi phuc tu ban tot cuoi:
    Ban sao luu -> chon ban -> "Xoa file khong co trong ban sao luu" -> Khoi phuc.
    An toan: tu choi chay neu thu muc khong chua file moi ~bks_canary* (dau hieu la du lieu demo).
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File deploy\demo\gia_ransomware.ps1 -Data D:\DemoBackup\DuLieu
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Data,
    [double]$Ratio = 0.7,
    [switch]$Force
)
$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $Data -PathType Container)) { Write-Host "Khong co thu muc $Data"; exit 1 }
$canaries = @(Get-ChildItem -LiteralPath $Data -Recurse -File -Filter '~bks_canary*')
if (-not $canaries -and -not $Force) {
    Write-Host "Thu muc $Data khong co file moi ~bks_canary* -> khong giong du lieu demo. Dung -Force neu chac chan."
    exit 1
}
$exts = '.txt', '.md', '.csv', '.json', '.ini', '.xml', '.docx', '.xlsx'
$files = @(Get-ChildItem -LiteralPath $Data -Recurse -File | Where-Object { $exts -contains $_.Extension.ToLower() -and $_.Name -notlike '~bks_canary*' })
if (-not $files) { Write-Host 'Khong co file van ban nao de "ma hoa"'; exit 1 }
$n = [Math]::Max(1, [int]($files.Count * $Ratio))
$rng = New-Object System.Random
$victims = $files | Sort-Object { $rng.Next() } | Select-Object -First $n
$buf = New-Object byte[] 65536
$done = 0
foreach ($f in $victims) {
    $size = [Math]::Max([int]$f.Length, 64)
    $fs = [IO.File]::Open($f.FullName, 'Create')
    try {
        $left = $size
        while ($left -gt 0) { $rng.NextBytes($buf); $k = [Math]::Min($buf.Length, $left); $fs.Write($buf, 0, $k); $left -= $k }
    } finally { $fs.Close() }
    Rename-Item -LiteralPath $f.FullName -NewName ($f.Name + '.locked')
    $done++
}
foreach ($c in $canaries) { [IO.File]::WriteAllText($c.FullName, "DA BI MA HOA $(Get-Date -Format 's')") }
[IO.File]::WriteAllText((Join-Path $Data 'HUONG_DAN_CHUOC.txt'), "Your files are encrypted. Pay 2 BTC to ...`r`n(Gia lap - demo K1)")
Write-Host "Da 'ma hoa' $done/$($files.Count) file (.locked) va sua $($canaries.Count) file moi trong $Data."
Write-Host 'Bay gio bam "Sao luu" tren web: cong chan phai DUNG job (BAT THUONG). Sau do khoi phuc tu ban tot cuoi.'
