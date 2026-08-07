param(
    [string]$HostAlias = "digital_book",
    [string]$RemoteUploadDir = "/ai/data/textbook-to-video/uploads",
    [string]$RemoteRepoDir = "/ai/data/repos/Textbook-to-Video"
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$requiredFiles = @(
    "TextbookEval-v1-formal-review.zip",
    "cpython-3.11.13+20250610-x86_64-unknown-linux-gnu-install_only.tar.gz",
    "PresentAgent-wheelhouse-core-py311-linux.tar.gz",
    "PresentAgent-wheelhouse-torch-py311-linux.tar.gz",
    "PresentAgent-wheelhouse-marker-py311-linux.tar.gz",
    "PresentAgent-wheelhouse-remaining-py311-linux.tar.gz",
    "LibreOffice_25.8.7_Linux_x86-64_deb.tar.gz",
    "tiktoken-cache-o200k\fb374d419588a4632f3f557e76b4b70aebbca790"
)

$missing = @()
foreach ($file in $requiredFiles) {
    if (-not (Test-Path $file)) {
        $missing += $file
    }
}
if ($missing.Count -gt 0) {
    Write-Error ("Missing required files:`n" + ($missing -join "`n"))
}

$lo = Get-Item "LibreOffice_25.8.7_Linux_x86-64_deb.tar.gz"
if ($lo.Length -lt 200MB) {
    Write-Error "LibreOffice package is incomplete: $($lo.Length) bytes. Re-run scripts\download_presentagent_offline_materials.ps1 first."
}

ssh $HostAlias "mkdir -p $RemoteUploadDir $RemoteRepoDir/scripts"

scp `
  "TextbookEval-v1-formal-review.zip" `
  "cpython-3.11.13+20250610-x86_64-unknown-linux-gnu-install_only.tar.gz" `
  "PresentAgent-wheelhouse-core-py311-linux.tar.gz" `
  "PresentAgent-wheelhouse-torch-py311-linux.tar.gz" `
  "PresentAgent-wheelhouse-marker-py311-linux.tar.gz" `
  "PresentAgent-wheelhouse-remaining-py311-linux.tar.gz" `
  "LibreOffice_25.8.7_Linux_x86-64_deb.tar.gz" `
  "${HostAlias}:${RemoteUploadDir}/"

scp "tiktoken-cache-o200k\fb374d419588a4632f3f557e76b4b70aebbca790" "${HostAlias}:${RemoteUploadDir}/o200k_base_cache"

scp `
  "scripts\check_presentagent_imports.py" `
  "scripts\install_presentagent_cloud.sh" `
  "scripts\run_presentagent_baseline.py" `
  "scripts\prepare_b_cloud_materials.py" `
  "scripts\validate_b_cloud_materials.py" `
  "${HostAlias}:${RemoteRepoDir}/scripts/"

Write-Host "Upload finished. Next command on cloud:"
Write-Host "cd $RemoteRepoDir && bash scripts/install_presentagent_cloud.sh"
