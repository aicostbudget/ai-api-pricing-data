[CmdletBinding(DefaultParameterSetName = "Prepare")]
param(
    [Parameter(ParameterSetName = "Prepare")][switch]$Prepare,
    [Parameter(ParameterSetName = "Publish", Mandatory = $true)][switch]$Publish,
    [string]$DatasetPath = (Split-Path -Parent $PSScriptRoot),
    [string]$WebsitePath,
    [Parameter(ParameterSetName = "Prepare")][string]$GeneratedAt
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $DatasetPath
if (-not $WebsitePath) {
    $WebsitePath = Join-Path (Split-Path -Parent $DatasetPath) "ai-cost-control-tool\aicostguard-english"
}
$action = if ($Publish) { "publish" } else { "prepare" }
$arguments = @("scripts/daily_pricing_release.py", $action, "--dataset-root", $DatasetPath, "--website-root", $WebsitePath)
if ($GeneratedAt) { $arguments += @("--generated-at", $GeneratedAt) }
& python @arguments
if ($LASTEXITCODE -ne 0) { throw "Daily pricing release $action failed with exit code $LASTEXITCODE" }
