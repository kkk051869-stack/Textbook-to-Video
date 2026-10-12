$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

Write-Host "[1/4] Checking required files..."
$Required = @(
    "contracts/research_generation_v2.schema.json",
    "datasets/research_generation_v2/mock_v0.1/package_manifest.json",
    "tests/test_research_generation_contract.py"
)
foreach ($Path in $Required) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Missing required file: $Path"
    }
}
$FreezeDoc = Get-ChildItem -LiteralPath "docs" -Recurse -File -Filter "G0_*.md" |
    Where-Object { $_.Name -like "G0_*" } |
    Select-Object -First 1
if ($null -eq $FreezeDoc) {
    throw "Missing G0 freeze document under docs."
}

Write-Host "[2/4] Checking Python..."
python --version

Write-Host "[3/4] Validating G0 contract and Pilot exporter..."
python -m pytest tests/test_research_generation_contract.py tests/test_research_pilot.py -q

Write-Host "[4/4] Checking optional video tools..."
$Ffmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
if ($null -eq $Ffmpeg) {
    Write-Warning "ffmpeg is not installed or not in PATH. Schema/baseline work can continue; rendering cannot."
} else {
    ffmpeg -version | Select-Object -First 1
}

Write-Host "G0 starter is ready."
