param(
    [Parameter(Mandatory = $true)][string]$Executable,
    [Parameter(Mandatory = $true)][string]$Pbfx,
    [Parameter(Mandatory = $true)][string]$StdoutPath,
    [Parameter(Mandatory = $true)][string]$StderrPath,
    [Parameter(Mandatory = $true)][string]$StatusPath,
    [Parameter(Mandatory = $true)][double]$TimeoutSeconds
)

$ErrorActionPreference = 'Stop'
$workingDirectory = Split-Path -Parent $Pbfx
$batchName = Split-Path -Leaf $Pbfx
$terminalPattern = 'Simulation is done with Success|Simulation done with Failure|not activated|Failed to connect to HASP|Database does not have component'
$process = $null
$timer = [Diagnostics.Stopwatch]::StartNew()
$timedOut = $false
$launchError = $null
$childExitCode = $null
$childPid = 0

function Read-SharedText([string]$Path) {
    try {
        $stream = [IO.File]::Open(
            $Path,
            [IO.FileMode]::Open,
            [IO.FileAccess]::Read,
            [IO.FileShare]::ReadWrite
        )
        $reader = [IO.StreamReader]::new($stream)
        try { return $reader.ReadToEnd() } finally { $reader.Dispose() }
    } catch [IO.IOException] {
        return ''
    }
}

try {
    $quotedBatchName = '"' + $batchName + '"'
    $process = Start-Process `
        -FilePath $Executable `
        -ArgumentList @($quotedBatchName, '2') `
        -WorkingDirectory $workingDirectory `
        -WindowStyle Hidden `
        -RedirectStandardOutput $StdoutPath `
        -RedirectStandardError $StderrPath `
        -PassThru
    $childPid = $process.Id

    while ($timer.Elapsed.TotalSeconds -lt $TimeoutSeconds) {
        $log = (Read-SharedText $StdoutPath) + "`n" + (Read-SharedText $StderrPath)

        if ($log -match $terminalPattern) { break }
        $process.Refresh()
        if ($process.HasExited) { break }
        Start-Sleep -Milliseconds 100
    }
    $process.Refresh()
    if (-not $process.HasExited -and $timer.Elapsed.TotalSeconds -ge $TimeoutSeconds) {
        $timedOut = $true
    }
} catch {
    $launchError = $_.Exception.Message
} finally {
    try {
        if ($null -ne $process) {
            $process.Refresh()
            if (-not $process.HasExited) {
                try { $process.Kill() } catch [InvalidOperationException] {}
                $process.WaitForExit()
            }
            if ($process.HasExited) { $childExitCode = $process.ExitCode }
        }
    } catch {
        if ($null -eq $launchError) { $launchError = $_.Exception.Message }
    } finally {
        $statusJson = [ordered]@{
            pid = $childPid
            exit_code = $childExitCode
            timed_out = $timedOut
        } | ConvertTo-Json
        [IO.File]::WriteAllText(
            $StatusPath,
            $statusJson,
            [Text.UTF8Encoding]::new($false)
        )
    }
}

if ($null -ne $launchError) {
    Add-Content -LiteralPath $StderrPath -Value $launchError -Encoding UTF8
    exit 1
}
exit 0
