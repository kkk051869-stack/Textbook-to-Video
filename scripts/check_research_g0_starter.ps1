param(
    [ValidateSet("development", "pilot", "validation", "locked-test")]
    [string]$Mode = "development",
    [string]$ConfigPath = "",
    [switch]$AllowDirty,
    [switch]$RequireRendering,
    [switch]$RequireLLM
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot
$EffectiveRequireRendering = [bool]$RequireRendering -or $Mode -ne "development"
$EffectiveRequireLLM = [bool]$RequireLLM -or $Mode -ne "development"

function Resolve-ProjectPython {
    $Candidates = @(
        (Join-Path $RepoRoot ".venv/Scripts/python.exe"),
        (Join-Path $RepoRoot ".venv312/Scripts/python.exe")
    )
    foreach ($Candidate in $Candidates) {
        if (Test-Path -LiteralPath $Candidate -PathType Leaf) {
            return (Resolve-Path -LiteralPath $Candidate).Path
        }
    }
    throw "No supported repository Python found. Expected .venv or .venv312; refusing shell default python."
}

function Get-CommandInfo {
    param(
        [string]$Name,
        [string[]]$Arguments
    )
    $Command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($null -eq $Command) {
        return $null
    }
    $Output = @(& $Command.Source @Arguments 2>&1)
    $ExitCode = $LASTEXITCODE
    return [ordered]@{
        path = $Command.Source
        version = [string]($Output | Select-Object -First 1)
        exit_code = $ExitCode
        available = $ExitCode -eq 0
    }
}

function Assert-NotReparsePoint {
    param([string]$Path, [string]$Label)
    if (Test-Path -LiteralPath $Path) {
        $Item = Get-Item -LiteralPath $Path -Force
        if (($Item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "$Label must not be a symlink, junction, or other reparse point: $Path"
        }
    }
}

Write-Host "[1/8] Checking required files and hashes..."
$Required = @(
    "contracts/research_generation_v2.schema.json",
    "contracts/ab_experiment_config_v1.schema.json",
    "contracts/ab_dataset_manifest_v1.schema.json",
    "contracts/ab_frozen_file_manifest_v1.schema.json",
    "configs/experiments/ab_single_lesson_pilot.template.json",
    "datasets/research_generation_v2/mock_v0.1/package_manifest.json",
    "datasets/research_generation_v2/reference/a_visual_support_gold_v0.1/human_reviewed_gold.json",
    "tests/test_research_generation_contract.py"
)
$RequiredHashes = [ordered]@{}
foreach ($Path in $Required) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Missing required file: $Path"
    }
    $RequiredHashes[$Path] = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}
$FreezeDoc = Get-ChildItem -LiteralPath "docs" -Recurse -File -Filter "G0_*.md" |
    Where-Object { $_.Name -like "G0_*" } |
    Select-Object -First 1
