$ErrorActionPreference = "Stop"

[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
$requestText = [Console]::In.ReadToEnd()
$request = $requestText | ConvertFrom-Json
$outputDir = [System.IO.Path]::GetFullPath([string]$request.output_dir)
[System.IO.Directory]::CreateDirectory($outputDir) | Out-Null

Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $requestedVoice = [string]$request.voice
    $installed = @($synth.GetInstalledVoices() | Where-Object { $_.Enabled })
    $selected = $installed | Where-Object { $_.VoiceInfo.Name -eq $requestedVoice } | Select-Object -First 1
    if ($null -eq $selected) {
        $selected = $installed | Where-Object { $_.VoiceInfo.Culture.Name -eq "zh-CN" } | Select-Object -First 1
    }
    if ($null -eq $selected) {
        throw "No enabled zh-CN System.Speech voice is installed."
    }
    $synth.SelectVoice($selected.VoiceInfo.Name)
    $synth.Rate = [Math]::Max(-10, [Math]::Min(10, [int]$request.rate))

    $outputs = @()
    for ($index = 0; $index -lt $request.segments.Count; $index++) {
        $path = Join-Path $outputDir ("s{0}.wav" -f ($index + 1))
        $synth.SetOutputToWaveFile($path)
        $synth.Speak([string]$request.segments[$index])
        $synth.SetOutputToNull()
        $outputs += $path
    }
    [pscustomobject]@{
        voice = $selected.VoiceInfo.Name
        rate = $synth.Rate
        outputs = $outputs
    } | ConvertTo-Json -Compress
}
finally {
    $synth.Dispose()
}
