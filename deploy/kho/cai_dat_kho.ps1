<#
.SYNOPSIS
    Cai API kho v2 thanh dich vu nen tren PC + cam xoa file kho bang NTFS (Nguoi B, tuan 3).

.DESCRIPTION
    Hai lop chong xoa (ke hoach tuan 3):
      1. API khong co lenh xoa (kho/app.py).
      2. Windows khong cho TAI KHOAN CHAY KHO xoa file: icacls deny (DE,DC) tren packs\, snapshots\, keys\ va file config.
         Tai khoan do la NT AUTHORITY\LOCAL SERVICE (co san, quyen thap, khong can mat khau) - chi duoc THEM file.
         Don kho (prune, tuan 5) chay bang tai khoan quan tri khac nen van xoa duoc khi can.
    Dich vu nen: Scheduled Task \BackupSystem\BackupKho chay luc khoi dong, tu khoi dong lai khi loi (khong can NSSM).
    Co nssm.exe thi them -UseNssm de cai thanh Windows Service that.
    Tuy chon -CaddyExe <duong dan caddy.exe>: cai them task \BackupSystem\BackupKhoCaddy (mTLS, cong 8443).

    -PrintOnly : chi in lenh (khong can quyen admin) - dung cho test.
    -Uninstall : go task/dich vu (KHONG dong vao du lieu kho, KHONG bo icacls).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File deploy\kho\cai_dat_kho.ps1 -KhoDir D:\kho-v2
    powershell -ExecutionPolicy Bypass -File deploy\kho\cai_dat_kho.ps1 -KhoDir D:\kho-v2 -CaddyExe D:\tools\caddy.exe
#>
[CmdletBinding()]
param(
    [string]$KhoDir = 'D:\kho-v2',
    [int]$Port = 8080,
    [string]$RepoDir = '',
    [string]$PythonExe = '',
    [string]$Account = 'NT AUTHORITY\LOCAL SERVICE',
    [string]$TaskName = 'BackupKho',
    [string]$CaddyExe = '',
    [switch]$UseNssm,
    [string]$NssmExe = 'nssm.exe',
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

function Say($m) { Write-Host $m }
function Run([string]$exe, [string[]]$argv) {
    if ($PrintOnly) { Say ("CMD $exe " + ($argv -join " ")); return }
    & $exe @argv
    if ($LASTEXITCODE -ne 0) { throw "$exe that bai (ma $LASTEXITCODE): $($argv -join " ")" }
}

if (-not $PrintOnly) {
    $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $isAdmin) { throw 'Can PowerShell quyen Administrator (icacls + Scheduled Task).' }
}

# SID cua tai khoan (dung cho icacls de khong phu thuoc ngon ngu Windows): LOCAL SERVICE = S-1-5-19
try { $sid = (New-Object Security.Principal.NTAccount($Account)).Translate([Security.Principal.SecurityIdentifier]).Value }
catch { $sid = 'S-1-5-19' }

