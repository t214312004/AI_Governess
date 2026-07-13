Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$modelsDir = Join-Path $repoRoot "ai_voice_assistant\models"
$modelName = "sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01"
$targetDir = Join-Path $modelsDir $modelName
$modelRepo = "https://www.modelscope.cn/pkufool/$modelName.git"
$requiredFiles = @(
    "encoder-epoch-12-avg-2-chunk-16-left-64.onnx",
    "decoder-epoch-12-avg-2-chunk-16-left-64.onnx",
    "joiner-epoch-12-avg-2-chunk-16-left-64.onnx",
    "tokens.txt"
)

function Get-MissingModelFiles {
    param([string]$Directory)

    $missing = @()
    foreach ($relativePath in $requiredFiles) {
        $filePath = Join-Path $Directory $relativePath
        if (-not (Test-Path -LiteralPath $filePath -PathType Leaf)) {
            $missing += $relativePath
            continue
        }
        if ((Get-Item -LiteralPath $filePath).Length -le 0) {
            $missing += $relativePath
        }
    }
    return $missing
}

if (Test-Path -LiteralPath $targetDir) {
    $missingFiles = @(Get-MissingModelFiles -Directory $targetDir)
    if ($missingFiles.Count -eq 0) {
        Write-Host "[OK] Complete model already exists: $targetDir"
        exit 0
    }
    throw "Model directory is incomplete. Missing or empty files: $($missingFiles -join ', '). Remove or repair it before retrying: $targetDir"
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "git was not found. Install Git first, then rerun this script."
}

New-Item -ItemType Directory -Force -Path $modelsDir | Out-Null

if (-not (Get-Command git-lfs -ErrorAction SilentlyContinue)) {
    throw "git-lfs was not found. Install Git LFS before downloading the model."
}

git lfs install | Out-Host
if ($LASTEXITCODE -ne 0) {
    throw "git lfs install failed with exit code $LASTEXITCODE."
}

git clone --depth 1 $modelRepo $targetDir
if ($LASTEXITCODE -ne 0) {
    throw "git clone failed with exit code $LASTEXITCODE. Partial files were left for inspection: $targetDir"
}

$missingFiles = @(Get-MissingModelFiles -Directory $targetDir)
if ($missingFiles.Count -gt 0) {
    throw "Model download is incomplete. Missing or empty files: $($missingFiles -join ', '). Clone metadata was preserved for recovery: $targetDir"
}

$nestedGit = Join-Path $targetDir ".git"
if (Test-Path -LiteralPath $nestedGit) {
    Remove-Item -LiteralPath $nestedGit -Recurse -Force
}

Write-Host "[OK] Model downloaded: $targetDir"
