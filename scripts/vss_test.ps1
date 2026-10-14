<#
.SYNOPSIS
    Thu VSS (Volume Shadow Copy) tren PC: chup o dia, doc 1 file Word DANG MO
    qua ban chup, in SHA-256, roi xoa ban chup.

.DESCRIPTION
    Windows ban client (10/11) khong co "vssadmin create shadow", nen script
    tao shadow copy qua WMI/CIM: Win32_ShadowCopy.Create (Context=ClientAccessible).
    Ban chup duoc gan vao 1 thu muc bang mklink /d toi
    \\?\GLOBALROOT\Device\HarddiskVolumeShadowCopyN\  (BAT BUOC co dau \ cuoi).
    Moi buoc deu in thoi gian de ghi vao bao cao. Cuoi cung LUON go link va xoa
    shadow copy (ke ca khi loi giua chung).

    PHAI chay bang PowerShell 64-bit, quyen Administrator.
    TOI PHAI TU CHAY tren PC - xem docs/vss-test.md.

.PARAMETER FilePath
    File Word dang mo trong Word (vd C:\Users\Duy\Documents\vss_test.docx).
    Phai nam tren o dia -Volume.

.PARAMETER Volume
    O dia can chup, mac dinh C:\

.PARAMETER MountPath
    Thu muc tam de gan ban chup, mac dinh C:\vss_mount_test (phai CHUA ton tai).

.PARAMETER CopyTo
    (Tuy chon) Chep file doc tu ban chup ra day de mo thu bang Word.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\vss_test.ps1 -FilePath "C:\Users\Duy\Documents\vss_test.docx"
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$FilePath,
    [string]$Volume = 'C:\',
    [string]$MountPath = "$env:SystemDrive\vss_mount_test",
    [string]$CopyTo = ''
)

$ErrorActionPreference = 'Stop'
$swAll = [Diagnostics.Stopwatch]::StartNew()

function Step([string]$msg) { Write-Host ("[{0,7:N2}s] {1}" -f $swAll.Elapsed.TotalSeconds, $msg) }

$vssErrors = @{
    1 = 'Access denied (chua chay Administrator?)'; 2 = 'Invalid argument'; 3 = 'Volume not found'
    4 = 'Volume not supported'; 5 = 'Unsupported shadow copy context'; 6 = 'Insufficient storage (thieu cho cho shadow storage)'
    7 = 'Volume is in use'; 8 = 'Maximum number of shadow copies reached'; 9 = 'Another shadow copy operation is in progress'
    10 = 'Shadow copy provider vetoed the operation'; 11 = 'Shadow copy provider not registered'
    12 = 'Shadow copy provider failure'; 13 = 'Unknown error'
}

