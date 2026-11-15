<#
.SYNOPSIS
    Tuong lua Windows cho PC giu kho (Nguoi B, tuan 3): mac dinh CHAN moi ket noi vao,
    chi mo cong kho (Caddy mTLS, 8443) va web dieu khien (5000) tren card Tailscale.

.DESCRIPTION
    - Set-NetFirewallProfile: 3 profile deu bat, inbound mac dinh Block, outbound Allow.
    - 2 rule Allow gan voi InterfaceAlias cua card Tailscale (mac dinh ten "Tailscale").
    - API kho tho (8080) chi nghe 127.0.0.1 nen khong can rule; them 1 rule Block 8080 tu ngoai cho chac.
    -Undo     : xoa cac rule do script tao (khong doi lai mac dinh profile).
    -PrintOnly: chi in lenh (khong can quyen admin) - dung cho test.
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File deploy\kho\tuong_lua.ps1
    powershell -ExecutionPolicy Bypass -File deploy\kho\tuong_lua.ps1 -InterfaceAlias "Tailscale" -KhoPort 8443 -WebPort 5000
#>
[CmdletBinding()]
param(
    [int]$KhoPort = 8443,
    [int]$WebPort = 5000,
    [int]$RawPort = 8080,
    [string]$InterfaceAlias = 'Tailscale',
    [switch]$Undo,
    [switch]$PrintOnly
)
$ErrorActionPreference = 'Stop'
$rules = @(
    @{ Name = 'BackupSystem - Kho mTLS (Tailscale)'; Port = $KhoPort; Action = 'Allow'; Iface = $InterfaceAlias },
    @{ Name = 'BackupSystem - Web dieu khien (Tailscale)'; Port = $WebPort; Action = 'Allow'; Iface = $InterfaceAlias },
    @{ Name = 'BackupSystem - Chan API kho tho tu ngoai'; Port = $RawPort; Action = 'Block'; Iface = '' }
)

if (-not $PrintOnly) {
    $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $isAdmin) { throw 'Can PowerShell quyen Administrator.' }
}

if ($Undo) {
    foreach ($r in $rules) {
        if ($PrintOnly) { Write-Host "REMOVE rule '$($r.Name)'"; continue }
        Get-NetFirewallRule -DisplayName $r.Name -ErrorAction SilentlyContinue | Remove-NetFirewallRule
        Write-Host "Da xoa rule '$($r.Name)'"
    }
    exit 0
}

Write-Host '== 1. Mac dinh: bat tuong lua 3 profile, CHAN moi ket noi vao, cho moi ket noi ra'
if ($PrintOnly) { Write-Host 'PS Set-NetFirewallProfile -Profile Domain,Private,Public -Enabled True -DefaultInboundAction Block -DefaultOutboundAction Allow' }
else { Set-NetFirewallProfile -Profile Domain, Private, Public -Enabled True -DefaultInboundAction Block -DefaultOutboundAction Allow }

if (-not $PrintOnly) {
    $nic = Get-NetAdapter -Name $InterfaceAlias -ErrorAction SilentlyContinue
    if (-not $nic) { Write-Host "CANH BAO: khong thay card mang '$InterfaceAlias' (Tailscale chua cai?). Rule van duoc tao, co hieu luc khi card xuat hien." }
}

Write-Host "== 2. Chi mo $KhoPort (kho mTLS) va $WebPort (web) tren card '$InterfaceAlias'; chan $RawPort tu ngoai"
foreach ($r in $rules) {
    $p = @{ DisplayName = $r.Name; Direction = 'Inbound'; Protocol = 'TCP'; LocalPort = $r.Port; Action = $r.Action; Profile = 'Any' }
    if ($r.Iface) { $p.InterfaceAlias = $r.Iface }
    $desc = "RULE '$($r.Name)': TCP $($r.Port) $($r.Action)" + $(if ($r.Iface) { " interface=$($r.Iface)" } else { ' (moi card)' })
    if ($PrintOnly) { Write-Host $desc; continue }
    Get-NetFirewallRule -DisplayName $r.Name -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    New-NetFirewallRule @p -Description 'Tao boi deploy\kho\tuong_lua.ps1' | Out-Null
    Write-Host "Da tao $desc"
}
Write-Host 'Kiem tra: Get-NetFirewallProfile | ft Name,Enabled,DefaultInboundAction ; Get-NetFirewallRule -DisplayName "BackupSystem*"'
exit 0
