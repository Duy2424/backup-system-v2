<#
.SYNOPSIS
    Cap / thu hoi chung chi cho mTLS cua kho (Nguoi B, tuan 3) - dung openssl (co san trong Git for Windows).

.DESCRIPTION
    Mot CA noi bo ky tat ca:
      -InitCA                 tao certs\ca.key + certs\ca.crt (10 nam) - lam MOT lan
      -Server -San "IP:100.x.y.z,DNS:pc-kho"
                              chung chi cho Caddy (certs\server.crt/.key, 825 ngay). SAN = IP Tailscale cua PC
      -Client <ten-may>       chung chi cho MOT may agent/laptop (certs\clients\<ten>.crt/.key, 825 ngay)
                              -> chep 3 file <ten>.crt, <ten>.key, ca.crt sang may do
      -Revoke <ten-may>       thu hoi: chuyen chung chi vao certs\revoked\, bo khoi danh sach cho phep
    Sau moi lenh, file clients.caddy (allow-list cua Caddy) duoc sinh lai tu certs\clients\*.crt.
    Caddy doc allow-list luc khoi dong -> sau khi them/thu hoi: khoi dong lai Caddy (hoac caddy reload).

    -PrintOnly: chi in cac lenh openssl (khong can openssl) - dung cho test.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File deploy\kho\make_certs.ps1 -InitCA
    powershell -ExecutionPolicy Bypass -File deploy\kho\make_certs.ps1 -Server -San "IP:100.101.102.103,DNS:pc-kho"
    powershell -ExecutionPolicy Bypass -File deploy\kho\make_certs.ps1 -Client laptop-duy
    powershell -ExecutionPolicy Bypass -File deploy\kho\make_certs.ps1 -Revoke laptop-cu
#>
[CmdletBinding()]
param(
    [switch]$InitCA,
    [switch]$Server,
    [string]$San = 'IP:127.0.0.1,DNS:localhost',
    [string]$Client = '',
    [string]$Revoke = '',
    [string]$CaddyDir = '',          # thu muc chua Caddyfile + clients.caddy (mac dinh: thu muc script)
    [string]$OutDir = '',            # thu muc chung chi (mac dinh: <CaddyDir>\certs)
    [int]$Days = 825,
    [switch]$Force,
    [switch]$PrintOnly
)

$ErrorActionPreference = 'Stop'
if (-not $CaddyDir) { $CaddyDir = Split-Path -Parent $MyInvocation.MyCommand.Path }
if (-not $OutDir) { $OutDir = Join-Path $CaddyDir 'certs' }
$clientsDir = Join-Path $OutDir 'clients'
$revokedDir = Join-Path $OutDir 'revoked'
$namePattern = '^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$'

function Find-OpenSsl {
    $c = Get-Command openssl -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    foreach ($p in 'C:\Program Files\Git\mingw64\bin\openssl.exe', 'C:\Program Files\Git\usr\bin\openssl.exe',
                   'C:\Program Files (x86)\Git\mingw64\bin\openssl.exe') {
        if (Test-Path $p) { return $p }
    }
    return $null
}

function Invoke-OpenSsl([string[]]$argv) {
    if ($PrintOnly) { Write-Host ("OPENSSL " + ($argv -join " ")); return }
    & $script:openssl @argv
    if ($LASTEXITCODE -ne 0) { throw "openssl that bai (ma $LASTEXITCODE): $($argv -join " ")" }
}

function Write-Text([string]$path, [string]$text) {
    if ($PrintOnly) { Write-Host "WRITE $path"; Write-Host $text; return }
    [IO.File]::WriteAllText($path, $text, (New-Object Text.UTF8Encoding $false))
}

function New-Dir([string]$p) { if (-not $PrintOnly) { New-Item -ItemType Directory -Force -Path $p | Out-Null } }

function Sign-Cert([string]$name, [string]$keyPath, [string]$crtPath, [string]$ext) {
    # khoa EC P-256 + CSR, roi CA ky kem extension (SAN / clientAuth / serverAuth)
    $csr = Join-Path $OutDir "$name.csr"
    $extFile = Join-Path $OutDir "$name.ext.cnf"
    Write-Text $extFile $ext
    Invoke-OpenSsl @('req', '-new', '-newkey', 'ec', '-pkeyopt', 'ec_paramgen_curve:prime256v1', '-nodes',
                     '-keyout', $keyPath, '-out', $csr, '-subj', "/CN=$name/O=Backup System")
    Invoke-OpenSsl @('x509', '-req', '-in', $csr, '-CA', (Join-Path $OutDir 'ca.crt'), '-CAkey', (Join-Path $OutDir 'ca.key'),
                     '-CAcreateserial', '-out', $crtPath, '-days', "$Days", '-sha256', '-extfile', $extFile)
    if (-not $PrintOnly) { Remove-Item -LiteralPath $csr, $extFile -ErrorAction SilentlyContinue }
}

