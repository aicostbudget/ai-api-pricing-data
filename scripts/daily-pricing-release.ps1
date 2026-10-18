[CmdletBinding(DefaultParameterSetName = "Validate")]
param(
    [Parameter(ParameterSetName = "Validate")][switch]$Validate,
    [Parameter(ParameterSetName = "Publish", Mandatory = $true)][switch]$Publish,
    [string]$DatasetPath = (Split-Path -Parent $PSScriptRoot),
    [string]$WebsitePath
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $DatasetPath
if (-not $WebsitePath) {
    $WebsitePath = Join-Path (Split-Path -Parent $DatasetPath) "ai-cost-control-tool\aicostguard-english"
}
$Action = if ($Publish) { "publish" } else { "validate" }
& python -m scripts.daily_pricing_release $Action --dataset-root $DatasetPath --website-root $WebsitePath
if ($LASTEXITCODE -ne 0) { throw "Daily pricing release $Action failed with exit code $LASTEXITCODE" }
