#Requires -Version 5.1
<#
.SYNOPSIS
    Seeds qBittorrentBB's qBittorrent.ini for suite use: WebUI on the local
    control-plane address, the BitTorrent data plane bound to the live VPN tunnel
    IP, and a WebUI password aMuTorrent can authenticate with.

.DESCRIPTION
    qBittorrentBB binding rules (HARD): the WebUI / control plane binds the local
    address (X_LOCAL_IP); the BitTorrent / DHT data plane binds the hide.me VPN
    tunnel via Session\InterfaceAddress (Session\Interface left EMPTY). The tunnel
    IPv4 rotates, so -VpnInterfaceAddress must be re-resolved and this re-run (or
    just the data-plane part) before every launch -- Start-Suite does that.

    This script is idempotent: it updates the relevant keys in place and creates
    the file/sections if missing. It does NOT touch unrelated keys.

.NOTES
    Local single-user trust model, consistent with the rest of the suite
    installer. Secrets are passed as parameters by the installer, not stored here.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ConfigPath,        # ...\qBittorrentBB\profile\qBittorrent\config\qBittorrent.ini
    [Parameter(Mandatory = $true)][string]$WebUiAddress,      # X_LOCAL_IP (control plane); never 0.0.0.0/127.0.0.1 on the operator box
    [Parameter(Mandatory = $true)][int]$WebUiPort,
    [Parameter(Mandatory = $true)][string]$Username,
    [Parameter(Mandatory = $true)][string]$Password,          # plaintext; hashed here (PBKDF2-HMAC-SHA512)
    [Parameter(Mandatory = $true)][string]$VpnInterfaceAddress, # live hide.me tunnel IPv4 (re-resolve before each launch)
    [int]$BtListenPort = 0,                                   # 0 = leave qBittorrent's existing/auto value
    [string]$AuthSubnetWhitelist = ''                         # optional CIDR allowed to skip WebUI auth (e.g. the LAN)
)

$ErrorActionPreference = 'Stop'

# qBittorrent stores the WebUI password as PBKDF2-HMAC-SHA512, 100000 iterations,
# 16-byte salt, 64-byte derived key, serialized as @ByteArray(saltB64:hashB64).
function Get-QbtPasswordPbkdf2 {
    param([string]$PlainPassword)

    $salt = New-Object byte[] 16
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($salt)
    $pwdBytes = [System.Text.Encoding]::UTF8.GetBytes($PlainPassword)
    $kdf = [System.Security.Cryptography.Rfc2898DeriveBytes]::new(
        $pwdBytes, $salt, 100000, [System.Security.Cryptography.HashAlgorithmName]::SHA512)
    try { $derived = $kdf.GetBytes(64) } finally { $kdf.Dispose() }
    $saltB64 = [Convert]::ToBase64String($salt)
    $hashB64 = [Convert]::ToBase64String($derived)
    return "@ByteArray($saltB64`:$hashB64)"
}

# Minimal Qt-INI writer: idempotent set of "Key=Value" under "[Section]".
function Set-IniValue {
    param([System.Collections.Generic.List[string]]$Lines, [string]$Section, [string]$Key, [string]$Value)

    $sectionHeader = "[$Section]"
    $sectionStart = -1
    $sectionEnd = $Lines.Count
    for ($i = 0; $i -lt $Lines.Count; $i++) {
        if ($Lines[$i].Trim() -eq $sectionHeader) { $sectionStart = $i; continue }
        if (($sectionStart -ge 0) -and ($Lines[$i].Trim() -match '^\[.+\]$')) { $sectionEnd = $i; break }
    }
    if ($sectionStart -lt 0) {
        if (($Lines.Count -gt 0) -and ($Lines[$Lines.Count - 1].Trim() -ne '')) { $Lines.Add('') }
        $Lines.Add($sectionHeader)
        $Lines.Add("$Key=$Value")
        return
    }
    for ($i = $sectionStart + 1; $i -lt $sectionEnd; $i++) {
        if ($Lines[$i] -match "^\s*$([regex]::Escape($Key))\s*=") { $Lines[$i] = "$Key=$Value"; return }
    }
    $Lines.Insert($sectionEnd, "$Key=$Value")
}

if ([string]::IsNullOrWhiteSpace($WebUiAddress) -or ($WebUiAddress -in @('0.0.0.0', '127.0.0.1', 'localhost'))) {
    throw "WebUiAddress must be a concrete local (X_LOCAL_IP) address, not '$WebUiAddress'."
}

$configDir = Split-Path -Parent $ConfigPath
if (-not (Test-Path $configDir)) { New-Item -ItemType Directory -Force -Path $configDir | Out-Null }

$lines = [System.Collections.Generic.List[string]]::new()
if (Test-Path $ConfigPath) { Get-Content -LiteralPath $ConfigPath | ForEach-Object { $lines.Add($_) } }

# WebUI / control plane (binds the local address).
Set-IniValue $lines 'Preferences' 'WebUI\Enabled' 'true'
Set-IniValue $lines 'Preferences' 'WebUI\Address' $WebUiAddress
Set-IniValue $lines 'Preferences' 'WebUI\Port' "$WebUiPort"
Set-IniValue $lines 'Preferences' 'WebUI\Username' $Username
Set-IniValue $lines 'Preferences' 'WebUI\Password_PBKDF2' "`"$(Get-QbtPasswordPbkdf2 -PlainPassword $Password)`""
Set-IniValue $lines 'Preferences' 'WebUI\LocalHostAuth' 'false'
# aMuTorrent talks cross-host to the WebUI; relax the host-header / CSRF gates.
Set-IniValue $lines 'Preferences' 'WebUI\HostHeaderValidation' 'false'
Set-IniValue $lines 'Preferences' 'WebUI\CSRFProtection' 'false'
if (-not [string]::IsNullOrWhiteSpace($AuthSubnetWhitelist)) {
    Set-IniValue $lines 'Preferences' 'WebUI\AuthSubnetWhitelistEnabled' 'true'
    Set-IniValue $lines 'Preferences' 'WebUI\AuthSubnetWhitelist' $AuthSubnetWhitelist
}

# BitTorrent / DHT data plane: bind the live VPN tunnel IP; Interface stays EMPTY.
Set-IniValue $lines 'BitTorrent' 'Session\Interface' ''
Set-IniValue $lines 'BitTorrent' 'Session\InterfaceName' ''
Set-IniValue $lines 'BitTorrent' 'Session\InterfaceAddress' $VpnInterfaceAddress
if ($BtListenPort -gt 0) { Set-IniValue $lines 'BitTorrent' 'Session\Port' "$BtListenPort" }

Set-Content -LiteralPath $ConfigPath -Value $lines -Encoding UTF8
Write-Host "Seeded qBittorrentBB config: $ConfigPath (WebUI $WebUiAddress`:$WebUiPort, VPN bind $VpnInterfaceAddress)"
