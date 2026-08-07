param(
    [string]$RepoUrl = "https://github.com/AIGeeksGroup/PresentAgent.git",
    [string]$Commit = "b9990e990c86c3709e18e9979bc36ac959d3b4d4",
    [string]$BuildDir = "presentagent-repo-build",
    [string]$Output = "PresentAgent-repo-b9990e9.tar.gz"
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (Test-Path $BuildDir) {
    Remove-Item -LiteralPath $BuildDir -Recurse -Force
}

git clone $RepoUrl $BuildDir
git -C $BuildDir checkout $Commit
git -C $BuildDir reset --hard $Commit

if (Test-Path $Output) {
    Remove-Item -LiteralPath $Output -Force
}

tar -czf $Output $BuildDir
Get-FileHash $Output -Algorithm SHA256 | Format-List
