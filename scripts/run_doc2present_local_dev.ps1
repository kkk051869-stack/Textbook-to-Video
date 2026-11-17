param(
    [ValidateSet('Verify','Compare','Audio','MediaPrepare','Render','Record','Report','Run')]
    [string]$Stage='Verify',
    [string]$Document='',
    [ValidateSet('','legacy','semantic','simple_rule','proposition_aware','without_signaling')]
    [string]$Condition=''
)
$ErrorActionPreference='Stop'
$repo=Split-Path -Parent $PSScriptRoot
Push-Location $repo
try {
    $python=Join-Path $repo '.venv/Scripts/python.exe'
    $env:LITELLM_LOCAL_MODEL_COST_MAP='True'
    $env:PYTHONUTF8='1'
    $env:PYTHONPATH=Join-Path $repo 'src'
    if(-not $env:T2V_FFMPEG) { $env:T2V_FFMPEG=Join-Path $repo '.local/tools-20261030/ffmpeg.exe' }
    if(-not $env:T2V_FFPROBE) { $env:T2V_FFPROBE=Join-Path $repo '.local/tools-20261030/ffprobe.exe' }
    $env:FFMPEG_PATH=$env:T2V_FFMPEG
    $env:FFPROBE_PATH=$env:T2V_FFPROBE
    $packages=@(
        @{Runner='scripts/run_rq1_doc2present_v2.py';Package='.local/doc2present-local-dev-20261109/ready-v2/rq1'},
        @{Runner='scripts/run_rq2_binding_dev.py';Package='.local/doc2present-local-dev-20261109/ready-v2/rq2'}
    )
    foreach($item in $packages) {
        $snapshot=Join-Path $repo ($item.Package+'/code_snapshot')
        if(-not (Test-Path -LiteralPath $snapshot)) { throw "Missing prepared package: $snapshot" }
        foreach($file in Get-ChildItem -LiteralPath $snapshot -Recurse -File) {
            $relative=[IO.Path]::GetRelativePath($snapshot,$file.FullName)
            if($relative -match '^(scripts|src|tests|configs)[\\/]') {
                $live=Join-Path $repo $relative
                if(-not (Test-Path -LiteralPath $live)) { throw "Missing source: $relative" }
                if((Get-FileHash -LiteralPath $live).Hash -ne (Get-FileHash -LiteralPath $file.FullName).Hash) {
                    throw "Source changed since preparation: $relative; prepare a new package."
                }
            }
        }
        & $python $item.Runner verify --package-root $item.Package
        if($LASTEXITCODE -ne 0) { throw "Package verification failed: $($item.Package)" }
    }
    if($Stage -in @('Compare','Run')) {
        & ./scripts/check_research_g0_starter.ps1 -Mode development -AllowDirty -RequireRendering
        if($LASTEXITCODE -ne 0) { throw 'Development preflight failed before model comparison.' }
        foreach($item in $packages) {
            & $python $item.Runner execute --package-root $item.Package
            if($LASTEXITCODE -ne 0) { throw "Comparison stopped: $($item.Package); failure preserved." }
        }
    }
    if($Stage -eq 'Run') {
        $root='.local/doc2present-local-dev-20261109/media-v2'
        $sharedArgs=@('--package-root',$packages[1].Package,'--output',$root,
            '--rq1-package-root',$packages[0].Package)
        $partialFailure=$false
        foreach($phase in @('audio','prepare','render')) {
            & $python scripts/run_doc2present_local_media.py $phase @sharedArgs
            if($LASTEXITCODE -ne 0) {
                if($phase -eq 'audio') { throw 'Shared audio failed; no recording attempted.' }
                $partialFailure=$true
            }
        }
        $tasks=Get-Content -LiteralPath ($packages[1].Package+'/inputs/tasks.json') -Raw | ConvertFrom-Json
        $modes=(Get-Content -LiteralPath ($root+'/media-execution-contract.json') -Raw | ConvertFrom-Json).modes
        foreach($doc in ($tasks.document_id | Select-Object -Unique)) {
            foreach($mode in $modes) {
                if(-not (Test-Path -LiteralPath "$root/$doc/$mode/compiled.json")) { continue }
                & $python scripts/run_doc2present_local_media.py record @sharedArgs --document $doc --mode $mode
                if($LASTEXITCODE -ne 0) { $partialFailure=$true }
            }
        }
        & $python scripts/run_doc2present_local_media.py report @sharedArgs
        if($LASTEXITCODE -ne 0 -or $partialFailure) { throw 'Experiment partial/failed; inspect evidence-index and preserved failures.' }
    } elseif($Stage -notin @('Verify','Compare')) {
        $commands=@{Audio='audio';MediaPrepare='prepare';Render='render';Record='record';Report='report'}
        $mediaArgs=@('scripts/run_doc2present_local_media.py',$commands[$Stage],
            '--package-root',$packages[1].Package,'--output','.local/doc2present-local-dev-20261109/media-v2',
            '--rq1-package-root',$packages[0].Package)
        if($Document) { $mediaArgs+=@('--document',$Document) }
        if($Condition) { $mediaArgs+=@('--mode',$Condition) }
        & $python @mediaArgs
        if($LASTEXITCODE -ne 0) { throw "Media stage failed: $Stage; failure preserved." }
    }
} finally { Pop-Location }
