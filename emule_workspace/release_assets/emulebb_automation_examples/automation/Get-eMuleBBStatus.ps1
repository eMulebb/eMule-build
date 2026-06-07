#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$Root
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Import-eMuleBBRestExample.ps1')

$connection = Get-eMuleBBRestConnection -Root $Root
$app = Get-eMuleBBResponseData (Invoke-eMuleBBRest -Connection $connection -Path '/app')
$status = Get-eMuleBBResponseData (Invoke-eMuleBBRest -Connection $connection -Path '/status')
$transfers = Get-eMuleBBResponseData (Invoke-eMuleBBRest -Connection $connection -Path '/transfers')

[pscustomobject]@{
    BaseUrl = $connection.BaseUrl
    App = $app
    Status = $status
    Transfers = $transfers
}