if ($null -eq $FreezeDoc) {
    throw "Missing G0 freeze document under docs."
}
$FreezeRelative = (Resolve-Path -LiteralPath $FreezeDoc.FullName -Relative) -replace "^[.][\\/]", ""
$FreezeRelative = $FreezeRelative.Replace("\", "/")
$RequiredHashes[$FreezeRelative] = (
    Get-FileHash -LiteralPath $FreezeDoc.FullName -Algorithm SHA256
).Hash.ToLowerInvariant()

Write-Host "[2/8] Resolving the repository Python and dependencies..."
$Python = Resolve-ProjectPython
$PythonProbe = @'
import importlib.metadata as metadata
import json
import platform
import sys

from jsonschema import Draft202012Validator  # noqa: F401

packages = {}
for name in ("jsonschema", "playwright", "edge-tts", "litellm", "pytest", "ruff"):
    try:
        packages[name] = metadata.version(name)
    except metadata.PackageNotFoundError:
        packages[name] = None

print(json.dumps({
    "executable": sys.executable,
    "version": platform.python_version(),
    "version_info": list(sys.version_info[:3]),
    "platform": platform.platform(),
    "packages": packages,
}, ensure_ascii=False))
'@
$PythonInfo = ($PythonProbe | & $Python - | ConvertFrom-Json)
if ([int]$PythonInfo.version_info[0] -lt 3 -or (
        [int]$PythonInfo.version_info[0] -eq 3 -and [int]$PythonInfo.version_info[1] -lt 11
    )) {
    throw "Python 3.11+ required, found $($PythonInfo.version) at $Python"
}
$JsonschemaVersion = [version]$PythonInfo.packages.jsonschema
if ($JsonschemaVersion -lt [version]"4.18") {
    throw "jsonschema>=4.18 required, found $JsonschemaVersion"
}
Write-Host "  Python $($PythonInfo.version): $Python"
Write-Host "  jsonschema $JsonschemaVersion; Draft202012Validator import OK"

Write-Host "[3/8] Checking Git identity and worktree state..."
$Branch = (git branch --show-current).Trim()
$Commit = (git rev-parse HEAD).Trim()
$StatusLines = @(git status --short)
$IsDirty = $StatusLines.Count -gt 0
$Upstream = (git rev-parse --abbrev-ref --symbolic-full-name "@{u}" 2>$null)
$Ahead = $null
$Behind = $null
if ($Mode -ne "development" -and $Upstream) {
    git fetch --quiet
    if ($LASTEXITCODE -ne 0) {
        throw "Formal mode requires a successful remote fetch before comparing HEAD with upstream."
    }
}
if ($LASTEXITCODE -eq 0 -and $Upstream) {
    $Counts = (git rev-list --left-right --count "HEAD...$Upstream").Trim() -split "\s+"
    $Ahead = [int]$Counts[0]
    $Behind = [int]$Counts[1]
}
if ($IsDirty -and -not $AllowDirty) {
    throw "Git worktree is dirty. Commit/stash reviewed changes or rerun development preflight with -AllowDirty."
}
if ($Mode -ne "development" -and $AllowDirty) {
    throw "-AllowDirty is only permitted in development mode."
}
if ($Mode -ne "development") {
    if (-not $Upstream) {
        throw "Formal mode requires a configured upstream branch."
    }
    if ($Ahead -ne 0 -or $Behind -ne 0) {
        throw "Formal mode requires HEAD to equal upstream; found ahead=$Ahead behind=$Behind."
    }
    if (-not $ConfigPath) {
        throw "Formal mode requires -ConfigPath pointing to a RUNNABLE frozen experiment config."
    }
}
Write-Host "  branch=$Branch commit=$Commit dirty=$IsDirty upstream=$Upstream ahead=$Ahead behind=$Behind"

Write-Host "[4/8] Validating G0 contract, frozen gold, A/B config, and Pilot exporter..."
& $Python -m pytest tests/test_research_generation_contract.py tests/test_a_visual_support_gold.py tests/test_ab_experiment_config.py tests/test_research_pilot.py -q
if ($LASTEXITCODE -ne 0) {
    throw "Research contract tests failed."
}
$ConfigInfo = $null
if ($ConfigPath) {
    $ConfigArgs = @(
        "-m", "textbook2video.research.experiment_config", $ConfigPath,
        "--repo-root", $RepoRoot, "--expected-mode", $Mode
    )
    if ($Mode -eq "development") {
        $ConfigArgs += "--allow-template"
    }
    $ConfigOutput = & $Python @ConfigArgs
    if ($LASTEXITCODE -ne 0) {
        throw "A/B experiment config validation failed."
    }
    $ConfigInfo = $ConfigOutput | ConvertFrom-Json
    if ($ConfigInfo.config_status -eq "RUNNABLE") {
        if ($ConfigInfo.branch -ne $Branch) {
            throw "Config branch $($ConfigInfo.branch) does not match current branch $Branch."
        }
        if ($Mode -ne "development") {
            git ls-files --error-unmatch -- $ConfigInfo.config_path 2>$null | Out-Null
            if ($LASTEXITCODE -ne 0) {
                throw "Formal experiment config must be tracked in Git: $($ConfigInfo.config_path)"
            }
            foreach ($InputPath in $ConfigInfo.verified_paths) {
                git ls-files --error-unmatch -- $InputPath 2>$null | Out-Null
                if ($LASTEXITCODE -ne 0) {
                    throw "Formal frozen input reference must be tracked in Git: $InputPath"
                }
            }
        }
    }
}

Write-Host "[5/8] Checking runtime tools..."
$FfmpegCommand = if ($env:FFMPEG_PATH) { $env:FFMPEG_PATH } else { "ffmpeg" }
$FfmpegInfo = Get-CommandInfo -Name $FfmpegCommand -Arguments @("-version")
$FfprobeCommand = if ($env:FFPROBE_PATH) {
    $env:FFPROBE_PATH
} elseif ($env:FFMPEG_PATH -and [IO.Path]::IsPathRooted($env:FFMPEG_PATH)) {
    Join-Path (Split-Path -Parent $env:FFMPEG_PATH) "ffprobe.exe"
} else {
    "ffprobe"
}
$FfprobeInfo = Get-CommandInfo -Name $FfprobeCommand -Arguments @("-version")
$LibreOfficeInfo = Get-CommandInfo -Name "soffice" -Arguments @("--version")
$BrowserProbe = @'
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

with sync_playwright() as playwright:
    path = Path(playwright.chromium.executable_path)
    chromium_available = False
    chromium_error_type = None
    if path.is_file():
        try:
            browser = playwright.chromium.launch(executable_path=str(path), headless=True)
            browser.close()
            chromium_available = True
        except Exception as exc:  # Report only exception type; never serialize command lines.
            chromium_error_type = type(exc).__name__
    msedge_available = False
    msedge_error_type = None
    try:
        browser = playwright.chromium.launch(channel="msedge", headless=True)
        browser.close()
        msedge_available = True
    except Exception as exc:  # Report only exception type; never serialize command lines.
        msedge_error_type = type(exc).__name__
    print(json.dumps({
        "chromium_executable": str(path),
        "chromium_exists": path.is_file(),
        "chromium_available": chromium_available,
        "chromium_error_type": chromium_error_type,
        "msedge_available": msedge_available,
        "msedge_error_type": msedge_error_type,
    }))
'@
$BrowserInfo = ($BrowserProbe | & $Python - | ConvertFrom-Json)
$BrowserReady = [bool]$BrowserInfo.chromium_available -or [bool]$BrowserInfo.msedge_available
$FfmpegReady = $null -ne $FfmpegInfo -and [bool]$FfmpegInfo.available
$FfprobeReady = $null -ne $FfprobeInfo -and [bool]$FfprobeInfo.available
if ($EffectiveRequireRendering -and -not $FfmpegReady) {
    throw "ffmpeg is required for rendering but was not found."
}
if ($EffectiveRequireRendering -and -not $FfprobeReady) {
    throw "ffprobe is required for rendered-video verification but was not found."
}
if ($EffectiveRequireRendering -and -not $BrowserReady) {
    throw "A Playwright browser (bundled Chromium or Microsoft Edge) is required for rendering but was not found."
}
if (-not $FfmpegReady) {
    Write-Warning "ffmpeg not found; schema work can continue, rendering cannot."
}
if (-not $FfprobeReady) {
    Write-Warning "ffprobe not found; rendered-video verification cannot run."
}
if (-not $BrowserReady) {
    Write-Warning "No Playwright browser found; browser-backed checks may skip."
}

Write-Host "[6/8] Checking LLM credential presence without exposing values..."
$CredentialProbe = @'
import json
import os
from pathlib import Path

from textbook2video.pipeline.config import select_llm_config

api_key, base_url, model = select_llm_config()
if os.getenv("LLM_API_KEY") and os.getenv("LLM_BASE_URL"):
    provider = "generic"
elif os.getenv("OPENAI_API_KEY") and os.getenv("OPENAI_BASE_URL"):
    provider = "openai"
elif os.getenv("ECNU_API_KEY") and os.getenv("ECNU_BASE_URL", "https://chat.ecnu.edu.cn/open/api/v1"):
    provider = "ecnu"
else:
    provider = None

print(json.dumps({
    "present": bool(api_key and base_url),
    "selected_provider": provider,
    "endpoint_present": bool(base_url),
    "model_present": bool(model),
    "dotenv_file_present": (Path.cwd() / ".env").is_file(),
    "generic_pair_present": bool(os.getenv("LLM_API_KEY") and os.getenv("LLM_BASE_URL")),
    "openai_pair_present": bool(os.getenv("OPENAI_API_KEY") and os.getenv("OPENAI_BASE_URL")),
    "ecnu_key_present": bool(os.getenv("ECNU_API_KEY")),
}))
'@
$CredentialInfo = ($CredentialProbe | & $Python - | ConvertFrom-Json)
if ($EffectiveRequireLLM -and -not $CredentialInfo.present) {
    throw "LLM credentials are required for mode=$Mode but no complete supported key/base-url pair is configured."
}
if ($ConfigInfo -and $ConfigInfo.config_status -eq "RUNNABLE" -and $CredentialInfo.present -and (
        $ConfigInfo.provider -ne $CredentialInfo.selected_provider
    )) {
    throw "Config provider $($ConfigInfo.provider) does not match selected credential provider $($CredentialInfo.selected_provider)."
}
if (-not $CredentialInfo.present) {
    Write-Warning "LLM credentials are not configured; static/schema work can continue, model-backed runs cannot."
}

Write-Host "[7/8] Writing an environment snapshot without secrets..."
$LocalStateRoot = [IO.Path]::GetFullPath((Join-Path $RepoRoot ".local"))
$SnapshotRoot = [IO.Path]::GetFullPath((Join-Path $LocalStateRoot "research_preflight"))
Assert-NotReparsePoint -Path $LocalStateRoot -Label ".local"
if (-not (Test-Path -LiteralPath $LocalStateRoot -PathType Container)) {
    New-Item -ItemType Directory -Path $LocalStateRoot | Out-Null
}
Assert-NotReparsePoint -Path $LocalStateRoot -Label ".local"
if (-not (Test-Path -LiteralPath $SnapshotRoot -PathType Container)) {
    New-Item -ItemType Directory -Path $SnapshotRoot | Out-Null
}
Assert-NotReparsePoint -Path $SnapshotRoot -Label ".local/research_preflight"
$SnapshotName = "environment_snapshot_{0}_{1}.json" -f (
    [DateTimeOffset]::UtcNow.ToString("yyyyMMddTHHmmssfffffffZ")
), ([guid]::NewGuid().ToString("N"))
$SnapshotTarget = Join-Path $SnapshotRoot $SnapshotName
$FontsPath = Join-Path $env:WINDIR "Fonts"
$Snapshot = [ordered]@{
    schema_version = "t2v-research-environment-snapshot-v0.1"
    captured_at_utc = [DateTimeOffset]::UtcNow.ToString("o")
    mode = $Mode
    repository = [ordered]@{
        root = $RepoRoot
        branch = $Branch
        commit = $Commit
        dirty = $IsDirty
        dirty_entries = $StatusLines
        upstream = if ($Upstream) { $Upstream.Trim() } else { $null }
        ahead = $Ahead
        behind = $Behind
    }
    python = $PythonInfo
    runtime_tools = [ordered]@{
        ffmpeg = $FfmpegInfo
        ffprobe = $FfprobeInfo
        playwright_chromium = $BrowserInfo
        browser_ready = $BrowserReady
        libreoffice = $LibreOfficeInfo
        windows_fonts_path = $FontsPath
        windows_fonts_present = Test-Path -LiteralPath $FontsPath -PathType Container
    }
    credentials = [ordered]@{
        llm = $CredentialInfo
    }
    experiment_config = $ConfigInfo
    required_file_sha256 = $RequiredHashes
    checks = [ordered]@{
        draft202012_validator = "PASS"
        research_contract_tests = "PASS"
        dirty_allowed_for_this_run = [bool]$AllowDirty
        rendering_required = $EffectiveRequireRendering
        llm_required = $EffectiveRequireLLM
        formal_config_required = $Mode -ne "development"
    }
}
$SnapshotJson = $Snapshot | ConvertTo-Json -Depth 10
$SnapshotBytes = ([Text.UTF8Encoding]::new($false)).GetBytes($SnapshotJson + [Environment]::NewLine)
$SnapshotStream = [IO.FileStream]::new(
    $SnapshotTarget,
    [IO.FileMode]::CreateNew,
    [IO.FileAccess]::Write,
    [IO.FileShare]::None
)
try {
    $SnapshotStream.Write($SnapshotBytes, 0, $SnapshotBytes.Length)
} finally {
    $SnapshotStream.Dispose()
}
Write-Host "  snapshot=$SnapshotTarget"

Write-Host "[8/8] Preflight result..."
Write-Host "G0 starter preflight passed for mode=$Mode."
