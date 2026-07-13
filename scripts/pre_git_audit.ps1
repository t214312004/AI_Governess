Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

if (-not (Test-Path -LiteralPath ".gitignore")) {
    throw ".gitignore is missing. Do not run git add until it exists."
}

$privatePaths = @(
    "ai_voice_assistant\config.local.json",
    "ai_voice_assistant\logs",
    "ai_voice_assistant\schedule_state",
    "ai_voice_assistant\whiteboard_state",
    "ai_voice_assistant\whisper_audio_archive",
    "ai_voice_assistant\voice_profiles",
    "ai_voice_assistant\agent_workspace",
    "ai_voice_assistant\models",
    "ai_voice_assistant\venv",
    "ai_voice_assistant\.venv-bluemagpie",
    "ai_voice_assistant\tts_eval_outputs"
)

Write-Host "Private paths that must stay untracked:"
foreach ($path in $privatePaths) {
    if (Test-Path -LiteralPath $path) {
        Write-Host "  present: $path"
    }
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "git was not found. The audit cannot prove that private paths are untracked."
}

$insideWorkTree = git rev-parse --is-inside-work-tree 2>$null
if ($LASTEXITCODE -ne 0 -or $insideWorkTree -ne "true") {
    throw "This directory is not a Git worktree. The private-path audit failed closed."
}

# README.md placeholders inside private dirs are intentionally tracked
$allowedFiles = @(
    "ai_voice_assistant/models/README.md",
    "ai_voice_assistant/schedule_state/README.md",
    "ai_voice_assistant/whiteboard_state/README.md",
    "ai_voice_assistant/voice_profiles/README.md",
    "ai_voice_assistant/whisper_audio_archive/README.md"
)
$trackedPrivate = @(git ls-files -- $privatePaths)
if ($LASTEXITCODE -ne 0) {
    throw "git ls-files failed. The private-path audit cannot report success."
}

$violations = @($trackedPrivate | Where-Object { $_ -and ($allowedFiles -notcontains $_) })
if ($violations.Count -gt 0) {
    Write-Host ""
    Write-Host "[ERROR] Private files are already tracked:" -ForegroundColor Red
    $violations | Sort-Object -Unique | ForEach-Object { Write-Host "  $_" }
    exit 1
}

Write-Host ""
Write-Host "[OK] No private paths are tracked by Git."
