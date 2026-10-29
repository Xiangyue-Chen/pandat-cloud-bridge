param(
    [string]$PandatExe = '',
    [string]$DatabaseCatalog = '',
    [string]$TemplatePath = '',
    [string]$RunnerRoot = '',
    [switch]$Json
)

$ErrorActionPreference = 'Stop'
if (-not $PandatExe) { $PandatExe = if ($env:PANDAT_EXE) { $env:PANDAT_EXE } else { 'D:\bin\Pandat.exe' } }
if (-not $DatabaseCatalog) {
    $DatabaseCatalog = if ($env:PANDAT_DATABASE_CATALOG) {
        $env:PANDAT_DATABASE_CATALOG
    } else {
        Join-Path (Split-Path $PSScriptRoot -Parent) 'config\databases.json'
    }
}
if (-not $TemplatePath) {
    $TemplatePath = if ($env:PANDAT_TEMPLATE_PATH) {
        $env:PANDAT_TEMPLATE_PATH
    } else {
        Join-Path (Split-Path $PSScriptRoot -Parent) 'config\line-template.pbfx'
    }
}
if (-not $RunnerRoot) { $RunnerRoot = $env:GITHUB_RUNNER_ROOT }

$state = [ordered]@{
    ready = $false
    pandat = [bool]($PandatExe -and (Test-Path -LiteralPath $PandatExe -PathType Leaf))
    catalog = [bool]($DatabaseCatalog -and (Test-Path -LiteralPath $DatabaseCatalog -PathType Leaf))
    template = [bool]($TemplatePath -and (Test-Path -LiteralPath $TemplatePath -PathType Leaf))
    runner = [bool]($RunnerRoot -and (Test-Path -LiteralPath (Join-Path $RunnerRoot 'run.cmd') -PathType Leaf))
}
$state.ready = $state.pandat -and $state.catalog -and $state.template -and $state.runner

if ($Json) {
    $state | ConvertTo-Json -Compress
} else {
    [pscustomobject]$state | Format-List
}
if (-not $state.ready) { exit 1 }

