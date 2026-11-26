param(
    [Parameter(Mandatory)][string]$Manifest,
    [string]$InstallRoot = 'D:\MApp\Chaessi Reader'
)
$ErrorActionPreference = 'Stop'
$inventory = Get-Content -Raw -LiteralPath $Manifest -Encoding UTF8 | ConvertFrom-Json
$basePath = (Resolve-Path -LiteralPath $InstallRoot).Path
$separator = [IO.Path]::DirectorySeparatorChar
$prefix = $basePath.TrimEnd($separator) + $separator
$checked = 0
foreach ($entry in $inventory.payload.PSObject.Properties) {
    $fullPath = [IO.Path]::GetFullPath((Join-Path $basePath $entry.Name))
    if (-not $fullPath.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Invalid relative path in packaging manifest'
    }
    if ((Get-FileHash -LiteralPath $fullPath -Algorithm SHA256).Hash -ne $entry.Value) {
        throw ('Installed file mismatch: ' + $entry.Name)
    }
    $checked += 1
}
[pscustomobject]@{
    ApplicationVersion = $inventory.app
    ExtensionVersion = $inventory.extension
    VerifiedPayloadFiles = $checked
    Result = 'PASS'
}
