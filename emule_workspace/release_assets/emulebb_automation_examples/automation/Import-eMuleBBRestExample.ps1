#Requires -Version 5.1
Set-StrictMode -Version 2.0

function Get-eMuleBBExampleInstallRoot {
    param([string]$Root)

    if (-not [string]::IsNullOrWhiteSpace($Root)) {
        return [IO.Path]::GetFullPath($Root)
    }

    $examplesRoot = Split-Path -Parent $PSScriptRoot
    return [IO.Path]::GetFullPath((Split-Path -Parent $examplesRoot))
}

function Read-eMuleBBJsonFile {
    param([string]$Path, [string]$Description)

    try {
        return Get-Content -Raw -LiteralPath $Path | ConvertFrom-Json
    } catch {
        throw "$Description is not valid JSON: $Path. $($_.Exception.Message)"
    }
}

function Read-eMuleBBIniSection {
    param([string]$Path, [string]$Section)

    $values = @{}
    $active = $false
    foreach ($rawLine in Get-Content -LiteralPath $Path) {
        $line = ([string]$rawLine).Trim()
        if ([string]::IsNullOrWhiteSpace($line) -or $line.StartsWith(';') -or $line.StartsWith('#')) {
            continue
        }
        if ($line.StartsWith('[') -and $line.EndsWith(']')) {
            $active = [string]::Equals($line.Trim('[', ']'), $Section, [StringComparison]::OrdinalIgnoreCase)
            continue
        }
        if (-not $active) {
            continue
        }
        $equals = $line.IndexOf('=')
        if ($equals -le 0) {
            continue
        }
        $key = $line.Substring(0, $equals).Trim()
        $value = $line.Substring($equals + 1).Trim()
        $values[$key] = $value
    }
    return $values
}

function ConvertTo-eMuleBBLocalHost {
    param([string]$HostName)

    $value = ([string]$HostName).Trim()
    if ([string]::IsNullOrWhiteSpace($value)) {
        return '127.0.0.1'
    }
    if ($value -eq '0.0.0.0' -or $value -eq '*' -or $value -eq '::') {
        return '127.0.0.1'
    }
    return $value
}

function New-eMuleBBRestConnection {
    param([string]$HostName, [int]$Port, [string]$ApiKey)

    if ($Port -le 0) {
        throw "eMuleBB REST port is missing or invalid."
    }
    if ([string]::IsNullOrWhiteSpace($ApiKey)) {
        throw "eMuleBB REST API key is missing."
    }

    $resolvedHost = ConvertTo-eMuleBBLocalHost -HostName $HostName
    return [pscustomobject]@{
        BaseUrl = "http://$resolvedHost`:$Port"
        Headers = @{ 'X-API-Key' = $ApiKey }
        Host = $resolvedHost
        Port = $Port
    }
}

function Get-eMuleBBRestConnection {
    param([string]$Root)

    $installRoot = Get-eMuleBBExampleInstallRoot -Root $Root
    $suiteConfigPath = Join-Path $installRoot 'manifests\suite-config.json'
    if (Test-Path -LiteralPath $suiteConfigPath) {
        $config = Read-eMuleBBJsonFile -Path $suiteConfigPath -Description 'suite-config.json'
        $service = $config.services.emulebb
        $hostName = [string]$service.clientHost
        if ([string]::IsNullOrWhiteSpace($hostName)) {
            $hostName = [string]$service.bindAddress
        }
        return New-eMuleBBRestConnection -HostName $hostName -Port ([int]$service.port) -ApiKey ([string]$service.apiKey)
    }

    $preferencePaths = @(
        (Join-Path $installRoot 'profiles\emulebb\config\preferences.ini'),
        (Join-Path $installRoot 'config\preferences.ini')
    )
    foreach ($path in $preferencePaths) {
        if (-not (Test-Path -LiteralPath $path)) {
            continue
        }
        $webServer = Read-eMuleBBIniSection -Path $path -Section 'WebServer'
        return New-eMuleBBRestConnection -HostName ([string]$webServer['BindAddr']) -Port ([int]$webServer['Port']) -ApiKey ([string]$webServer['ApiKey'])
    }

    throw "Could not find suite-config.json or preferences.ini under $installRoot."
}

function Invoke-eMuleBBRest {
    param(
        [Parameter(Mandatory = $true)]
        $Connection,
        [string]$Method = 'GET',
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [object]$Body = $null
    )

    $uri = "$($Connection.BaseUrl)/api/v1$Path"
    if ($null -eq $Body) {
        return Invoke-RestMethod -Method $Method -Uri $uri -Headers $Connection.Headers -TimeoutSec 30 -ErrorAction Stop
    }

    return Invoke-RestMethod `
        -Method $Method `
        -Uri $uri `
        -Headers $Connection.Headers `
        -ContentType 'application/json' `
        -Body ($Body | ConvertTo-Json -Depth 12) `
        -TimeoutSec 30 `
        -ErrorAction Stop
}

function Get-eMuleBBResponseData {
    param($Response)

    if ($null -ne $Response -and $null -ne $Response.PSObject.Properties['data']) {
        return $Response.data
    }
    return $Response
}
