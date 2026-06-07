# eMuleBB REST Automation Examples

These examples show how to call the trusted local eMuleBB REST API from Windows
PowerShell 5.1.

Run them from the installed suite folder:

```powershell
cd C:\eMuleBBSuite
.\examples\automation\Get-eMuleBBStatus.ps1
```

The scripts read REST bind information and the API key from the installed suite
configuration first:

```text
manifests\suite-config.json
```

If that file is not available, they try the eMuleBB profile preferences:

```text
profiles\emulebb\config\preferences.ini
config\preferences.ini
```

Examples:

```powershell
.\examples\automation\Get-eMuleBBStatus.ps1
.\examples\automation\Set-eMuleBBLimits.ps1 -UploadLimitKiBps 2048 -DownloadLimitKiBps 8192
.\examples\automation\Search-eMuleBB.ps1 -Query 'ubuntu iso' -Method global
.\examples\automation\Download-ReleaseGroup.ps1 -ReleaseGroup 'RELEASE_GROUP' -Paused $true
```

`Download-ReleaseGroup.ps1` stores seen result hashes under
`examples\automation\state` so repeated runs do not download the same result
hash twice. It is an on-demand example only. Use your own authorized search
terms and review results before broad automation.
