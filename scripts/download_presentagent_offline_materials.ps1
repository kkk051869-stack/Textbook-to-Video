param(
    [string]$Mirror = "https://mirrors.aliyun.com/pypi/simple/",
    [string]$LibreOfficeUrl = "https://mirrors.nju.edu.cn/tdf/libreoffice/stable/25.8.7/deb/x86_64/LibreOffice_25.8.7_Linux_x86-64_deb.tar.gz",
    [int]$MaxTimeSeconds = 1800
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$RemainingDir = Join-Path $Root "PresentAgent-wheelhouse-remaining-py311-linux"
$RemainingTar = Join-Path $Root "PresentAgent-wheelhouse-remaining-py311-linux.tar.gz"
$LibreOfficeTar = Join-Path $Root "LibreOffice_25.8.7_Linux_x86-64_deb.tar.gz"

New-Item -ItemType Directory -Force -Path $RemainingDir | Out-Null

Write-Host "Downloading remaining PresentAgent Python wheels..."
$binaryRequirements = Get-Content "presentagent-requirements-remaining-offline.txt" |
  Where-Object { $_ -and ($_ -notmatch "^\s*#") -and ($_ -notmatch "^openai-whisper") }

python -m pip download `
  --progress-bar off `
  --only-binary=:all: `
  --platform manylinux2014_x86_64 `
  --python-version 3.11 `
  --implementation cp `
  --abi cp311 `
  --dest $RemainingDir `
  --index-url $Mirror `
  --find-links "PresentAgent-wheelhouse-core-py311-linux" `
  --find-links "PresentAgent-wheelhouse-torch-py311-linux" `
  --find-links "presentagent-wheelhouse-marker-py311-linux" `
  $binaryRequirements

Write-Host "Downloading openai-whisper source package and runtime wheels..."
python -m pip download `
  --progress-bar off `
  --no-deps `
  --dest $RemainingDir `
  --index-url $Mirror `
  "openai-whisper==20240930"

python -m pip download `
  --progress-bar off `
  --only-binary=:all: `
  --platform manylinux2014_x86_64 `
  --python-version 3.11 `
  --implementation cp `
  --abi cp311 `
  --dest $RemainingDir `
  --index-url $Mirror `
  --find-links "PresentAgent-wheelhouse-core-py311-linux" `
  --find-links "PresentAgent-wheelhouse-torch-py311-linux" `
  --find-links "presentagent-wheelhouse-marker-py311-linux" `
  more-itertools numba llvmlite triton

Write-Host "Packing remaining wheelhouse..."
if (Test-Path $RemainingTar) {
    Remove-Item -LiteralPath $RemainingTar -Force
}
tar -czf $RemainingTar "PresentAgent-wheelhouse-remaining-py311-linux"

Write-Host "Downloading LibreOffice package with resume..."
curl.exe -L -C - --retry 10 --retry-delay 5 --connect-timeout 30 --max-time $MaxTimeSeconds -o $LibreOfficeTar $LibreOfficeUrl

Write-Host "Hashes:"
Get-FileHash $RemainingTar, $LibreOfficeTar -Algorithm SHA256 | Format-Table -AutoSize

Write-Host "Done."