function Update-AllowList {
    $lines = @('# Danh sach may duoc phep goi API kho (allow-list cua Caddy). FILE NAY DO make_certs.ps1 SINH LAI.',
               '# Moi may mot dong:  trusted_leaf_cert_file certs/clients/<ten>.crt',
               '# Thu hoi = make_certs.ps1 -Revoke <ten> roi khoi dong lai Caddy.',
               "# Cap nhat: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')")
    $certs = @()
    if (Test-Path $clientsDir) { $certs = @(Get-ChildItem -LiteralPath $clientsDir -Filter '*.crt' | Sort-Object Name) }
    if ($PrintOnly -and $Client) { $certs = @([pscustomobject]@{ Name = "$Client.crt" }) }
    foreach ($c in $certs) {
        $rel = ($OutDir.TrimEnd('\') -replace [regex]::Escape($CaddyDir.TrimEnd('\')), '').TrimStart('\') -replace '\\', '/'
        if (-not $rel) { $rel = 'certs' }
        $lines += "trusted_leaf_cert_file $rel/clients/$($c.Name)"
    }
    if ($certs.Count -eq 0) { $lines += '# (chua co may nao - moi chung chi do ca.crt ky deu vao duoc)' }
    Write-Text (Join-Path $CaddyDir 'clients.caddy') (($lines -join "`r`n") + "`r`n")
    Write-Host "Allow-list: $($certs.Count) may -> $(Join-Path $CaddyDir 'clients.caddy')"
}

if (-not ($InitCA -or $Server -or $Client -or $Revoke)) {
    Write-Host 'Chon mot: -InitCA | -Server [-San ...] | -Client <ten> | -Revoke <ten>   (them -PrintOnly de xem lenh)'
    exit 1
}
$script:openssl = Find-OpenSsl
if (-not $PrintOnly -and -not $script:openssl) {
    Write-Host 'Khong tim thay openssl. Cai Git for Windows (co san openssl) hoac them openssl vao PATH.'
    exit 2
}
New-Dir $OutDir
New-Dir $clientsDir

if ($InitCA) {
    $caKey = Join-Path $OutDir 'ca.key'
    if ((Test-Path $caKey) -and -not $Force) {
        Write-Host "CA da co ($caKey). Dung -Force neu muon tao lai (moi chung chi cu se khong con hop le)."
    } else {
        Invoke-OpenSsl @('req', '-x509', '-new', '-newkey', 'ec', '-pkeyopt', 'ec_paramgen_curve:prime256v1', '-nodes',
                         '-keyout', $caKey, '-out', (Join-Path $OutDir 'ca.crt'), '-days', '3650', '-sha256',
                         '-subj', '/CN=Backup Kho CA/O=Backup System',
                         '-addext', 'basicConstraints=critical,CA:TRUE', '-addext', 'keyUsage=critical,keyCertSign,cRLSign')
        Write-Host "Da tao CA: $(Join-Path $OutDir 'ca.crt') (giu ca.key that can than - ai co no la cap duoc chung chi)"
    }
}

if ($Server) {
    if ($San -notmatch '^(IP|DNS):[A-Za-z0-9.:\-]+(,(IP|DNS):[A-Za-z0-9.:\-]+)*$') { Write-Host "SAN khong hop le: $San"; exit 1 }
    $ext = "basicConstraints=CA:FALSE`nkeyUsage=critical,digitalSignature,keyEncipherment`nextendedKeyUsage=serverAuth`nsubjectAltName=$San`n"
    Sign-Cert 'server' (Join-Path $OutDir 'server.key') (Join-Path $OutDir 'server.crt') $ext
    Write-Host "Da tao chung chi Caddy: certs\server.crt (SAN $San). Client xac minh bang ca.crt."
}

if ($Client) {
    if ($Client -notmatch $namePattern) { Write-Host "Ten may khong hop le: $Client (chu, so, . _ -)"; exit 1 }
    $crt = Join-Path $clientsDir "$Client.crt"
    if ((Test-Path $crt) -and -not $Force) { Write-Host "Da co chung chi cho $Client (dung -Force de cap lai)"; exit 1 }
    $ext = "basicConstraints=CA:FALSE`nkeyUsage=critical,digitalSignature`nextendedKeyUsage=clientAuth`n"
    Sign-Cert $Client (Join-Path $clientsDir "$Client.key") $crt $ext
    if (-not $PrintOnly) { Copy-Item -LiteralPath (Join-Path $OutDir 'ca.crt') -Destination (Join-Path $clientsDir 'ca.crt') -Force }
    Write-Host "Da cap chung chi cho $Client. Chep 3 file sang may do (vd C:\backup-certs\):"
    Write-Host "   $crt"
    Write-Host "   $(Join-Path $clientsDir "$Client.key")"
    Write-Host "   $(Join-Path $clientsDir 'ca.crt')"
    Write-Host "Dung: python -m core ... --repo https://<IP Tailscale PC>:8443 --cert <ten>.crt --key <ten>.key --ca ca.crt"
}

if ($Revoke) {
    if ($Revoke -notmatch $namePattern) { Write-Host "Ten may khong hop le: $Revoke"; exit 1 }
    New-Dir $revokedDir
    $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
    $moved = 0
    foreach ($ext in 'crt', 'key') {
        $src = Join-Path $clientsDir "$Revoke.$ext"
        if ($PrintOnly) { Write-Host "MOVE $src -> $(Join-Path $revokedDir "$Revoke.$stamp.$ext")"; $moved++; continue }
        if (Test-Path $src) { Move-Item -LiteralPath $src -Destination (Join-Path $revokedDir "$Revoke.$stamp.$ext"); $moved++ }
    }
    if ($moved -eq 0) { Write-Host "Khong co chung chi nao ten $Revoke"; exit 1 }
    Write-Host "Da thu hoi $Revoke (chuyen vao certs\revoked\). Khoi dong lai Caddy de ap dung."
}

Update-AllowList
exit 0