# ------------------------------------------------------------------ go cai
if ($Uninstall) {
    foreach ($t in $TaskName, "${TaskName}Caddy") {
        if ($PrintOnly) { Say "TASK remove $taskPath$t"; continue }
        $task = Get-ScheduledTask -TaskPath $taskPath -TaskName $t -ErrorAction SilentlyContinue
        if ($task) { Stop-ScheduledTask -InputObject $task -ErrorAction SilentlyContinue; Unregister-ScheduledTask -InputObject $task -Confirm:$false; Say "Da go task $t" }
    }
    if ($UseNssm) { Run $NssmExe @('stop', $TaskName); Run $NssmExe @('remove', $TaskName, 'confirm') }
    Say "Da go dich vu. Du lieu kho van o $KhoDir. Bo cam xoa (neu can):  icacls `"$KhoDir`" /remove:d *$sid /T"
    exit 0
}

# ------------------------------------------------------------------ 1. thu muc kho
Say "== 1. Thu muc kho $KhoDir"
foreach ($d in '', 'packs', 'snapshots', 'keys', 'tmp', 'logs') {
    $p = Join-Path $KhoDir $d
    if ($PrintOnly) { Say "MKDIR $p" } else { New-Item -ItemType Directory -Force -Path $p | Out-Null }
}

# ------------------------------------------------------------------ 2. quyen NTFS: chi duoc THEM
Say "== 2. NTFS: $Account ($sid) duoc ghi them, KHONG duoc xoa trong packs\ snapshots\ keys\ va config"
# doc + tao file/thu muc moi tren ca kho
Run 'icacls.exe' @($KhoDir, '/grant', "*${sid}:(OI)(CI)(RX,W)")
# tmp\ va logs\: duoc xoa (file tam sau khi doi ten, xoay log)
Run 'icacls.exe' @((Join-Path $KhoDir 'tmp'), '/grant', "*${sid}:(OI)(CI)(M)")
Run 'icacls.exe' @((Join-Path $KhoDir 'logs'), '/grant', "*${sid}:(OI)(CI)(M)")
# CAM XOA: DE = delete, DC = delete child. Deny thang grant.
foreach ($d in 'packs', 'snapshots', 'keys') {
    Run 'icacls.exe' @((Join-Path $KhoDir $d), '/deny', "*${sid}:(OI)(CI)(DE,DC)")
}
# file ngay trong thu muc goc (config) khong xoa duoc; khong xoa duoc cac thu muc con cua goc
Run 'icacls.exe' @($KhoDir, '/deny', "*${sid}:(OI)(NP)(IO)(DE)")
Run 'icacls.exe' @($KhoDir, '/deny', "*${sid}:(DC)")
# tai khoan dich vu can doc ma nguon + .venv de chay python
Run 'icacls.exe' @($RepoDir, '/grant', "*${sid}:(OI)(CI)(RX)")

# ------------------------------------------------------------------ 3. dich vu nen
$khoArgs = "-B -m kho --kho `"$KhoDir`" --host 127.0.0.1 --port $Port"
if ($UseNssm) {
    Say "== 3. Windows Service $TaskName (NSSM) chay bang $Account"
    Run $NssmExe @('install', $TaskName, $PythonExe, $khoArgs)
    Run $NssmExe @('set', $TaskName, 'AppDirectory', $RepoDir)
    Run $NssmExe @('set', $TaskName, 'ObjectName', $Account)
    Run $NssmExe @('set', $TaskName, 'AppStdout', (Join-Path $KhoDir 'logs\service.out.log'))
    Run $NssmExe @('set', $TaskName, 'AppStderr', (Join-Path $KhoDir 'logs\service.err.log'))
    Run $NssmExe @('set', $TaskName, 'AppRotateFiles', '1')
    Run $NssmExe @('set', $TaskName, 'Start', 'SERVICE_AUTO_START')
    Run $NssmExe @('start', $TaskName)
} else {
    Say "== 3. Scheduled Task $taskPath$TaskName (luc khoi dong, chay bang $Account, tu khoi dong lai)"
    if ($PrintOnly) {
        Say "TASK $taskPath$TaskName [AtStartup] ${Account}: $PythonExe $khoArgs  (cwd $RepoDir)"
    } else {
        $action = New-ScheduledTaskAction -Execute $PythonExe -Argument $khoArgs -WorkingDirectory $RepoDir
        $trigger = New-ScheduledTaskTrigger -AtStartup
        $principal = New-ScheduledTaskPrincipal -UserId $Account -LogonType ServiceAccount -RunLevel Limited
        $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
            -ExecutionTimeLimit (New-TimeSpan -Seconds 0) -MultipleInstances IgnoreNew
        Register-ScheduledTask -TaskPath $taskPath -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal `
            -Settings $settings -Description "API kho backup v2 (chi them, khong xoa) - 127.0.0.1:$Port" -Force | Out-Null
        Start-ScheduledTask -TaskPath $taskPath -TaskName $TaskName
    }
}

# ------------------------------------------------------------------ 4. Caddy (mTLS) - tuy chon
if ($CaddyExe) {
    Say "== 4. Caddy mTLS: task $taskPath${TaskName}Caddy chay '$CaddyExe run --config Caddyfile' trong $here"
    foreach ($f in 'certs\server.crt', 'certs\server.key', 'certs\ca.crt') {
        if (-not $PrintOnly -and -not (Test-Path (Join-Path $here $f))) { throw "Thieu $f - chay make_certs.ps1 -InitCA roi -Server truoc" }
    }
    if ($PrintOnly) {
        Say "TASK $taskPath${TaskName}Caddy [AtStartup] ${Account}: $CaddyExe run --config Caddyfile  (cwd $here)"
    } else {
        New-Item -ItemType Directory -Force -Path (Join-Path $here 'logs') | Out-Null
        & icacls.exe $here /grant "*${sid}:(OI)(CI)(RX)" | Out-Null
        & icacls.exe (Join-Path $here 'logs') /grant "*${sid}:(OI)(CI)(M)" | Out-Null
        $action = New-ScheduledTaskAction -Execute $CaddyExe -Argument 'run --config Caddyfile' -WorkingDirectory $here
        $principal = New-ScheduledTaskPrincipal -UserId $Account -LogonType ServiceAccount -RunLevel Limited
        $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
            -ExecutionTimeLimit (New-TimeSpan -Seconds 0) -MultipleInstances IgnoreNew
        Register-ScheduledTask -TaskPath $taskPath -TaskName "${TaskName}Caddy" -Action $action -Trigger (New-ScheduledTaskTrigger -AtStartup) `
            -Principal $principal -Settings $settings -Description 'Caddy mTLS truoc API kho (cong 8443)' -Force | Out-Null
        Start-ScheduledTask -TaskPath $taskPath -TaskName "${TaskName}Caddy"
    }
}

# ------------------------------------------------------------------ 5. kiem tra
if (-not $PrintOnly) {
    Start-Sleep -Seconds 4
    try {
        $h = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 5
        Say ("== 5. Kho dang chay: {0} pack, {1} snapshot, {2}" -f $h.packs, $h.snapshots, $(if ($h.initialized) { 'da init' } else { 'CHUA init' }))
    } catch {
        Say "== 5. Chua goi duoc http://127.0.0.1:$Port/health - xem $KhoDir\logs\kho.log (task co the con dang khoi dong)"
    }
}
Say ''
Say 'Tiep theo:'
Say "  - Chua init: .venv\Scripts\python -m core init --repo http://127.0.0.1:$Port   (tren PC, mat khau kho cat ky)"
Say '  - mTLS: make_certs.ps1 -InitCA ; -Server -San "IP:<IP Tailscale>" ; -Client <ten may>  roi chay Caddy (hoac -CaddyExe)'
Say '  - Tuong lua: tuong_lua.ps1 (chi mo 8443 tren card Tailscale)'
Say "  - Thu cam xoa: mo PowerShell quyen thuong, chay  icacls `"$KhoDir\packs`"  -> thay dong Deny cho $Account"
exit 0
