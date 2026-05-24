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
    "ai_voice_assistant\whisper_audio_archive",
    "ai_voice_assistant\voice_profiles",
    "ai_voice_assistant\agent_workspace",
    "ai_voice_assistant\models",
    "ai_voice_assistant\venv"
)

Write-Host "Private paths that must stay untracked:"
foreach ($path in $privatePaths) {
    if (Test-Path -LiteralPath $path) {
        Write-Host "  present: $path"
    }
}

if (Test-Path -LiteralPath ".git") {
    # README.md placeholders inside private dirs are intentionally tracked
    $allowedFiles = @(
        "ai_voice_assistant/models/README.md",
        "ai_voice_assistant/voice_profiles/README.md",
        "ai_voice_assistant/whisper_audio_archive/README.md"
    )
    $trackedPrivate = @()
    foreach ($path in $privatePaths) {
        $trackedPrivate += git ls-files -- $path
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
} else {
    Write-Host ""
    Write-Host "Git is not initialized yet. Run this script again after git init and git add."
}
