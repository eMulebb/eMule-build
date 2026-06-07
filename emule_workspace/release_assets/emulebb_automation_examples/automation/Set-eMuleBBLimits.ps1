#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$Root,
    [ValidateRange(1, 4294967294)]
    [UInt32]$UploadLimitKiBps,
    [ValidateRange(1, 4294967294)]
    [UInt32]$DownloadLimitKiBps
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Import-eMuleBBRestExample.ps1')

$body = @{}
if ($PSBoundParameters.ContainsKey('UploadLimitKiBps')) {
    $body.uploadLimitKiBps = [UInt32]$UploadLimitKiBps
}
if ($PSBoundParameters.ContainsKey('DownloadLimitKiBps')) {
    $body.downloadLimitKiBps = [UInt32]$DownloadLimitKiBps
}
if ($body.Count -eq 0) {
    throw 'Pass -UploadLimitKiBps, -DownloadLimitKiBps, or both.'
}

$connection = Get-eMuleBBRestConnection -Root $Root
Get-eMuleBBResponseData (Invoke-eMuleBBRest -Connection $connection -Method PATCH -Path '/app/preferences' -Body $body)
