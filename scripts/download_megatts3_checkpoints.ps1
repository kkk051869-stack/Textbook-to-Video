param(
    [string]$OutputDir = "PresentAgent-MegaTTS3-checkpoints",
    [string]$OutputTar = "PresentAgent-MegaTTS3-checkpoints.tar.gz",
    [string]$PrimaryBaseUrl = "https://hf-mirror.com/ByteDance/MegaTTS3/resolve/main",
    [string]$FallbackBaseUrl = "https://huggingface.co/ByteDance/MegaTTS3/resolve/main",
    [int]$MaxTimeSeconds = 7200,
    [int]$AttemptsPerFile = 6
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$files = @(
    @{ Path = ".gitattributes"; Size = 1574 },
    @{ Path = "README.md"; Size = 7635 },
    @{ Path = "aligner_lm/config.yaml"; Size = 2335 },
    @{ Path = "aligner_lm/model_only_last.ckpt"; Size = 218434266 },
    @{ Path = "config.json"; Size = 68 },
    @{ Path = "diffusion_transformer/config.yaml"; Size = 2301 },
    @{ Path = "diffusion_transformer/model_only_last.ckpt"; Size = 1836341777 },
    @{ Path = "duration_lm/config.yaml"; Size = 2720 },
    @{ Path = "duration_lm/model_only_last.ckpt"; Size = 267955084 },
    @{ Path = "g2p/added_tokens.json"; Size = 573857 },
    @{ Path = "g2p/config.json"; Size = 757 },
    @{ Path = "g2p/generation_config.json"; Size = 117 },
    @{ Path = "g2p/latest"; Size = 16 },
    @{ Path = "g2p/merges.txt"; Size = 1671853 },
    @{ Path = "g2p/model.safetensors"; Size = 1018490136 },
    @{ Path = "g2p/special_tokens_map.json"; Size = 616 },
    @{ Path = "g2p/tokenizer.json"; Size = 14796960 },
    @{ Path = "g2p/tokenizer_config.json"; Size = 3210300 },
    @{ Path = "g2p/trainer_state.json"; Size = 789603 },
    @{ Path = "g2p/vocab.json"; Size = 2776833 },
    @{ Path = "wavvae/config.yaml"; Size = 3566 },
    @{ Path = "wavvae/decoder.ckpt"; Size = 904541298 }
)

function Get-FileSize($Path) {
    if (Test-Path -LiteralPath $Path) {
        return (Get-Item -LiteralPath $Path).Length
    }
    return -1
}

function Download-One($RelativePath, $ExpectedSize) {
    $target = Join-Path $OutputDir $RelativePath
    $targetDir = Split-Path -Parent $target
    if ($targetDir) {
        New-Item -ItemType Directory -Force -Path $targetDir | Out-Null
    }

    $existingSize = Get-FileSize $target
    if ($existingSize -eq $ExpectedSize) {
        Write-Host "OK $RelativePath ($ExpectedSize bytes)"
        return
    }
    if ($existingSize -gt $ExpectedSize) {
        Write-Warning "Local file is larger than expected, restarting $RelativePath"
        Remove-Item -LiteralPath $target -Force
    }

    $encodedPath = ($RelativePath -split "/" | ForEach-Object { [uri]::EscapeDataString($_) }) -join "/"
    $urls = @(
        "$PrimaryBaseUrl/$encodedPath",
        "$FallbackBaseUrl/$encodedPath"
    )

    for ($attempt = 1; $attempt -le $AttemptsPerFile; $attempt++) {
        foreach ($url in $urls) {
            Write-Host "Downloading $RelativePath from $url (attempt $attempt/$AttemptsPerFile)"
            curl.exe -L -C - --fail --retry 8 --retry-all-errors --retry-delay 5 --connect-timeout 30 --max-time $MaxTimeSeconds -o $target $url
            $actualSize = Get-FileSize $target
            if ($actualSize -eq $ExpectedSize) {
                Write-Host "OK $RelativePath ($actualSize bytes)"
                return
            }
            Write-Warning "Size mismatch for $RelativePath`: expected $ExpectedSize, got $actualSize"
        }
        Start-Sleep -Seconds 5
    }

    throw "Failed to download $RelativePath with expected size $ExpectedSize"
}

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

foreach ($file in $files) {
    Download-One $file.Path $file.Size
}

if (Test-Path -LiteralPath $OutputTar) {
    Remove-Item -LiteralPath $OutputTar -Force
}

Write-Host "Packing $OutputTar ..."
tar -czf $OutputTar $OutputDir

Write-Host "Hashes:"
Get-FileHash $OutputTar -Algorithm SHA256 | Format-List

Write-Host "Done."
