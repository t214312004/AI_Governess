param(
    [Parameter(Mandatory=$true)][string]$InputPsd,
    [ValidateSet('governess','compatibility')][string]$Model = 'governess'
)
$ErrorActionPreference = 'Stop'
$labRoot = Split-Path -Parent $PSScriptRoot
$inputPath = (Resolve-Path -LiteralPath $InputPsd).Path
$executable = Join-Path $labRoot 'vendor/psd2live/PSD2Live.exe'
$outputPath = Join-Path $labRoot "models/$Model"
$reportPath = Join-Path $labRoot 'reports/g1'
New-Item -ItemType Directory -Path $outputPath,$reportPath -Force | Out-Null
$arguments = @('--input', ('"' + $inputPath + '"'), '--output', ('"' + $outputPath + '"'), '--lang', 'en', '--atlas', '2048', '--no-see-through')
$process = Start-Process -FilePath $executable -ArgumentList $arguments -WindowStyle Hidden -PassThru -Wait -RedirectStandardOutput (Join-Path $reportPath "$Model-export.log") -RedirectStandardError (Join-Path $reportPath "$Model-export-error.log")
if ($process.ExitCode -ne 0) { throw "PSD2Live export failed: $($process.ExitCode)" }
Write-Output "Exported $Model. Inspect in the official runtime before acceptance."
