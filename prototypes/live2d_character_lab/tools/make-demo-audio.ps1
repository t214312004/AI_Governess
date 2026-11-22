$ErrorActionPreference = 'Stop'
$labRoot = Split-Path -Parent $PSScriptRoot
$audioDir = Join-Path $labRoot 'fixtures/audio'
New-Item -ItemType Directory -Path $audioDir -Force | Out-Null
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $voices = $synth.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.Name -eq 'zh-TW' }
    if ($voices) { $synth.SelectVoice(($voices | Select-Object -First 1).VoiceInfo.Name) }
    $synth.SetOutputToWaveFile((Join-Path $audioDir 'demo.wav'))
    $synth.Speak([System.IO.File]::ReadAllText((Join-Path $PSScriptRoot 'demo-speech.txt'), [System.Text.Encoding]::UTF8))
} finally { $synth.Dispose() }
Write-Output 'Created new local synthetic speech fixture.'
