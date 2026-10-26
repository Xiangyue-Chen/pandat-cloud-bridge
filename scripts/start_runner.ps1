param(
    [string]$PandatExe = '',
    [string]$DatabasePath = '',
    [string]$TemplatePath = '',
    [string]$RunnerRoot = '',
    [int]$TimeoutSeconds = 7200,
    [switch]$ValidateOnly
)

$ErrorActionPreference = 'Stop'
if (-not $PandatExe) { $PandatExe = if ($env:PANDAT_EXE) { $env:PANDAT_EXE } else { 'D:\bin\Pandat.exe' } }
if (-not $DatabasePath) { $DatabasePath = $env:PANDAT_DATABASE_PATH }
if (-not $TemplatePath) {
    $TemplatePath = if ($env:PANDAT_TEMPLATE_PATH) {
        $env:PANDAT_TEMPLATE_PATH
    } else {
        Join-Path (Split-Path $PSScriptRoot -Parent) 'config\line-template.pbfx'
    }
}
if (-not $RunnerRoot) { $RunnerRoot = $env:GITHUB_RUNNER_ROOT }

$required = [ordered]@{
    PANDAT_EXE = $PandatExe
    PANDAT_DATABASE_PATH = $DatabasePath
    PANDAT_TEMPLATE_PATH = $TemplatePath
}
foreach ($entry in $required.GetEnumerator()) {
    if (-not $entry.Value -or -not (Test-Path -LiteralPath $entry.Value -PathType Leaf)) {
        throw "$($entry.Key) is not configured or does not point to a file"
    }
}
$runCommand = if ($RunnerRoot) { Join-Path $RunnerRoot 'run.cmd' } else { '' }
if (-not $runCommand -or -not (Test-Path -LiteralPath $runCommand -PathType Leaf)) {
    throw 'GITHUB_RUNNER_ROOT is not configured or run.cmd is missing'
}
if ($TimeoutSeconds -lt 1 -or $TimeoutSeconds -gt 7200) {
    throw 'TimeoutSeconds must be between 1 and 7200'
}

$env:PANDAT_EXE = (Resolve-Path -LiteralPath $PandatExe).Path
$env:PANDAT_DATABASE_PATH = (Resolve-Path -LiteralPath $DatabasePath).Path
$env:PANDAT_TEMPLATE_PATH = (Resolve-Path -LiteralPath $TemplatePath).Path
$env:PANDAT_TIMEOUT_SECONDS = [string]$TimeoutSeconds

if ($ValidateOnly) {
    Write-Output 'Pandat workstation and existing GitHub runner are ready.'
    exit 0
}

Push-Location -LiteralPath $RunnerRoot
try {
    & $runCommand
    exit $LASTEXITCODE
} finally {
    Pop-Location
}

