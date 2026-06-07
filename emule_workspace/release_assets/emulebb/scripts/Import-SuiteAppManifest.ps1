#Requires -Version 5.1

function ConvertTo-SuiteManifestStringArray {
    param([object]$Value)
    $items = @()
    foreach ($item in @($Value)) {
        if (-not [string]::IsNullOrWhiteSpace([string]$item)) {
            $items += [string]$item
        }
    }
    return $items
}

function ConvertTo-SuiteAppManifest {
    param([object]$Payload, [string]$Path = '')
    if ($null -eq $Payload) {
        throw "suite app manifest is empty: $Path"
    }
    if ($null -eq $Payload.PSObject.Properties['schema'] -or [string]$Payload.schema -ne 'emulebb.suite-apps.v1') {
        throw "suite app manifest has an unsupported schema: $Path"
    }
    if ($null -eq $Payload.PSObject.Properties['arrApps']) {
        throw "suite app manifest does not contain arrApps: $Path"
    }

    $arrNames = @()
    $arrMetadata = @{}
    $dependencyPins = @{}
    $indexerCategories = @{}
    foreach ($entry in @($Payload.arrApps)) {
        $keyProperty = $entry.PSObject.Properties['key']
        if ($null -eq $keyProperty) {
            continue
        }
        $key = ([string]$keyProperty.Value).ToLowerInvariant()
        if ([string]::IsNullOrWhiteSpace($key)) {
            continue
        }

        $arrNames += $key
        $arrMetadata[$key] = @{
            DisplayName = [string]$entry.displayName
            Exe = [string]$entry.exe
            ApiPath = [string]$entry.apiPath
            DataDir = [string]$entry.dataDir
            MediaRoot = [string]$entry.mediaRoot
        }

        $dependencyProperty = $entry.PSObject.Properties['dependency']
        if ($null -ne $dependencyProperty -and $null -ne $dependencyProperty.Value) {
            $dependency = $dependencyProperty.Value
            $dependencyPins[$key] = @{
                Repo = [string]$dependency.repo
                Tag = [string]$dependency.tag
                Pattern = [string]$dependency.assetPattern
                Exe = [string]$dependency.exe
                Url = [string]$dependency.url
                Sha256 = [string]$dependency.sha256
            }
        }

        $categoryProperty = $entry.PSObject.Properties['indexerCategories']
        if ($null -ne $categoryProperty -and $null -ne $categoryProperty.Value) {
            $categories = @()
            foreach ($category in @($categoryProperty.Value)) {
                if (-not [string]::IsNullOrWhiteSpace([string]$category)) {
                    $categories += [int]$category
                }
            }
            if ($categories.Count -gt 0) {
                $indexerCategories[$key] = $categories
            }
        }
    }
    if ($arrNames.Count -eq 0) {
        throw "suite app manifest does not define any Arr apps: $Path"
    }

    $nodeArchives = @{}
    $nodeVersion = ''
    $minimumNodeMajor = $null
    if ($null -ne $Payload.PSObject.Properties['node'] -and $null -ne $Payload.node) {
        if ($null -ne $Payload.node.PSObject.Properties['version']) {
            $nodeVersion = [string]$Payload.node.version
        }
        if ($null -ne $Payload.node.PSObject.Properties['minimumMajor']) {
            $minimumNodeMajor = [int]$Payload.node.minimumMajor
        }
        if ($null -ne $Payload.node.PSObject.Properties['archives']) {
            foreach ($property in $Payload.node.archives.PSObject.Properties) {
                $nodeArchives[$property.Name] = @{
                    FileName = [string]$property.Value.fileName
                    Sha256 = [string]$property.Value.sha256
                }
            }
        }
    }

    return [ordered]@{
        AllArrAppNames = $arrNames
        ArrAppMetadata = $arrMetadata
        PinnedDependencies = $dependencyPins
        ArrIndexerCategories = $indexerCategories
        CoreServiceNames = if ($null -ne $Payload.PSObject.Properties['coreServiceNames']) { ConvertTo-SuiteManifestStringArray -Value $Payload.coreServiceNames } else { @() }
        ControllerServiceNames = if ($null -ne $Payload.PSObject.Properties['controllerServiceNames']) { ConvertTo-SuiteManifestStringArray -Value $Payload.controllerServiceNames } else { @() }
        DefaultArrAppNames = if ($null -ne $Payload.PSObject.Properties['defaultArrAppNames']) { ConvertTo-SuiteManifestStringArray -Value $Payload.defaultArrAppNames } else { @() }
        SuiteServiceOrder = if ($null -ne $Payload.PSObject.Properties['suiteServiceOrder']) { ConvertTo-SuiteManifestStringArray -Value $Payload.suiteServiceOrder } else { @() }
        NodeVersion = $nodeVersion
        MinimumNodeMajor = $minimumNodeMajor
        NodeArchives = $nodeArchives
    }
}

function Read-SuiteAppManifest {
    param([string]$Path)
    try {
        $payload = Get-Content -Raw -LiteralPath $Path | ConvertFrom-Json
    } catch {
        throw "suite app manifest is not valid JSON: $Path. $($_.Exception.Message)"
    }
    return ConvertTo-SuiteAppManifest -Payload $payload -Path $Path
}
