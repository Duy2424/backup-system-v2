<#
.SYNOPSIS
    Chuan bi demo tren MOT may (tuan 8): .venv, du lieu mau, kho v2 + mat khau, tai khoan admin, bien moi truong.
    Sau do chay deploy\demo\demo_1_may.bat de mo 3 cua so (kho, server, agent) va trinh duyet.

.DESCRIPTION
    Moi thu nam trong -Root (mac dinh D:\DemoBackup), khong dong vao file trong repo:
      kho\         kho v2 (API kho chay tren 127.0.0.1:8080)
      DuLieu\      du lieu mau de sao luu (du_lieu_mau\ sinh boi bench\make_dataset.py + cau_hinh_mau\ + file moi ~bks_canary*)
      server\      CSDL web + instance;  work\  thu muc tam;  secrets\kho.txt  mat khau kho (chi may nay giu)
      demo.env.cmd bien moi truong cho demo_1_may.bat (token agent, duong dan, ENGINE=v2 ...)
    Khong can quyen Administrator (demo khong doi IP/firewall). Chay lai duoc nhieu lan (bo qua phan da co).
    -Reset : xoa -Root roi lam lai tu dau (demo "sach").
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File deploy\demo\chuan_bi_demo.ps1
    powershell -ExecutionPolicy Bypass -File deploy\demo\chuan_bi_demo.ps1 -Reset -DataSize 100MB
#>
[CmdletBinding()]
param(
    [string]$Root = 'D:\DemoBackup',
    [int]$KhoPort = 8080,
    [int]$WebPort = 5000,
    [string]$AdminPassword = 'demo12345',
    [string]$DataSize = '50MB',
    [switch]$Reset
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) '..\..')).Path
Set-Location $repo
if ($AdminPassword.Length -lt 8 -or $AdminPassword -match "['`"]") { throw 'Mat khau admin >= 8 ky tu, khong chua dau nhay' }

# ------------------------------------------------------------------ 1. Python + .venv
$py = Join-Path $repo '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) {
    Write-Host '== 1. Tao .venv va cai thu vien (lan dau, can Internet) ...'
    $boot = $null
    foreach ($c in @('py -3.11', 'python')) {
        cmd /c "$c --version >nul 2>&1"
        if ($LASTEXITCODE -eq 0) { $boot = $c; break }
    }
    if (-not $boot) { throw 'Chua co Python 3.11 - cai tu https://www.python.org/downloads/windows/ roi chay lai' }
    cmd /c "$boot -m venv .venv"
    & $py -m pip install --disable-pip-version-check -q -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'pip install that bai' }
} else { Write-Host "== 1. .venv da co ($py)" }

# ------------------------------------------------------------------ 2. thu muc demo
if ($Reset -and (Test-Path $Root)) { Write-Host "== Reset: xoa $Root"; Remove-Item -Recurse -Force -LiteralPath $Root }
foreach ($d in '', 'kho', 'DuLieu', 'server', 'work', 'secrets', 'logs') {
    New-Item -ItemType Directory -Force -Path (Join-Path $Root $d) | Out-Null
}
Write-Host "== 2. Thu muc demo: $Root"

# ------------------------------------------------------------------ 3. du lieu mau
$data = Join-Path $Root 'DuLieu'
$mau = Join-Path $data 'du_lieu_mau'
if (-not (Test-Path $mau)) {
    Write-Host "== 3. Sinh du lieu mau $DataSize (tat dinh, seed 2026) vao $mau ..."
    & $py bench\make_dataset.py --out $mau --size $DataSize --seed 2026
    if ($LASTEXITCODE -ne 0) { throw 'make_dataset that bai' }
} else { Write-Host "== 3. Du lieu mau da co: $mau" }
$cfgMau = Join-Path $data 'cau_hinh_mau'
if (-not (Test-Path $cfgMau)) { Copy-Item -Recurse -LiteralPath (Join-Path $repo 'agent\sample_data') -Destination $cfgMau }
$canary = Join-Path $data '~bks_canary_dung_sua.txt'
if (-not (Test-Path $canary)) {
    [IO.File]::WriteAllText($canary, "File moi (canary) - KHONG AI DUOC SUA.`r`nNoi dung doi = dau hieu ransomware -> cong chan dung sao luu.`r`n")
}

