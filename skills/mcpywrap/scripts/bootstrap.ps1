param(
    [string]$Version,
    [string]$GitRef,
    [string]$EditablePath,
    [string]$Python = '3.12',
    [string[]]$RequireCapability = @(),
    [string]$Remote,
    [switch]$Local,
    [switch]$Upgrade
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding
$env:PYTHONIOENCODING = 'utf-8'
try {
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if (!$uv) { throw '需要 uv：https://docs.astral.sh/uv/getting-started/installation/' }
    $scriptArgs = @('run', '--no-project', '--python', $Python, (Join-Path $PSScriptRoot 'bootstrap.py'), '--python', $Python)
    if ($Version) { $scriptArgs += @('--version', $Version) }
    if ($GitRef) { $scriptArgs += @('--git-ref', $GitRef) }
    if ($EditablePath) { $scriptArgs += @('--editable-path', $EditablePath) }
    if ($Remote) { $scriptArgs += @('--remote', $Remote) }
    if ($Local) { $scriptArgs += '--local' }
    if ($Upgrade) { $scriptArgs += '--upgrade' }
    foreach ($capability in $RequireCapability) { $scriptArgs += @('--require-capability', $capability) }
    & $uv.Source @scriptArgs
    exit $LASTEXITCODE
} catch {
    @{ ok = $false; error = $_.Exception.Message } | ConvertTo-Json -Compress
    exit 1
}
