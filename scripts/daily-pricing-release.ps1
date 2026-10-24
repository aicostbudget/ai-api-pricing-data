[CmdletBinding(DefaultParameterSetName = "Validate")]
param(
    [Parameter(ParameterSetName = "Validate")][switch]$Validate,
    [Parameter(ParameterSetName = "Prepare", Mandatory = $true)][switch]$Prepare,
    [Parameter(ParameterSetName = "Publish", Mandatory = $true)][switch]$Publish,
    [Parameter(ParameterSetName = "Publish")][switch]$Follow,
    [Parameter(ParameterSetName = "Rehearse", Mandatory = $true)][switch]$Rehearse,
    [Parameter(ParameterSetName = "Rehearse")][switch]$SkipTests,
    [string]$DatasetPath = (Split-Path -Parent $PSScriptRoot),
    [string]$WebsitePath
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $DatasetPath
if (-not $WebsitePath) {
    $WebsitePath = Join-Path (Split-Path -Parent $DatasetPath) "ai-cost-control-tool\aicostguard-english"
}
$Action = if ($Publish) { "publish" } elseif ($Rehearse) { "rehearse" } elseif ($Prepare) { "prepare" } else { "validate" }
# @(...) keeps a one-flag result an array; a bare string would splat character by character.
$Extra = @(if ($SkipTests) { "--skip-tests" } elseif ($Follow) { "--follow" })
& python -m scripts.daily_pricing_release $Action --dataset-root $DatasetPath --website-root $WebsitePath @Extra
if ($LASTEXITCODE -ne 0) { throw "Daily pricing release $Action failed with exit code $LASTEXITCODE" }