# ------------------------------------------------------------------ 4. mat khau kho (chi may nay giu, server web khong biet)
$pwFile = Join-Path $Root 'secrets\kho.txt'
if (-not (Test-Path $pwFile)) {
    $chars = 'abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789'
    $pw = -join (1..24 | ForEach-Object { $chars[(Get-Random -Maximum $chars.Length)] })
    [IO.File]::WriteAllText($pwFile, $pw)
    Write-Host "== 4. Da tao mat khau kho: $pwFile (mat file = mat du lieu kho)"
} else { Write-Host "== 4. Mat khau kho da co: $pwFile" }

# ------------------------------------------------------------------ 5. init kho (truc tiep tren thu muc, cung bo cuc voi API kho)
$kho = Join-Path $Root 'kho'
if (-not (Test-Path (Join-Path $kho 'config'))) {
    Write-Host '== 5. Khoi tao kho v2 ...'
    & $py -m core init --repo $kho --password-file $pwFile
    if ($LASTEXITCODE -ne 0) { throw 'core init that bai' }
} else { Write-Host "== 5. Kho da init: $kho" }

# ------------------------------------------------------------------ 6. CSDL web + token admin (khong can server chay)
$env:BACKUP_DB = Join-Path $Root 'server\backup_system.db'
$env:BACKUP_STORAGE_DIR = Join-Path $Root 'server\storage'
$env:BACKUP_INSTANCE_DIR = Join-Path $Root 'server\instance'
$env:BACKUP_WORK_DIR = Join-Path $Root 'work'
$token = (& $py -c "from shared import database; database.init_db('$AdminPassword'); print(database.get_user_by_username('admin')['token'])" | Select-Object -Last 1).Trim()
if ($LASTEXITCODE -ne 0 -or -not $token) { throw 'Khong tao duoc CSDL web / token admin' }
Write-Host '== 6. Tai khoan web: admin / (mat khau da chon). Token agent da lay.'

# ------------------------------------------------------------------ 7. bien moi truong cho demo_1_may.bat
$envFile = Join-Path $Root 'demo.env.cmd'
$lines = @(
    '@echo off',
    "set DEMO_ROOT=$Root",
    "set DEMO_DATA=$data",
    "set KHO_DIR=$kho",
    "set KHO_PORT=$KhoPort",
    "set BACKUP_HOST=127.0.0.1",
    "set BACKUP_PORT=$WebPort",
    "set BACKUP_DB=$env:BACKUP_DB",
    "set BACKUP_STORAGE_DIR=$env:BACKUP_STORAGE_DIR",
    "set BACKUP_INSTANCE_DIR=$env:BACKUP_INSTANCE_DIR",
    "set BACKUP_WORK_DIR=$env:BACKUP_WORK_DIR",
    "set BACKUP_KHO_URL=http://127.0.0.1:$KhoPort",
    "set BACKUP_RPO_HOURS=24",
    "set BACKUP_SERVER_URL=http://127.0.0.1:$WebPort",
    "set BACKUP_AGENT_TOKEN=$token",
    'set BACKUP_ENGINE=v2',
    "set BACKUP_V2_REPO=http://127.0.0.1:$KhoPort",
    "set BACKUP_V2_PASSWORD_FILE=$pwFile",
    "set BACKUP_V2_NOTIFY_URL=http://127.0.0.1:$WebPort/api/notify?token=$token"
)
[IO.File]::WriteAllLines($envFile, $lines, (New-Object Text.ASCIIEncoding))
Write-Host "== 7. Da ghi $envFile"

Write-Host ''
Write-Host 'XONG. Chay demo:   deploy\demo\demo_1_may.bat'
Write-Host "  Web      : http://127.0.0.1:$WebPort   (admin / $AdminPassword)"
Write-Host "  Du lieu  : $data   (sao luu thu muc nay; xoa thu 1 thu muc con roi khoi phuc)"
Write-Host "  Kho      : http://127.0.0.1:$KhoPort/health   (thu muc $kho)"
Write-Host "  K5 thu xoa: .venv\Scripts\python bench\dien_tap.py k5 --repo http://127.0.0.1:$KhoPort --password-file $pwFile"
Write-Host "  K1 ransom : deploy\demo\gia_ransomware.ps1 -Data $data   roi bam Sao luu tren web"
Write-Host '  Telegram : Cai dat > Thong bao Telegram (token tu @BotFather, nhan /id cho bot de lay chat ID)'