# ---------- 0. Kiem tra dieu kien ----------
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) { throw 'Can chay PowerShell bang quyen Administrator (Run as administrator).' }
if ([Environment]::Is64BitOperatingSystem -and -not [Environment]::Is64BitProcess) {
    throw 'Dang chay PowerShell 32-bit tren Windows 64-bit -> Win32_ShadowCopy.Create se loi. Mo PowerShell 64-bit.'
}
if (-not $Volume.EndsWith('\')) { $Volume += '\' }
$FilePath = (Resolve-Path -LiteralPath $FilePath).Path
if (-not $FilePath.StartsWith($Volume, [StringComparison]::OrdinalIgnoreCase)) {
    throw "File $FilePath khong nam tren o $Volume"
}
if (Test-Path -LiteralPath $MountPath) { throw "$MountPath da ton tai - chon -MountPath khac hoac tu go link cu." }

$os = Get-CimInstance Win32_OperatingSystem
Write-Host '=== THU VSS ==='
Write-Host "May      : $env:COMPUTERNAME  ($($os.Caption) build $($os.BuildNumber))"
Write-Host "Thoi gian: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host "File     : $FilePath  ($((Get-Item -LiteralPath $FilePath).Length) byte)"
Write-Host ''

# ---------- 1. Doc truc tiep file dang mo (doi chung) ----------
Step 'Thu doc TRUC TIEP file dang mo (khong qua VSS)...'
try {
    $fs = [IO.File]::Open($FilePath, 'Open', 'Read', 'ReadWrite')
    $fs.Close()
    $live = Get-FileHash -LiteralPath $FilePath -Algorithm SHA256
    Write-Host "    Doc truc tiep DUOC. SHA-256 = $($live.Hash)"
    Write-Host '    (Word co the cho doc chung; voi file bi khoa doc quyen nhu .mdf/.pst/NTUSER.DAT thi se loi.)'
} catch {
    Write-Host "    Doc truc tiep LOI: $($_.Exception.Message)"
}

$shadow = $null
$linked = $false
try {
    # ---------- 2. Tao shadow copy ----------
    Step "Tao shadow copy cho $Volume (Win32_ShadowCopy.Create, ClientAccessible)..."
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $r = Invoke-CimMethod -ClassName Win32_ShadowCopy -MethodName Create `
        -Arguments @{ Volume = $Volume; Context = 'ClientAccessible' }
    $sw.Stop()
    if ($r.ReturnValue -ne 0) {
        $why = $vssErrors[[int]$r.ReturnValue]
        throw "Win32_ShadowCopy.Create tra ve $($r.ReturnValue): $why"
    }
    $shadow = Get-CimInstance -ClassName Win32_ShadowCopy -Filter "ID='$($r.ShadowID)'"
    Write-Host "    ShadowID     = $($r.ShadowID)"
    Write-Host "    DeviceObject = $($shadow.DeviceObject)"
    Write-Host ("    Tao mat {0:N2} s" -f $sw.Elapsed.TotalSeconds)

    # ---------- 3. Gan ban chup bang mklink /d ----------
    $target = $shadow.DeviceObject.TrimEnd('\') + '\'
    Step "mklink /d $MountPath -> $target"
    $out = cmd /c mklink /d "$MountPath" "$target" 2>&1
    if ($LASTEXITCODE -ne 0) { throw "mklink loi: $out" }
    $linked = $true

    # ---------- 4. Doc file qua ban chup ----------
    $rel = $FilePath.Substring($Volume.Length)
    $snapFile = Join-Path $MountPath $rel
    Step "Doc file qua ban chup: $snapFile"
    $sw.Restart()
    $snapHash = Get-FileHash -LiteralPath $snapFile -Algorithm SHA256
    $sw.Stop()
    $snapItem = Get-Item -LiteralPath $snapFile
    Write-Host "    Doc qua VSS DUOC."
    Write-Host "    SHA-256      = $($snapHash.Hash)"
    Write-Host "    Kich thuoc   = $($snapItem.Length) byte, LastWriteTime = $($snapItem.LastWriteTime)"
    Write-Host ("    Doc + bam mat {0:N3} s" -f $sw.Elapsed.TotalSeconds)

    if ($CopyTo) {
        Copy-Item -LiteralPath $snapFile -Destination $CopyTo
        Write-Host "    Da chep ra $CopyTo (mo bang Word de xac nhan file khong hong)."
    }
}
finally {
    # ---------- 5. Don dep: go link (KHONG de quy) roi xoa shadow copy ----------
    if ($linked -and (Test-Path -LiteralPath $MountPath)) {
        Step "Go link $MountPath (rmdir khong /s - chi xoa link, khong dung vao du lieu)"
        cmd /c rmdir "$MountPath" | Out-Null
    }
    if ($shadow) {
        Step "Xoa shadow copy $($shadow.ID)"
        Remove-CimInstance -InputObject $shadow
        $left = Get-CimInstance -ClassName Win32_ShadowCopy -Filter "ID='$($shadow.ID)'"
        if ($left) { Write-Host '    CANH BAO: shadow copy van con, xoa tay: vssadmin delete shadows /shadow={ID}' }
        else { Write-Host '    Da xoa.' }
    }
}

Step 'XONG. Chup man hinh toan bo cua so nay dan vao docs/vss-test.md.'
