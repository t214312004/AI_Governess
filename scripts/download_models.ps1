Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$modelsDir = Join-Path $repoRoot "ai_voice_assistant\models"
$modelName = "sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01"
$targetDir = Join-Path $modelsDir $modelName
$modelRepo = "https://www.modelscope.cn/pkufool/$modelName.git"

if (Test-Path -LiteralPath $targetDir) {
    Write-Host "[OK] Model already exists: $targetDir"
    exit 0
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "git was not found. Install Git first, then rerun this script."
}

New-Item -ItemType Directory -Force -Path $modelsDir | Out-Null

if (Get-Command git-lfs -ErrorAction SilentlyContinue) {
    git lfs install | Out-Host
} else {
    Write-Warning "git-lfs was not found. The clone may not download large model files correctly."
}

git clone --depth 1 $modelRepo $targetDir

$nestedGit = Join-Path $targetDir ".git"
if (Test-Path -LiteralPath $nestedGit) {
    Remove-Item -LiteralPath $nestedGit -Recurse -Force
}

Write-Host "[OK] Model downloaded: $targetDir"
