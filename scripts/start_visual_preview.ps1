param(
    [Parameter(Mandatory = $true)][string]$OutputDir,
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9]+(,[0-9]+)*$')][string]$Segments,
    [Parameter(Mandatory = $true)][string]$SnapshotPath,
    [ValidateSet('ecnu-plus', 'ecnu-max')][string]$Model = 'ecnu-plus',
    [ValidateSet('ecnu-plus', 'ecnu-max')][string]$ReviewModel = $Model,
    [string]$VisualCacheDir = '.local/visual-cache',
    [switch]$NoVisualCache,
    [ValidateRange(1, 5)][int]$MaxIterations = 5,
    [ValidateSet('strict', 'development')][string]$ReviewPolicy = 'development',
    [string]$Storyboard = 'datasets/research_generation_v2/frozen/ab-real-lessons-dev-v1/cases/lesson_002/baseline/storyboard.json',
    [string]$Source = 'datasets/research_generation_v2/frozen/ab-real-lessons-dev-v1/cases/lesson_002/source/source.md'
)
$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
Set-Location -LiteralPath $repo
$output = [IO.Path]::GetFullPath((Join-Path $repo $OutputDir))
$allowed = [IO.Path]::GetFullPath((Join-Path $repo '.local/ordinary-course')) +
    [IO.Path]::DirectorySeparatorChar
if (-not $output.StartsWith($allowed, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Preview output must remain inside .local/ordinary-course.'
}
$ancestor = [IO.DirectoryInfo]::new([IO.Path]::GetDirectoryName($output))
while ($null -ne $ancestor -and $ancestor.FullName.Length -ge $repo.Length) {
    if ($ancestor.Exists -and ($ancestor.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'Preview output ancestors must not be junctions or symbolic links.'
    }
    $ancestor = $ancestor.Parent
}
$jobDir = $output + '.job'
if ((Test-Path -LiteralPath $output) -or (Test-Path -LiteralPath $jobDir)) {
    throw 'Output or job directory already exists; choose a new run ID.'
}
$snapshotFile = (Resolve-Path -LiteralPath $SnapshotPath).Path
$snapshot = Get-Content -LiteralPath $snapshotFile -Raw | ConvertFrom-Json
$commit = git rev-parse HEAD
if ($LASTEXITCODE -ne 0) { throw 'Cannot read Git HEAD.' }
$dirty = git status --porcelain
if ($LASTEXITCODE -ne 0 -or $dirty) { throw 'Preview launch requires a clean committed worktree.' }
if ($snapshot.mode -ne 'development' -or $snapshot.repository.commit -ne $commit -or
    $snapshot.repository.dirty -or $snapshot.repository.root -ne $repo) {
    throw 'Use a clean development preflight snapshot for this exact worktree and commit.'
}
$python = (Resolve-Path -LiteralPath (Join-Path $repo '.venv/Scripts/python.exe')).Path
if ($snapshot.python.executable -ne $python) { throw 'Snapshot interpreter does not match.' }
$boardPath = (Resolve-Path -LiteralPath $Storyboard).Path
$sourcePath = (Resolve-Path -LiteralPath $Source).Path
$scriptPath = Join-Path $repo 'scripts/preview_visual_agent.py'
# Each quoted value is a filesystem path; no shell is asked to interpret it.
$arguments = @('-u', ('"' + $scriptPath + '"'), '--storyboard', ('"' + $boardPath + '"'),
    '--source', ('"' + $sourcePath + '"'), '--segments', $Segments,
    '--output-dir', ('"' + $output + '"'), '--model', $Model,
    '--review-model', $ReviewModel,
    '--max-iterations', [string]$MaxIterations, '--review-policy', $ReviewPolicy, '--course-plan', '--before-tts')
New-Item -ItemType Directory -Path $jobDir | Out-Null
if ($NoVisualCache) {
    $arguments += '--no-visual-cache'
} else {
    $cachePath = if ([IO.Path]::IsPathRooted($VisualCacheDir)) {
        [IO.Path]::GetFullPath($VisualCacheDir)
    } else {
        [IO.Path]::GetFullPath((Join-Path $repo $VisualCacheDir))
    }
    $arguments += @('--visual-cache-dir', ('"' + $cachePath + '"'))
}
$env:LITELLM_LOCAL_MODEL_COST_MAP = 'True'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$stdout = Join-Path $jobDir 'stdout.log'
$stderr = Join-Path $jobDir 'stderr.log'
$process = Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $repo `
    -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
$record = [ordered]@{
    scope = 'development preview; not a formal experiment manifest'
    pid = $process.Id
    started_at_utc = $process.StartTime.ToUniversalTime().ToString('o')
    commit = $commit
    snapshot = $snapshotFile
    snapshot_sha256 = (Get-FileHash -LiteralPath $snapshotFile -Algorithm SHA256).Hash.ToLowerInvariant()
    storyboard = $boardPath
    storyboard_sha256 = (Get-FileHash -LiteralPath $boardPath -Algorithm SHA256).Hash.ToLowerInvariant()
    source = $sourcePath
    source_sha256 = (Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash.ToLowerInvariant()
    output_dir = $output
    model = $Model
    review_model = $ReviewModel
    max_iterations = $MaxIterations
    review_policy = $ReviewPolicy
    stdout = $stdout
    stderr = $stderr
}
$record | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $jobDir 'job.json') -Encoding utf8
$record | ConvertTo-Json -Depth 4
