$ErrorActionPreference = 'Stop'
$labRoot = Split-Path -Parent $PSScriptRoot
$vendorRoot = Join-Path $labRoot 'vendor'
New-Item -ItemType Directory -Path $vendorRoot -Force | Out-Null
$lock = Get-Content (Join-Path $PSScriptRoot 'dependencies.lock.json') -Raw -Encoding UTF8 | ConvertFrom-Json
foreach ($property in $lock.PSObject.Properties) {
    $dependency = $property.Value
    $archive = Join-Path $vendorRoot $dependency.file
    if (-not (Test-Path -LiteralPath $archive)) { Invoke-WebRequest -Uri $dependency.url -OutFile $archive }
    $actual = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $dependency.sha256) { throw "Checksum mismatch: $archive" }
    $destination = Join-Path $vendorRoot $dependency.directory
    if (-not (Test-Path -LiteralPath $destination)) { Expand-Archive -LiteralPath $archive -DestinationPath $destination }
    Write-Output ("Verified {0} {1}" -f $property.Name, $dependency.version)
}
