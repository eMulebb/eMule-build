#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$Root,
    [Parameter(Mandatory = $true)]
    [string]$Query,
    [ValidateSet('automatic', 'server', 'global', 'kad')]
    [string]$Method = 'automatic',
    [ValidateSet('', 'arc', 'audio', 'iso', 'image', 'pro', 'video', 'doc', 'emulecollection')]
    [string]$Type = '',
    [ValidateRange(0, 600)]
    [int]$PollSeconds = 5,
    [ValidateRange(1, 60)]
    [int]$MaxPolls = 6,
    [ValidateRange(1, 1000)]
    [int]$Limit = 20
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Import-eMuleBBRestExample.ps1')

$connection = Get-eMuleBBRestConnection -Root $Root
$created = Get-eMuleBBResponseData (Invoke-eMuleBBRest -Connection $connection -Method POST -Path '/searches' -Body @{
    query = $Query
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

@($search.results) |
    Select-Object -First $Limit searchId, hash, name, sizeBytes, sources, completeSources, fileType
