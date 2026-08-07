param(
    [Parameter(Mandatory=$true)]
    [string]$Url,
    [Parameter(Mandatory=$true)]
    [string]$Output,
    [Parameter(Mandatory=$true)]
    [Int64]$ExpectedSize,
    [int]$Connections = 12,
    [int]$ChunkSizeMb = 64,
    [int]$MaxTimeSeconds = 3600
)

$ErrorActionPreference = "Stop"

function Get-FileSize($Path) {
    if (Test-Path -LiteralPath $Path) {
        return (Get-Item -LiteralPath $Path).Length
    }
    return -1
}

$Output = [System.IO.Path]::GetFullPath($Output)
$outputDir = Split-Path -Parent $Output
if ($outputDir) {
    New-Item -ItemType Directory -Force -Path $outputDir | Out-Null
}

$currentSize = Get-FileSize $Output
if ($currentSize -eq $ExpectedSize) {
    Write-Host "OK $Output ($ExpectedSize bytes)"
    exit 0
}
if ($currentSize -gt $ExpectedSize) {
    throw "Output is larger than expected: $currentSize > $ExpectedSize"
}

$partRoot = "$Output.parts"
New-Item -ItemType Directory -Force -Path $partRoot | Out-Null

$ranges = New-Object System.Collections.Generic.List[object]
if ($currentSize -gt 0) {
    $seedPart = Join-Path $partRoot ("{0:D10}-{1:D10}.part" -f 0, ($currentSize - 1))
    if ((Get-FileSize $seedPart) -ne $currentSize) {
        Copy-Item -LiteralPath $Output -Destination $seedPart -Force
    }
    $start = [Int64]$currentSize
} else {
    $start = [Int64]0
}

$chunkSize = [Int64]$ChunkSizeMb * 1024 * 1024
while ($start -lt $ExpectedSize) {
    $end = [Math]::Min($ExpectedSize - 1, $start + $chunkSize - 1)
    $partPath = Join-Path $partRoot ("{0:D10}-{1:D10}.part" -f $start, $end)
    $ranges.Add([pscustomobject]@{
        Start = $start
        End = $end
        Size = $end - $start + 1
        Path = $partPath
    }) | Out-Null
    $start = $end + 1
}

function Start-RangeJob($Range) {
    Start-Job -ArgumentList $Url, $Range.Start, $Range.End, $Range.Size, $Range.Path, $MaxTimeSeconds -ScriptBlock {
        param($Url, [Int64]$Start, [Int64]$End, [Int64]$Size, $Path, $MaxTimeSeconds)
        $ErrorActionPreference = "Stop"
        function Get-FileSize($Path) {
            if (Test-Path -LiteralPath $Path) {
                return (Get-Item -LiteralPath $Path).Length
            }
            return -1
        }
        if ((Get-FileSize $Path) -eq $Size) {
            return "skip $Start-$End"
        }
        if ((Get-FileSize $Path) -gt $Size) {
            Remove-Item -LiteralPath $Path -Force
        }
        $rangeHeader = "$Start-$End"
        for ($attempt = 1; $attempt -le 6; $attempt++) {
            & curl.exe -L --fail --silent -r $rangeHeader --retry 6 --retry-all-errors --retry-delay 3 --connect-timeout 30 --max-time $MaxTimeSeconds -o $Path $Url 2>$null
            if ((Get-FileSize $Path) -eq $Size) {
                return "ok $Start-$End"
            }
            if (Test-Path -LiteralPath $Path) {
                Remove-Item -LiteralPath $Path -Force
            }
            Start-Sleep -Seconds 3
        }
        throw "failed $Start-$End expected $Size got $(Get-FileSize $Path)"
    }
}

$pending = New-Object System.Collections.Queue
foreach ($range in $ranges) {
    if ((Get-FileSize $range.Path) -ne $range.Size) {
        $pending.Enqueue($range)
    }
}

$jobs = @()
while ($pending.Count -gt 0 -or $jobs.Count -gt 0) {
    while ($pending.Count -gt 0 -and $jobs.Count -lt $Connections) {
        $range = $pending.Dequeue()
        Write-Host ("start {0}-{1}" -f $range.Start, $range.End)
        $jobs += Start-RangeJob $range
    }

    Start-Sleep -Seconds 5
    $done = $jobs | Where-Object { $_.State -ne "Running" }
    foreach ($job in $done) {
        Receive-Job $job
        if ($job.State -ne "Completed") {
            $state = $job.State
            Remove-Job $job -Force
            throw "A range download job ended with state $state"
        }
        Remove-Job $job -Force
    }
    $jobs = $jobs | Where-Object { $_.State -eq "Running" }

    $downloaded = $currentSize
    foreach ($range in $ranges) {
        $size = Get-FileSize $range.Path
        if ($size -gt 0) {
            $downloaded += [Math]::Min($size, $range.Size)
        }
    }
    $percent = [Math]::Round(($downloaded / $ExpectedSize) * 100, 2)
    Write-Host "progress $downloaded/$ExpectedSize bytes ($percent%)"
}

$orderedParts = Get-ChildItem -LiteralPath $partRoot -Filter "*.part" | Sort-Object Name
$total = ($orderedParts | Measure-Object -Property Length -Sum).Sum
if ($total -ne $ExpectedSize) {
    throw "Part total size mismatch: expected $ExpectedSize, got $total"
}

$tmp = "$Output.tmp"
if (Test-Path -LiteralPath $tmp) {
    Remove-Item -LiteralPath $tmp -Force
}

$outStream = [System.IO.File]::Open($tmp, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write)
try {
    foreach ($part in $orderedParts) {
        $inStream = [System.IO.File]::OpenRead($part.FullName)
        try {
            $inStream.CopyTo($outStream)
        } finally {
            $inStream.Dispose()
        }
    }
} finally {
    $outStream.Dispose()
}

if ((Get-FileSize $tmp) -ne $ExpectedSize) {
    throw "Combined file size mismatch"
}

Move-Item -LiteralPath $tmp -Destination $Output -Force
Remove-Item -LiteralPath $partRoot -Recurse -Force
Write-Host "OK $Output ($ExpectedSize bytes)"
