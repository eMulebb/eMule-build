#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$Root,
    [Parameter(Mandatory = $true)]
    [string]$ReleaseGroup,
    [ValidateSet('automatic', 'server', 'global', 'kad')]
    [string]$Method = 'automatic',
    [ValidateSet('', 'arc', 'audio', 'iso', 'image', 'pro', 'video', 'doc', 'emulecollection')]
    [string]$Type = '',
    [string]$CategoryName = 'release-group',
    [bool]$Paused = $true,
    [ValidateRange(0, 600)]
    [int]$PollSeconds = 5,
    [ValidateRange(1, 60)]
    [int]$MaxPolls = 6,
    [ValidateRange(1, 100)]
    [int]$MaxDownloads = 5,
    [string]$StatePath
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Import-eMuleBBRestExample.ps1')

if ([string]::IsNullOrWhiteSpace($StatePath)) {
    $StatePath = Join-Path (Join-Path $PSScriptRoot 'state') 'release-group-downloads.json'
}

function Read-ReleaseGroupState {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return [pscustomobject]@{ schema = 'emulebb.automation.release-group-state.v1'; seenHashes = @{} }
    }
    $state = Read-eMuleBBJsonFile -Path $Path -Description 'release group automation state'
    if ($null -eq $state.PSObject.Properties['seenHashes']) {
        $state | Add-Member -MemberType NoteProperty -Name seenHashes -Value @{}
    }
    return $state
}

function Save-ReleaseGroupState {
    param([string]$Path, $State)

    $directory = Split-Path -Parent $Path
    if (-not [string]::IsNullOrWhiteSpace($directory)) {
        New-Item -ItemType Directory -Force -Path $directory | Out-Null
    }
    $State | ConvertTo-Json -Depth 10 | Set-Content -Encoding UTF8 -LiteralPath $Path
}

$connection = Get-eMuleBBRestConnection -Root $Root
$created = Get-eMuleBBResponseData (Invoke-eMuleBBRest -Connection $connection -Method POST -Path '/searches' -Body @{
    query = $ReleaseGroup
    method = $Method
    type = $Type
})
$searchId = [string]$created.id
if ([string]::IsNullOrWhiteSpace($searchId)) {
    throw 'The search response did not include an id.'
}

$search = $created
for ($index = 0; $index -lt $MaxPolls; $index++) {
    if ($PollSeconds -gt 0) {
        Start-Sleep -Seconds $PollSeconds
    }
    $search = Get-eMuleBBResponseData (Invoke-eMuleBBRest -Connection $connection -Path "/searches/$searchId")
    if (@($search.results).Count -gt 0 -or [string]$search.status -ne 'running') {
        break
    }
}

$state = Read-ReleaseGroupState -Path $StatePath
$seen = @{}
foreach ($property in @($state.seenHashes.PSObject.Properties)) {
    $seen[$property.Name] = $property.Value
}

$downloaded = @()
$candidates = @($search.results) | Where-Object {
    -not [string]::IsNullOrWhiteSpace([string]$_.hash) -and
        ([string]$_.name).IndexOf($ReleaseGroup, [StringComparison]::OrdinalIgnoreCase) -ge 0 -and
        -not $seen.ContainsKey([string]$_.hash)
} | Sort-Object sources -Descending | Select-Object -First $MaxDownloads

foreach ($item in $candidates) {
    $hash = [string]$item.hash
    [void](Invoke-eMuleBBRest -Connection $connection -Method POST -Path "/searches/$searchId/results/$hash/operations/download" -Body @{
        categoryName = $CategoryName
        paused = [bool]$Paused
    })
    $seen[$hash] = [pscustomobject]@{
        name = [string]$item.name
        releaseGroup = $ReleaseGroup
        downloadedAtUtc = [DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ')
    }
    $downloaded += $item
}

$state.seenHashes = $seen
Save-ReleaseGroupState -Path $StatePath -State $state

$downloaded | Select-Object searchId, hash, name, sizeBytes, sources, completeSources, fileType
